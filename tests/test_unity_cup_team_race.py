import pytest

from career_bot.engine import CareerRunner, _format_verbose_response_log, _slim_api_data
from career_bot.scenarios.unity_cup import UnityCupStrategy
from career_bot.scenarios.unity_cup.team_race import (
    _continue_limit,
    _continue_type,
    run_team_race,
)
from uma_api.errors import ApiError


def team_state(turn=24):
    # team_data_set.team_data_array itself is null on this response in the real
    # game (the server only fills it in after team_edit) -- the roster below
    # (trainee + one on-team scout, one off-team scout excluded) is what
    # TeamRosterBuilder.build builds client-side from chara_info +
    # evaluation_info_array. card_id 999999 / chara_id 9999999 are outside any
    # real master.mdb id range, so this is deterministic whether or not
    # master.mdb is present (falls back to card_id // 100 and a default
    # aptitude respectively either way).
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "card_id": 999999,
                "proper_distance_short": 7,
                "proper_distance_mile": 1,
                "proper_distance_middle": 1,
                "proper_distance_long": 1,
                "proper_running_style_nige": 1,
                "proper_running_style_senko": 1,
                "proper_running_style_sashi": 7,
                "proper_running_style_oikomi": 1,
                "proper_ground_turf": 7,
                "proper_ground_dirt": 1,
            },
            "team_data_set": {
                "team_data_array": None,
                "evaluation_info_array": [
                    {"target_id": 1, "chara_id": 9999999, "member_state": 1, "soul_threshold_id": 5, "soul_event_state": 0},
                    {"target_id": 2, "chara_id": 8888888, "member_state": 0, "soul_threshold_id": 1, "soul_event_state": 0},
                ],
            },
        }
    }


class FakeTeamClient:
    def __init__(self, out_data=None, opponent_data=None):
        self.calls = []
        self.edit_payloads = []
        self.analyze_ids = []
        self.continues = []
        self.out_data = out_data or {}
        # Default opponent_list response mirrors the real shape: an
        # opponent_info_array with a team_race_set_id per entry, and
        # _team_race_set_id picks the entry with the highest team_power.
        self.opponent_data = opponent_data if opponent_data is not None else {
            "team_data_set": {"opponent_info_array": [{"team_power": 100, "team_race_set_id": 301}]},
        }

    def team_edit(self, team_data_array, current_turn):
        self.calls.append("team_edit")
        self.edit_payloads.append((team_data_array, current_turn))
        return {"data_headers": {"sid": "server-sid", "result_code": 1}, "data": {"chara_info": {"turn": current_turn}}}

    def opponent_list(self, current_turn):
        self.calls.append("opponent_list")
        return {"data": self.opponent_data}

    def team_race_analyze(self, race_set_id, current_turn):
        self.calls.append("team_race_analyze")
        self.analyze_ids.append(race_set_id)
        return {"data": {"chara_info": {"turn": current_turn}}}

    def team_race_start(self, team_race_set_id, current_turn):
        self.calls.append("team_race_start")
        return {"data": {"chara_info": {"turn": current_turn}}}

    def team_race_end(self, current_turn):
        self.calls.append("team_race_end")
        return {"data": {"chara_info": {"turn": current_turn}}}

    def team_race_out(self, current_turn):
        self.calls.append("team_race_out")
        return {"data": {"chara_info": {"turn": current_turn}, **self.out_data}}

    def team_race_continue(self, current_turn, continue_type=1):
        self.calls.append("team_race_continue")
        self.continues.append((current_turn, continue_type))
        self.out_data = {}
        return {"data": {"chara_info": {"turn": current_turn}}}


def test_team_race_normal_sequence_and_fallback_race_set_id(tmp_path):
    # "fallback" here now means the single-opponent default (opponent_info_array
    # highest-team_power selection), not the removed UNITY_TEAM_RACE_SET_IDS
    # hardcoded turn->id table.
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = False
    client = FakeTeamClient()

    run_team_race(runner, client, team_state(24), {"scenario_id": 2}, {"current_turn": 24})

    assert client.calls == [
        "team_edit",
        "opponent_list",
        "team_race_analyze",
        "team_race_start",
        "team_race_end",
        "team_race_out",
    ]
    assert client.analyze_ids == [301]
    assert client.edit_payloads[0][0] == [
        {"distance_type": 1, "member_id": 1, "chara_id": 9999, "running_style": 3},
        {"distance_type": 2, "member_id": 1, "chara_id": 9999999, "running_style": 2},
    ]


