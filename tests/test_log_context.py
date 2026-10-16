"""§12.6 L2 -- the structured-field mechanism itself (uma_api/log_context.py).

The contract these pin, in order of how much they matter:

1. the operator console is BYTE-IDENTICAL to the pre-L2 rendering;
2. the five fields really are on the LogRecord for a machine sink to read;
3. the per-thread isolation the threaded run loop depends on.

`tests/test_engine_log_fields.py` covers the career_bot/engine pilot that uses it.
"""

import io
import logging
import sys
import threading

import pytest

from uma_api.log_context import (
    LOG_FIELDS,
    current_log_fields,
    install_log_fields,
    log_context,
    set_log_fields,
    uninstall_log_fields,
)
from backend.app.logging_setup import configure_console_logging


# A representative slice of the real career_bot/engine log sites, message text
# copied verbatim from the modules so this asserts on genuine operator output
# rather than a toy string. One entry carries a literal '%' and literal braces --
# if anything ever started re-formatting the frozen L1 text, that line breaks first.
SCRIPT = [
    ("career_bot.engine.debug", logging.INFO, "T11 Inventory: Speed Notepad 2"),
    ("career_bot.engine.reporting", logging.INFO,
     "11\ttrain\tSpd | Score: 8.0 (2B, 2RB, 3Ws, 3Bs, 1Ps, 0F)\tHP 100/100 | MOOD 4"),
    ("career_bot.engine.commerce", logging.WARNING, "Skill phase reload failure: boom"),
    ("career_bot.engine.racing", logging.WARNING,
     "Race Entry Error at turn 11: API error 205 on single_mode_free/race_entry"),
    ("career_bot.engine.lifecycle", logging.INFO, "Draining leftover SP (352)..."),
    ("career_bot.engine.recovery", logging.WARNING, "Blocked State Recovery Failure: nope"),
    ("career_bot.engine.runner", logging.WARNING,
     "RUN RETRY 1/5 (reload in place) after error: 100% {failed}"),
    ("career_bot.engine.runner", logging.ERROR, "RUNNER CRASH: kaboom"),
]

EXPECTED_CONSOLE = "".join(f"{message}\n" for _, _, message in SCRIPT)

CAREER_FIELDS = {
    "account": "lewpie",
    "scenario_id": 4,
    "turn": 11,
    "endpoint": "single_mode_free/command",
    "result_code": 1,
}


def _emit_script():
    for name, level, message in SCRIPT:
        logging.getLogger(name).log(level, message)


def _render_through_production_console(bind_fields):
    """Replay SCRIPT through the REAL configure_console_logging() and return stdout.

    `bind_fields=None` reproduces the pre-L2 world: the production handler with the
    stdlib LogRecord and no context at all. Otherwise the L2 factory is installed
    (by configure_console_logging itself) and the fields are bound around the replay.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_factory = logging.getLogRecordFactory()
    saved_stdout = sys.stdout
    buffer = io.StringIO()

    root.handlers.clear()
    sys.stdout = buffer
    try:
        logging.setLogRecordFactory(logging.LogRecord)
        configure_console_logging()
        if bind_fields is None:
            uninstall_log_fields()
            _emit_script()
        else:
            with log_context(**bind_fields):
                _emit_script()
    finally:
        sys.stdout = saved_stdout
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        root.setLevel(saved_level)
        logging.setLogRecordFactory(saved_factory)
    return buffer.getvalue()


# --- 1. console byte-identity (the hard constraint) ------------------------

def test_console_output_is_byte_identical_to_the_pre_l2_rendering():
    # Sentinel values that cannot occur in any of the frozen message texts, so
    # "did a field leak into the console?" is answerable by substring search.
    sentinels = {
        "account": "ZZ_ACCOUNT_ZZ",
        "scenario_id": "ZZ_SCENARIO_ZZ",
        "turn": "ZZ_TURN_ZZ",
        "endpoint": "ZZ_ENDPOINT_ZZ",
        "result_code": "ZZ_RESULT_ZZ",
    }
    before = _render_through_production_console(None)
    after = _render_through_production_console(sentinels)

    # Against the pre-L2 baseline...
    assert after == before
    # ...and against the literal text, so a regression in BOTH passes still fails.
    assert after == EXPECTED_CONSOLE
    for value in sentinels.values():
        assert value not in after


def test_console_handler_shape_is_unchanged_by_the_factory():
    """configure_console_logging still installs exactly one message-only handler."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_factory = logging.getLogRecordFactory()
    root.handlers.clear()
    try:
        logging.setLogRecordFactory(logging.LogRecord)
        configure_console_logging()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.formatter._fmt == "%(message)s"
    finally:
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        root.setLevel(saved_level)
        logging.setLogRecordFactory(saved_factory)


# --- 2. the fields are on the record --------------------------------------

def test_fields_are_present_on_every_record(caplog):
    install_log_fields()
    caplog.set_level(logging.INFO)
    with log_context(**CAREER_FIELDS):
        logging.getLogger("career_bot.engine.runner").info("hello")

    record = caplog.records[-1]
    for name, value in CAREER_FIELDS.items():
        assert getattr(record, name) == value
    # In __dict__, not just as an attribute, so "%(turn)s"-style formatters and a
    # json.dumps(record.__dict__) sink both work.
    assert {name: record.__dict__[name] for name in LOG_FIELDS} == CAREER_FIELDS


def test_unbound_fields_are_present_as_none(caplog):
    install_log_fields()
    caplog.set_level(logging.INFO)
    with log_context(account="lewpie"):
        logging.getLogger("career_bot.engine.runner").info("hello")

    record = caplog.records[-1]
    assert record.account == "lewpie"
    # Uniform schema: the other four exist and are None rather than missing.
    assert [record.turn, record.endpoint, record.scenario_id, record.result_code] == [None] * 4


