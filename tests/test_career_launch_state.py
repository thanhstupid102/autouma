from types import SimpleNamespace

import pytest

from uma_api import game_service
from uma_api.session import Session
from backend.app.services import game_login
from backend.app.domain import account_status, account_store, career_selection, preset_runtime
from backend.app.routers.careers.schemas.career import RunCareerRequest
from backend.app.routers.careers.services.career_service import CareerService


SLEEP = "backend.app.routers.careers.services.career_run.time.sleep"


class RecordingRunner:
    def __init__(self):
        self.start_calls = []
        self.loop_info = None

    def set_loop_info(self, current, target):
        self.loop_info = (current, target)

    def start(self, *args, **kwargs):
        self.start_calls.append((args, kwargs))

    def snapshot(self):
        return {"running": bool(self.start_calls)}


class ImmediateExitRunner(RecordingRunner):
    def snapshot(self):
        return {"running": False, "status": "ok"}

    def stop(self):
        pass


class StoppableRunner(RecordingRunner):
    """A runner that keeps reporting ``running`` until ``stop()`` is called, so the
    loop's ``_await_runner_exit`` poll actually spins.

    ``poll_budget`` is a safety valve, not behaviour: a regression that ignores
    ``loop_stop`` would otherwise poll forever and HANG the suite instead of
    failing it.
    """

    def __init__(self, poll_budget=5):
        super().__init__()
        self.stop_calls = 0
        self.polls = 0
        self.poll_budget = poll_budget
        self._running = False

    def start(self, *args, **kwargs):
        super().start(*args, **kwargs)
        self._running = True

    def stop(self):
        self.stop_calls += 1
        self._running = False

    def snapshot(self):
        self.polls += 1
        if self.polls > self.poll_budget:
            self._running = False
        return {"running": self._running, "status": "ok"}