def test_team_race_playing_states_not_blocked(tmp_path):
    # playing_state 7 (team race ready), 8 (race started), 9 (race ended) are
    # normal Unity Cup states -- treating them as blocked made the runner
    # reload + break with "blocked state 7" (live failure
    # career_log_lewpie_20260708_230039). 6 (minigame) stays blocked/recovered.
    runner = CareerRunner(tmp_path)
    runner.strategy = UnityCupStrategy()
    for ps in (1, 2, 3, 4, 5, 7, 8, 9):
        assert not runner._blocked_playing_state({"playing_state": ps}), ps
    assert runner._blocked_playing_state({"playing_state": 6})


def test_team_race_resume_from_playing_state_8_skips_edit_and_start(tmp_path):
    # Resuming a career that died mid team-race (ps 8: race already started
    # server-side) must not re-run team_edit/opponent_list/team_race_start.
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = False
    client = FakeTeamClient()

    run_team_race(runner, client, team_state(24), {"scenario_id": 2}, {"current_turn": 24, "playing_state": 8})

    assert client.calls == ["team_race_end", "team_race_out"]


def test_team_race_resume_from_playing_state_8_recovers_retry_budget(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    client = FakeTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 1}
    )
    state = team_state(24)
    state["data"]["team_data_set"]["opponent_info_array"] = [
        {"team_power": 100, "team_race_set_id": 301},
    ]

    run_team_race(
        runner,
        client,
        state,
        {"scenario_id": 2},
        {"current_turn": 24, "playing_state": 8},
    )

    assert client.continues == [(24, 1)]
    assert client.analyze_ids == [301]


def test_team_race_resume_from_playing_state_9_only_outs(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = False
    client = FakeTeamClient()

    run_team_race(runner, client, team_state(24), {"scenario_id": 2}, {"current_turn": 24, "playing_state": 9})

    assert client.calls == ["team_race_out"]


def test_team_race_burn_clocks_false_never_continues(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = False
    client = FakeTeamClient({"available_free_continue_num": 1})

    run_team_race(runner, client, team_state(60), {"scenario_id": 2}, {"current_turn": 60})

    assert "team_race_continue" not in client.calls
    assert client.continues == []


def test_team_race_burn_clocks_true_continues_once_when_available(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    client = FakeTeamClient({"available_continue_num": 1, "available_free_continue_num": 1})

    run_team_race(runner, client, team_state(60), {"scenario_id": 2}, {"current_turn": 60})

    assert client.continues == [(60, 1)]
    assert client.calls == [
        "team_edit",
        "opponent_list",
        "team_race_analyze",
        "team_race_start",
        "team_race_end",
        "team_race_out",
        "team_race_continue",
        "team_race_analyze",
        "team_race_start",
        "team_race_end",
        "team_race_out",
    ]


def test_team_race_selects_paid_type_after_free_retry_is_spent():
    response = {
        "data": {
            "home_info": {
                "available_free_continue_num": 0,
                "free_continue_num": 1,
                "available_continue_num": 2,
            }
        }
    }

    assert _continue_type(response) == 2


def test_team_race_retry_limit_comes_from_total_remaining_budget():
    response = {
        "data": {
            "home_info": {
                "available_free_continue_num": 1,
                "free_continue_num": 99,
                "available_continue_num": 2,
            }
        }
    }

    assert _continue_limit(response) == 2


def test_team_race_paid_preflight_false_skips_continue_and_returns_finished_race(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    runner._ensure_alarm_clock = lambda _client, _preset: False
    client = FakeTeamClient(
        {
            "available_continue_num": 2,
            "available_free_continue_num": 0,
            "free_continue_num": 1,
        }
    )

    result = run_team_race(
        runner,
        client,
        team_state(60),
        {"scenario_id": 2},
        {"current_turn": 60},
    )

    assert "team_race_continue" not in client.calls
    assert client.calls[-1] == "team_race_out"
    assert result["data"]["chara_info"]["turn"] == 60


def test_team_race_free_retry_never_runs_paid_preflight(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    preflight_calls = []
    runner._ensure_alarm_clock = lambda _client, _preset: preflight_calls.append(1) or False
    client = FakeTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 1}
    )

    run_team_race(
        runner,
        client,
        team_state(60),
        {"scenario_id": 2},
        {"current_turn": 60},
    )

    assert preflight_calls == []
    assert client.continues == [(60, 1)]


def test_team_race_continue_state_recovery_error_propagates(tmp_path):
    error = ApiError(201, "single_mode_team/team_race_continue", "desynced")

    class RecoveringTeamClient(FakeTeamClient):
        def team_race_continue(self, current_turn, continue_type=1):
            self.calls.append("team_race_continue")
            self.continues.append((current_turn, continue_type))
            raise error

    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    client = RecoveringTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 1}
    )

    with pytest.raises(ApiError) as caught:
        run_team_race(
            runner,
            client,
            team_state(60),
            {"scenario_id": 2},
            {"current_turn": 60},
        )

    assert caught.value is error
    assert client.continues == [(60, 1)]
    assert not any(
        row["action"] == "team_race_clock_failed" for row in runner.status["log"]
    )


def test_team_race_continue_blocked_state_propagates_without_marking_done(tmp_path):
    error = ApiError(102, "single_mode_team/team_race_continue", "blocked")

    class BlockedTeamClient(FakeTeamClient):
        def team_race_continue(self, current_turn, continue_type=1):
            self.calls.append("team_race_continue")
            self.continues.append((current_turn, continue_type))
            raise error

    class Strategy:
        def __init__(self):
            self.done_turns = []

        def mark_team_race_done(self, turn):
            self.done_turns.append(turn)

    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    strategy = Strategy()
    client = BlockedTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 1}
    )

    with pytest.raises(ApiError) as caught:
        run_team_race(
            runner,
            client,
            team_state(60),
            {"scenario_id": 2},
            {"current_turn": 60, "_strategy": strategy},
        )

    assert caught.value is error
    assert strategy.done_turns == []


