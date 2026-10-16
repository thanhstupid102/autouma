"""§12.6 L2 pilot -- career_bot/engine records carry the structured fields.

The engine pilot deliberately edits only the three *binding* points
(runner._run thread entry, the run loop's turn, runner's on_api_log funnel, and
reporting._mark's turn mirror). All 20 `log.*` call sites across
runner/racing/commerce/lifecycle/recovery/reporting/debug are covered *ambiently*
by those binds -- no call site grew boilerplate. These tests prove that claim
both per-module and by driving the real run loop.
"""

import logging
import threading

import pytest

from career_bot.engine import CareerRunner
from career_bot.scenarios.base import Decision
from uma_api.log_context import LOG_FIELDS, current_log_fields, install_log_fields, log_context


ENGINE_LOGGERS = [
    "career_bot.engine.runner",
    "career_bot.engine.racing",
    "career_bot.engine.commerce",
    "career_bot.engine.lifecycle",
    "career_bot.engine.recovery",
    "career_bot.engine.reporting",
    "career_bot.engine.debug",
]


def _inventory_state(turn):
    return {
        "data": {
            "chara_info": {"turn": turn, "playing_state": 1, "skill_point": 0},
            "free_data_set": {"user_item_info_array": [{"item_id": 1001, "num": 2}]},
        },
    }


class _InventoryStrategy:
    """Same shape as tests/test_runner_action_logging.py: turn 11 -> 12 -> done."""

    handles_shop_items = True
    scenario_id = 4

    def next_decision(self, state, preset):
        turn = state["data"]["chara_info"]["turn"]
        if turn == 11:
            return Decision("advance", {"current_turn": turn}, "advance turn")
        return Decision("done", {}, "complete")

    def extra_action_handlers(self):
        return {"advance": self._advance_turn}

    @staticmethod
    def _advance_turn(runner, client, state, preset, payload):
        return _inventory_state(12)


def _silence_notify(monkeypatch):
    import career_bot.engine.runner as runner_module
    monkeypatch.setattr(runner_module.notify, "start_live_monitor", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.notify, "stop_live_monitor", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.notify, "send_career_summary", lambda *a, **k: None)


def _build_runner(tmp_path, account="lewpie", scenario_id=4):
    runner = CareerRunner(tmp_path)
    runner._account = account
    runner.status["scenario_id"] = scenario_id
    strategy = _InventoryStrategy()
    runner.strategy = strategy
    runner._init_debug_log({}, scenario_id=scenario_id)
    runner._debug_turn = lambda *a, **k: None
    runner._buy_skills = lambda client, state, preset, force: state
    return runner, strategy


# --- per-module coverage ------------------------------------------------------

@pytest.mark.parametrize("logger_name", ENGINE_LOGGERS)
def test_every_engine_module_logger_carries_the_fields(caplog, logger_name):
    """The binds are logger-agnostic, so each engine module's module-level
    `log = logging.getLogger(__name__)` is covered without editing that module."""
    install_log_fields()
    caplog.set_level(logging.INFO)
    fields = {
        "account": "lewpie", "scenario_id": 4, "turn": 33,
        "endpoint": "single_mode_free/command", "result_code": 1,
    }
    with log_context(**fields):
        logging.getLogger(logger_name).warning("frozen L1 message text")

    record = caplog.records[-1]
    assert record.name == logger_name
    assert {name: getattr(record, name) for name in LOG_FIELDS} == fields


# --- the real run loop --------------------------------------------------------

def test_run_binds_account_and_scenario_and_releases_them(monkeypatch, tmp_path, caplog):
    install_log_fields()
    caplog.set_level(logging.INFO)
    _silence_notify(monkeypatch)
    runner, strategy = _build_runner(tmp_path, account="lewpie", scenario_id=4)

    runner._run(object(), {}, _inventory_state(11), strategy, max_steps=4)

    engine_records = [r for r in caplog.records if r.name.startswith("career_bot.engine.")]
    assert engine_records, "the scripted career must produce at least one engine log line"
    for record in engine_records:
        assert record.account == "lewpie"
        assert record.scenario_id == 4
    # the scope released on the way out
    assert current_log_fields() == {}