def test_managed_fields_do_not_collide_with_logrecord_attributes():
    vanilla = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
    assert set(LOG_FIELDS).isdisjoint(vanilla.__dict__)
    assert set(LOG_FIELDS).isdisjoint({"message", "asctime"})


def test_extra_kwarg_for_a_managed_field_is_rejected(caplog):
    """Documented consequence of stamping in the factory: `extra=` must not be
    used for these names. Logger.makeRecord raises on an extra key already in the
    record __dict__, so a future rollout that reached for extra= would fail loudly
    here rather than silently in production."""
    install_log_fields()
    caplog.set_level(logging.INFO)
    with pytest.raises(KeyError):
        logging.getLogger("career_bot.engine.runner").info("x", extra={"turn": 5})

    # The sanctioned one-off override:
    with log_context(**CAREER_FIELDS):
        with log_context(result_code=205):
            logging.getLogger("career_bot.engine.runner").info("x")
    assert caplog.records[-1].result_code == 205


def test_install_is_idempotent_and_uninstall_restores_the_previous_factory():
    saved = logging.getLogRecordFactory()
    try:
        logging.setLogRecordFactory(logging.LogRecord)
        install_log_fields()
        once = logging.getLogRecordFactory()
        install_log_fields()
        assert logging.getLogRecordFactory() is once
        uninstall_log_fields()
        assert logging.getLogRecordFactory() is logging.LogRecord
    finally:
        logging.setLogRecordFactory(saved)


# --- 3. scoping --------------------------------------------------------------

def test_scope_restores_previous_fields_on_exit_and_on_exception():
    install_log_fields()
    assert current_log_fields() == {}
    with log_context(account="lewpie", turn=1):
        set_log_fields(turn=7)
        assert current_log_fields()["turn"] == 7
        with pytest.raises(RuntimeError):
            with log_context(account="yuko"):
                assert current_log_fields()["account"] == "yuko"
                raise RuntimeError("boom")
        assert current_log_fields()["account"] == "lewpie"
        # the inner set_log_fields survived the inner scope's unwind
        assert current_log_fields()["turn"] == 7
    assert current_log_fields() == {}


def test_scope_exit_clears_fields_on_a_reused_thread():
    """The property a bare threading.local()/plain .set() would NOT give us.

    Runner threads are dedicated today, but a pooled worker keeps its context
    between tasks -- so the release has to come from the scope, not from the
    thread dying.
    """
    install_log_fields()
    seen = []

    def task(account):
        with log_context(account=account):
            seen.append(current_log_fields())
        seen.append(current_log_fields())

    worker = threading.Thread(target=lambda: (task("lewpie"), task("yuko")))
    worker.start()
    worker.join()

    assert seen == [{"account": "lewpie"}, {}, {"account": "yuko"}, {}]


# --- 4. threading isolation --------------------------------------------------

def test_context_is_not_inherited_by_a_new_thread():
    """Why CareerRunner binds inside _run (the thread body) and not in start().

    A freshly started threading.Thread begins with an EMPTY context: values set on
    the creating thread do NOT reach it (unlike asyncio.Task, which copies). A bind
    in start() would therefore never reach the runner AND would strand the account
    on the web/CLI thread that called start().
    """
    install_log_fields()
    seen = {}

    def child():
        seen["inherited"] = current_log_fields()
        set_log_fields(account="child")
        seen["own"] = current_log_fields()

    with log_context(account="parent", turn=42):
        worker = threading.Thread(target=child)
        worker.start()
        worker.join()
        # the child inherited nothing...
        assert seen["inherited"] == {}
        assert seen["own"] == {"account": "child"}
        # ...and could not write back into the parent either.
        assert current_log_fields() == {"account": "parent", "turn": 42}


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_two_account_threads_never_see_each_other_fields():
    """Two simulated runner threads + a monitor thread, forced to interleave.

    Every record must carry its OWN thread's account/scenario_id/turn, and the
    monitor thread -- which is not running anybody's career -- must carry none.
    """
    install_log_fields()
    logger = logging.getLogger("test_log_context.concurrency")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    collector = _Collector()
    logger.addHandler(collector)

    turns = list(range(1, 26))
    accounts = {"lewpie": 4, "yuko": 2}
    # 2 careers + the monitor, stepping in lockstep so every log call from one
    # thread lands between two log calls of the others.
    barrier = threading.Barrier(len(accounts) + 1)

    def career(account, scenario_id):
        with log_context(account=account, scenario_id=scenario_id):
            for turn in turns:
                set_log_fields(turn=turn, endpoint=f"{account}/ep{turn}")
                barrier.wait()
                logger.info(f"{account}|{scenario_id}|{turn}")

    def monitor():
        for _ in turns:
            barrier.wait()
            logger.info("monitor")

    threads = [threading.Thread(target=career, args=item) for item in accounts.items()]
    threads.append(threading.Thread(target=monitor))
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        logger.removeHandler(collector)

    assert len(collector.records) == len(turns) * (len(accounts) + 1)
    monitor_records = 0
    for record in collector.records:
        if record.getMessage() == "monitor":
            monitor_records += 1
            # the monitor thread never bound anything -> no other career's fields
            assert [getattr(record, name) for name in LOG_FIELDS] == [None] * len(LOG_FIELDS)
            continue
        account, scenario_id, turn = record.getMessage().split("|")
        assert record.account == account
        assert record.scenario_id == accounts[account]
        assert record.scenario_id == int(scenario_id)
        assert record.turn == int(turn)
        assert record.endpoint == f"{account}/ep{turn}"
    assert monitor_records == len(turns)