def test_ordinary_team_race_continue_rejection_is_caught(tmp_path):
    class RejectingTeamClient(FakeTeamClient):
        def team_race_continue(self, current_turn, continue_type=1):
            self.calls.append("team_race_continue")
            self.continues.append((current_turn, continue_type))
            raise ApiError(654, "single_mode_team/team_race_continue", "rejected")

    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    runner._ensure_alarm_clock = lambda _client, _preset: True
    client = RejectingTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 0}
    )

    result = run_team_race(
        runner,
        client,
        team_state(60),
        {"scenario_id": 2},
        {"current_turn": 60},
    )

    assert client.continues == [(60, 2)]
    assert result["data"]["chara_info"]["turn"] == 60
    assert any("result_code=654" in row["detail"] for row in runner.status["log"])


def test_team_race_paid_preflight_blocked_state_propagates(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.burn_clocks = True
    error = ApiError(102, "load/index", "blocked")
    runner._ensure_alarm_clock = lambda _client, _preset: (_ for _ in ()).throw(error)
    client = FakeTeamClient(
        {"available_continue_num": 1, "available_free_continue_num": 0}
    )

    with pytest.raises(ApiError) as caught:
        run_team_race(
            runner,
            client,
            team_state(60),
            {"scenario_id": 2},
            {"current_turn": 60},
        )

    assert caught.value is error


def test_unity_cup_api_response_goes_to_terminal_and_career_log():
    response = {"data_headers": {"sid": "server-sid", "result_code": 1}, "data": {"chara_info": {"turn": 24}}}

    line = _format_verbose_response_log("single_mode_team/exec_command", response, 0)
    row = _slim_api_data("RES", "single_mode_team/exec_command", response, verbose=True)

    assert line.startswith("[Unity Cup T24] single_mode_team/exec_command server_response:")
    assert '"turn": 24' in line
    assert "server-sid" not in line
    assert row["server_response"]["data_headers"]["sid"] == "<redacted>"
    assert row["server_response"]["data"]["chara_info"]["turn"] == 24