def make_launch(monkeypatch, tmp_path, start_result, runner=None):
    session = Session(name="launch-state-test", base_dir=str(tmp_path))
    session.client = SimpleNamespace(
        tp_info={},
        coin_info={},
        item_map={},
        reset_circuit=lambda: None,
    )
    session.runner = runner or RecordingRunner()
    req = RunCareerRequest(
        card_id=100101,
        support_card_ids=[],
        friend_viewer_id=1,
        friend_card_id=2,
        parent_id_1=3,
        parent_id_2=4,
        scenario_id=2,
        run_count=1,
    )
    preset = {"name": "launch-state-test", "scenario_id": 2}
    service = CareerService(session)
    monkeypatch.setattr(
        service,
        "start_career_from_request",
        lambda _req: {"success": True, "result": start_result},
    )
    monkeypatch.setattr(account_store, "apply_auto_delete_config", lambda _session: {})
    monkeypatch.setattr(career_selection, "apply_deck_type_counts", lambda *args, **kwargs: None)
    monkeypatch.setattr(preset_runtime, "apply_runtime_bot_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(game_service, "reset_circuit", lambda _session: None)
    return service, session, req, preset


def test_fresh_team_start_unwraps_turn_state_before_launching_runner(monkeypatch, tmp_path):
    start_result = {
        "data": {
            "single_mode_start_common": {
                "chara_info": {
                    "turn": 1,
                    "card_id": 100101,
                    "scenario_id": 2,
                },
                "home_info": {"available_command_array": []},
                "unchecked_event_array": [{"event_id": 3000}],
            },
            "team_data_set": {"team_id": 42},
        }
    }
    service, session, req, preset = make_launch(monkeypatch, tmp_path, start_result)

    def unexpected_load(*args, **kwargs):
        raise AssertionError("fresh start should use its unwrapped result; no load is expected")

    monkeypatch.setattr(game_service, "load_index_live", unexpected_load)
    monkeypatch.setattr(game_service, "load_career", unexpected_load)

    response = service._launch_career_run(req, preset)

    launched_result = session.runner.start_calls[0][0][2]
    assert launched_result["data"]["chara_info"]["turn"] == 1
    assert launched_result["data"]["team_data_set"] == start_result["data"]["team_data_set"]
    assert response["chara_info"] == start_result["data"]["single_mode_start_common"]["chara_info"]


def test_successful_start_without_chara_info_recovers_turn_state(monkeypatch, tmp_path, caplog):
    start_result = {
        "data_headers": {"result_code": 1},
        "data": {"single_mode_start_common": {}, "team_data_set": {"team_id": 42}},
    }
    recovered = {
        "data_headers": {"result_code": 1},
        "data": {"chara_info": {"turn": 1, "card_id": 100101, "scenario_id": 2}},
    }
    service, session, req, preset = make_launch(monkeypatch, tmp_path, start_result)
    calls = []
    monkeypatch.setattr(game_service, "load_index_live", lambda *_args: calls.append("index") or {"data": {}})
    monkeypatch.setattr(game_service, "load_career", lambda *_args: calls.append("career") or recovered)

    response = service._launch_career_run(req, preset)

    assert calls == ["index", "career"]
    assert response["chara_info"]["turn"] == 1
    assert "recovering turn state with load/index + career load" in caplog.text


def test_failed_start_without_chara_info_does_not_load_recovery_state(monkeypatch, tmp_path):
    start_result = {"data_headers": {"result_code": 102}, "data": {}}
    service, _session, req, preset = make_launch(monkeypatch, tmp_path, start_result)

    def unexpected_load(*_args):
        raise AssertionError("failed start must not trigger turn-state recovery")

    monkeypatch.setattr(game_service, "load_index_live", unexpected_load)
    monkeypatch.setattr(game_service, "load_career", unexpected_load)

    with pytest.raises(RuntimeError, match=r"missing chara_info \(result_code=102\)"):
        service._launch_career_run(req, preset)


@pytest.mark.parametrize("failure_point", ["index", "career"])
def test_missing_chara_info_recovery_keeps_original_condition_visible(
        monkeypatch, tmp_path, caplog, failure_point):
    start_result = {"data_headers": {"result_code": 1}, "data": {}}
    service, _session, req, preset = make_launch(monkeypatch, tmp_path, start_result)

    def load_index(*_args):
        if failure_point == "index":
            raise RuntimeError("index failed")
        return {"data": {}}

    def load_career(*_args):
        if failure_point == "career":
            raise RuntimeError("career failed")
        return {"data": {}}

    monkeypatch.setattr(game_service, "load_index_live", load_index)
    monkeypatch.setattr(game_service, "load_career", load_career)

    with pytest.raises(RuntimeError, match="response omitted chara_info; turn-state recovery failed"):
        service._launch_career_run(req, preset)

    assert "successful start response missing chara_info" in caplog.text
    assert "turn-state recovery failed" in caplog.text


def test_loop_next_career_unwraps_before_runner(monkeypatch, tmp_path):
    wrapped_result = {
        "data": {
            "single_mode_start_common": {
                "chara_info": {
                    "turn": 1,
                    "card_id": 100101,
                    "scenario_id": 2,
                },
                "home_info": {},
                "unchecked_event_array": [{"event_id": 3000}],
            },
            "team_data_set": {"team_id": 42},
        }
    }
    runner = ImmediateExitRunner()
    service, session, req, preset = make_launch(
        monkeypatch,
        tmp_path,
        wrapped_result,
        runner=runner,
    )
    session.client.login = lambda: {"data": {}}
    req.run_count = 2
    initial_result = {
        "data": {
            "chara_info": {
                "turn": 1,
                "card_id": 100101,
                "scenario_id": 2,
            }
        }
    }

    monkeypatch.setattr(SLEEP, lambda *_args: None)
    monkeypatch.setattr(game_service, "login", lambda _session: {"data": {}})
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args, **kwargs: None)

    service.manage_career_loop(req, preset, initial_result)

    assert len(runner.start_calls) == 2
    second_initial_state = runner.start_calls[1][0][2]
    assert second_initial_state["data"]["chara_info"]["turn"] == 1
    assert second_initial_state["data"]["team_data_set"] == {"team_id": 42}


def _no_further_starts(_req):
    raise AssertionError("a stopped loop must not start another career")


def _loop_context(monkeypatch, tmp_path, runner):
    """A 2-career loop whose collaborators are all offline no-ops."""
    service, session, req, preset = make_launch(
        monkeypatch, tmp_path, {"data": {"chara_info": {"turn": 1}}}, runner=runner)
    req.run_count = 2
    session.client.login = lambda: {"data": {}}
    monkeypatch.setattr(game_login, "login_with_master_refresh", lambda _session: {"data": {}})
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args, **kwargs: None)
    return service, session, req, preset