def test_turn_field_follows_the_run_loop(monkeypatch, tmp_path, caplog):
    """`turn` is bound at the TOP of the loop iteration, so even _begin_turn's
    inventory snapshot -- which runs before status["turn"] is marked -- is tagged
    with the turn it is actually reporting."""
    install_log_fields()
    caplog.set_level(logging.INFO)
    _silence_notify(monkeypatch)
    runner, strategy = _build_runner(tmp_path)

    runner._run(object(), {}, _inventory_state(11), strategy, max_steps=4)

    inventory = [r for r in caplog.records if r.getMessage().endswith("Inventory: Speed Notepad 2")]
    assert [r.getMessage().split()[0] for r in inventory] == ["T11", "T12"]
    assert [r.turn for r in inventory] == [11, 12]


def test_start_binds_on_the_runner_thread_not_the_caller(monkeypatch, tmp_path):
    """The load-bearing placement decision, asserted directly.

    A freshly started thread gets an EMPTY context, so binding in start() would
    never reach the runner -- and would leave the calling web/CLI thread tagged
    with one account forever. The bind therefore lives at the top of _run.
    """
    install_log_fields()
    _silence_notify(monkeypatch)
    runner = CareerRunner(tmp_path)
    observed = {}

    def _fake_run_career(*args, **kwargs):
        observed["fields"] = current_log_fields()
        observed["thread"] = threading.get_ident()

    runner._run_career = _fake_run_career
    runner.start(None, {"name": "p", "scenario_id": 4}, {}, account="yuko")
    runner.thread.join(timeout=10)

    assert observed["thread"] != threading.get_ident()
    assert observed["fields"] == {"account": "yuko", "scenario_id": 4}
    # the caller's thread was never touched
    assert current_log_fields() == {}


def test_on_api_log_funnel_binds_endpoint_and_result_code(monkeypatch, tmp_path, caplog):
    """One hook on the client's api_log callback gives every later engine record
    the endpoint and the game result_code, with zero per-call-site boilerplate.
    client.call() emits RES *before* it raises on rc != 1, so an `except` handler
    logs with the real code in context."""
    install_log_fields()
    _silence_notify(monkeypatch)
    runner = CareerRunner(tmp_path)
    runner._run_career = lambda *a, **k: None

    class _Client:
        report = None
        on_api_log = None

    client = _Client()
    runner.start(client, {"name": "p", "scenario_id": 4}, {}, account="lewpie")
    runner.thread.join(timeout=10)

    hook = client.on_api_log
    assert callable(hook)
    with log_context():  # keep the probe's writes off the shared test thread
        hook("REQ", "single_mode_free/race_entry", {"payload": {"current_turn": 11}}, "r1")
        assert current_log_fields() == {
            "endpoint": "single_mode_free/race_entry", "result_code": None,
        }
        hook("RES", "single_mode_free/race_entry", {"data_headers": {"result_code": 205}}, "r1")
        assert current_log_fields() == {
            "endpoint": "single_mode_free/race_entry", "result_code": 205,
        }
        # ...and a real engine log line emitted after it carries both, which is the
        # point: racing.py's "Race Entry Error at turn N" site was not edited.
        caplog.set_level(logging.WARNING)
        logging.getLogger("career_bot.engine.racing").warning(
            "Race Entry Error at turn 11: API error 205 on single_mode_free/race_entry")
        assert caplog.records[-1].endpoint == "single_mode_free/race_entry"
        assert caplog.records[-1].result_code == 205
        # a transport ERR has no data_headers -> no invented result_code
        hook("ERR", "single_mode_free/race_entry", {"error": "Network error"}, "r1")
        assert current_log_fields()["result_code"] is None
    assert current_log_fields() == {}


def test_two_runner_threads_do_not_share_account_fields(monkeypatch, tmp_path):
    """Two CareerRunners started concurrently, as the multi-account run loop does."""
    install_log_fields()
    _silence_notify(monkeypatch)
    seen = {}
    ready = threading.Barrier(2)

    def make(account, scenario_id):
        runner = CareerRunner(tmp_path / account)

        def _fake_run_career(*args, **kwargs):
            ready.wait(timeout=10)          # both threads bound before either reads
            seen[account] = current_log_fields()

        runner._run_career = _fake_run_career
        runner.start(None, {"name": account, "scenario_id": scenario_id}, {}, account=account)
        return runner

    runners = [make("lewpie", 4), make("yuko", 2)]
    for runner in runners:
        runner.thread.join(timeout=10)

    assert seen == {
        "lewpie": {"account": "lewpie", "scenario_id": 4},
        "yuko": {"account": "yuko", "scenario_id": 2},
    }
    assert current_log_fields() == {}