def test_stop_pressed_during_a_running_career_stops_the_runner_and_ends_the_loop(monkeypatch, tmp_path):
    """Pressing Stop while a career is mid-run: the poll must forward the Stop to
    the runner, end the loop, and NOT book the interrupted career as finished."""
    runner = StoppableRunner()
    service, session, req, preset = _loop_context(monkeypatch, tmp_path, runner)
    session.account = {"career": {"active": True}}
    sleeps = []

    def press_stop_on_the_first_poll_tick(seconds):
        sleeps.append(seconds)
        session.loop_stop = True

    monkeypatch.setattr(SLEEP, press_stop_on_the_first_poll_tick)
    monkeypatch.setattr(service, "start_career_from_request", _no_further_starts)

    service.manage_career_loop(req, preset, {"data": {"chara_info": {"turn": 1}}})

    assert runner.stop_calls == 1
    # a real 1s poll tick, not a No-CD dna_sleep that would peg a core
    assert sleeps == [1.0]
    assert len(runner.start_calls) == 1
    assert session.account["career"]["active"] is True


@pytest.mark.parametrize("mode", ["rejected", "raised"])
def test_next_career_start_failures_back_off_fifteen_seconds_and_give_up_after_five(
        monkeypatch, tmp_path, mode):
    runner = ImmediateExitRunner()
    service, session, req, preset = _loop_context(monkeypatch, tmp_path, runner)
    attempts = []
    sleeps = []

    def failing_start(_req):
        attempts.append(mode)
        if mode == "raised":
            raise RuntimeError("start blew up")
        return {"success": False, "detail": "not enough TP"}

    monkeypatch.setattr(SLEEP, sleeps.append)
    monkeypatch.setattr(service, "start_career_from_request", failing_start)

    service.manage_career_loop(req, preset, {"data": {"chara_info": {"turn": 1}}})

    assert len(attempts) == 5
    assert len(runner.start_calls) == 1  # a failed start never launches a runner
    # the 6s inter-career pause, then a 15s backoff after each of the first four
    # failures (the fifth trips the give-up threshold before it can sleep)
    assert sleeps == [1.0] * (6 + 4 * 15)


def test_stop_pressed_during_a_start_failure_backoff_ends_the_loop_at_once(monkeypatch, tmp_path):
    runner = ImmediateExitRunner()
    service, session, req, preset = _loop_context(monkeypatch, tmp_path, runner)
    attempts = []
    sleeps = []

    def press_stop_on_the_third_backoff_tick(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 6 + 3:
            session.loop_stop = True

    monkeypatch.setattr(SLEEP, press_stop_on_the_third_backoff_tick)
    monkeypatch.setattr(
        service, "start_career_from_request",
        lambda _req: (attempts.append("rejected"), {"success": False, "detail": "nope"})[1])

    service.manage_career_loop(req, preset, {"data": {"chara_info": {"turn": 1}}})

    assert len(attempts) == 1
    # 6 inter-career ticks + 3 backoff ticks, then the backoff sees the Stop
    assert sleeps == [1.0] * 9


def test_unwrap_single_mode_start_common_promotes_state_and_keeps_siblings():
    result = {
        "success": True,
        "data": {
            "single_mode_start_common": {
                "chara_info": {"turn": 1, "card_id": 100101, "scenario_id": 2},
                "home_info": {"home": True},
                "team_data_set": {"team_id": 1},
            },
            "team_data_set": {"team_id": 42},
        },
    }

    unwrapped = account_status.unwrap_single_mode_start_common(result)

    assert unwrapped is not result
    assert unwrapped["data"] is not result["data"]
    assert unwrapped["data"]["chara_info"] == result["data"]["single_mode_start_common"]["chara_info"]
    assert unwrapped["data"]["home_info"] == result["data"]["single_mode_start_common"]["home_info"]
    assert unwrapped["data"]["team_data_set"] == result["data"]["team_data_set"]
    assert "chara_info" not in result["data"]


def test_unwrap_single_mode_start_common_noops_for_unwrapped_result():
    result = {"data": {"chara_info": {"turn": 1}, "team_data_set": {"team_id": 42}}}

    assert account_status.unwrap_single_mode_start_common(result) is result


def test_unwrap_single_mode_start_common_noops_when_wrapper_is_missing():
    result = {"data": {"team_data_set": {"team_id": 42}}}

    assert account_status.unwrap_single_mode_start_common(result) is result
