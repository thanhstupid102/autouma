import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from backend.app.routers.careers.services import career_run
from backend.app.routers.careers.services.career_run import (
    MAX_RESUME_ATTEMPTS,
    _BREAK,
    _CareerLoop,
    _NEXT_CYCLE,
    _STOP,
)
from core.settings import (
    DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS,
    Settings,
    career_circuit_retry_wait_seconds,
)
from uma_api import game_service


class RecordingRunner:
    def __init__(self):
        self.status = {"running": False, "status": "error", "last_error": "boom"}
        self.start_calls = []
        self.resume_attempts = []
        self.waits = []
        self.stages = []

    def set_loop_info(self, current, target):
        self.loop_info = (current, target)

    def set_resume_attempt(self, attempt, limit):
        self.resume_attempts.append((attempt, limit))

    def set_retry_wait(self, attempt, limit, wait_seconds):
        self.waits.append((attempt, limit, wait_seconds))

    def set_retry_stage(self, action, detail):
        self.stages.append((action, detail))

    def start(self, *args, **kwargs):
        self.start_calls.append((args, kwargs))

    def snapshot(self):
        return dict(self.status)

    def stop(self):
        pass


class CircuitThenFinishedRunner(RecordingRunner):
    def snapshot(self):
        if len(self.start_calls) == 1:
            return {
                "running": False,
                "status": "stopped",
                "last_error": "auto-backoff",
                "circuit_tripped": True,
            }
        return {"running": False, "status": "finished", "finished": True}


def make_loop(name="resume-ladder", runner=None, run_count=1):
    runner = runner or RecordingRunner()
    client = SimpleNamespace(login=lambda: None, circuit_tripped=True)
    session = SimpleNamespace(
        runner=runner,
        loop_stop=False,
        loop_paused=False,
        client=client,
        name=name,
        account={},
        user_info_cache={},
    )
    service = SimpleNamespace(session=session)
    service._resume_active_career = lambda _req, _preset: {"data": {"career": name}}
    req = SimpleNamespace(
        max_steps=1,
        run_count=run_count,
        burn_clocks=False,
        spark_reroll=False,
    )
    return _CareerLoop(service, req, {}, {"data": {"career": "initial"}})


def test_circuit_abort_enters_resume_ladder_instead_of_stopping(monkeypatch):
    runner = CircuitThenFinishedRunner()
    loop = make_loop(runner=runner)
    events = []

    monkeypatch.setattr(
        loop,
        "_idle",
        lambda seconds: events.append(("wait", seconds)) or False,
    )
    monkeypatch.setattr(
        loop,
        "_rerun_session",
        lambda: events.append(("rerun", None)) or True,
    )

    def reset(session):
        events.append(("reset", None))
        session.client.circuit_tripped = False

    def resume(_req, _preset):
        events.append(("resume", None))
        return {"data": {"career": "resumed"}}

    monkeypatch.setattr(game_service, "reset_circuit", reset)
    loop.service._resume_active_career = resume

    loop.run()

    assert len(runner.start_calls) == 2
    assert runner.start_calls[1][0][2] == {"data": {"career": "resumed"}}
    assert events == [
        ("wait", DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS[0]),
        ("rerun", None),
        ("reset", None),
        ("resume", None),
    ]
    assert runner.resume_attempts == [(0, 3), (1, 3)]
    assert loop.session.loop_stop is False


def test_circuit_retry_waits_escalate_and_stop_after_three(monkeypatch, caplog):
    loop = make_loop()
    waits = []
    reruns = []
    resets = []
    resumes = []
    status = {
        "status": "stopped",
        "last_error": "auto-backoff",
        "circuit_tripped": True,
    }

    monkeypatch.setattr(loop, "_idle", lambda seconds: waits.append(seconds) or False)
    monkeypatch.setattr(loop, "_rerun_session", lambda: reruns.append(True) or True)

    def reset(session):
        resets.append(session.name)
        session.client.circuit_tripped = False

    def resume(_req, _preset):
        resumes.append(True)
        return {"data": {"career": "resumed"}}

    monkeypatch.setattr(game_service, "reset_circuit", reset)
    loop.service._resume_active_career = resume
    caplog.set_level(logging.WARNING, logger=career_run.__name__)

    for expected_attempt in range(1, MAX_RESUME_ATTEMPTS + 1):
        loop.session.client.circuit_tripped = True
        assert loop._handle_runner_error(status) == _NEXT_CYCLE
        assert loop.resume_attempts == expected_attempt

    assert loop._handle_runner_error(status) == _BREAK
    assert waits == list(DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS)
    assert len(reruns) == len(resets) == len(resumes) == MAX_RESUME_ATTEMPTS
    assert "career still stuck after 3 resume attempts" in caplog.text


def test_stop_during_retry_wait_does_not_rerun_or_resume(monkeypatch):
    loop = make_loop()
    status = {
        "status": "stopped",
        "last_error": "auto-backoff",
        "circuit_tripped": True,
    }

    def stop_during_wait(_seconds):
        loop.session.loop_stop = True
        return True

    monkeypatch.setattr(loop, "_idle", stop_during_wait)
    monkeypatch.setattr(
        loop,
        "_rerun_session",
        lambda: pytest.fail("session must not re-run after Stop"),
    )
    monkeypatch.setattr(
        game_service,
        "reset_circuit",
        lambda _session: pytest.fail("circuit must not reset after Stop"),
    )
    loop.service._resume_active_career = lambda *_args: pytest.fail(
        "career must not resume after Stop"
    )

    assert loop._handle_runner_error(status) == _STOP
    assert loop.resume_attempts == 0
    assert loop.runner.stages[-1][0] == "retry-cancelled"


def test_failed_session_rerun_never_resets_or_resumes(monkeypatch):
    loop = make_loop()
    status = {"status": "error", "last_error": "runner failed"}
    monkeypatch.setattr(loop, "_rerun_session", lambda: False)
    monkeypatch.setattr(
        game_service,
        "reset_circuit",
        lambda _session: pytest.fail("circuit reset must follow a successful re-run"),
    )
    loop.service._resume_active_career = lambda *_args: pytest.fail(
        "resume must not run against a dead session"
    )

    assert loop._handle_runner_error(status) == _BREAK
    assert loop.resume_attempts == 0
    assert loop.runner.stages[-1][0] == "retry-failed"


def test_normal_finish_resets_resume_budget_for_next_career():
    loop = make_loop(run_count=2)
    loop.resume_attempts = MAX_RESUME_ATTEMPTS

    loop._record_finished_career()

    assert loop.resume_attempts == 0
    assert loop.runs_done == 1


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (
            {
                "status": "error",
                "last_error": "Scenario 3 is unsupported",
                "error_type": "UnsupportedScenarioError",
            },
            "unsupported scenario",
        ),
        (
            {
                "status": "error",
                "last_error": "API error 102; Sign in again",
                "error_type": "AuthInvalidatedError",
                "error_result_code": 102,
            },
            "authentication is invalid",
        ),
        (
            {
                "status": "error",
                "last_error": (
                    "Spark Reroll failed: Account auth is invalid "
                    "(re-registered). Sign in again from the web UI"
                ),
                "error_type": "RunFatalError",
            },
            "authentication is invalid",
        ),
        (
            {
                "status": "error",
                "last_error": "race_out rejected by the server on turn 55",
                "error_type": "RunFatalError",
            },
            "race_out 201 lock",
        ),
        (
            {
                "status": "error",
                "last_error": "restart cap exhausted on turn 42",
                "error_type": "RunFatalError",
            },
            "fatal run failure",
        ),
        (
            {
                "status": "error",
                "last_error": "Spark Reroll requires manual resolution",
                "error_type": "RunFatalError",
            },
            "fatal run failure",
        ),
    ],
)
def test_permanent_failure_classes_are_not_retried(
    monkeypatch, caplog, status, reason,
):
    loop = make_loop()
    monkeypatch.setattr(
        loop,
        "_rerun_session",
        lambda: pytest.fail("permanent failure must not re-run the session"),
    )
    caplog.set_level(logging.WARNING, logger=career_run.__name__)

    assert loop._handle_runner_error(status) == _BREAK
    assert reason in caplog.text
    assert loop.resume_attempts == 0
    assert loop.runner.stages[-1][0] == "retry-disabled"


def test_concurrent_accounts_keep_independent_attempts_and_waits(monkeypatch):
    loop_a = make_loop(name="account-a")
    loop_b = make_loop(name="account-b")
    loop_b.resume_attempts = 1
    barrier = threading.Barrier(2)
    waits = {}
    status = {
        "status": "stopped",
        "last_error": "auto-backoff",
        "circuit_tripped": True,
    }

    def install(loop):
        def idle(seconds):
            waits[loop.session.name] = seconds
            barrier.wait(timeout=2)
            return False

        loop._idle = idle
        loop._rerun_session = lambda: True
        loop.service._resume_active_career = (
            lambda _req, _preset: {"data": {"career": loop.session.name}}
        )

    install(loop_a)
    install(loop_b)

    def reset(session):
        session.client.circuit_tripped = False

    monkeypatch.setattr(game_service, "reset_circuit", reset)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda loop: loop._handle_runner_error(status), [loop_a, loop_b]))

    assert outcomes == [_NEXT_CYCLE, _NEXT_CYCLE]
    assert loop_a.resume_attempts == 1
    assert loop_b.resume_attempts == 2
    assert waits == {
        "account-a": Settings.UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS[0],
        "account-b": Settings.UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS[1],
    }


@pytest.mark.parametrize("raw", ["broken", "5,10", "5,0,30", "5,,30"])
def test_malformed_retry_wait_setting_falls_back(monkeypatch, caplog, raw):
    monkeypatch.setenv("UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS", raw)
    caplog.set_level(logging.WARNING, logger="settings")

    assert (
        career_circuit_retry_wait_seconds()
        == DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS
    )
    assert "Invalid UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS value" in caplog.text


def test_retry_wait_setting_accepts_three_positive_values(monkeypatch):
    monkeypatch.setenv("UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS", "60, 120,300")

    assert career_circuit_retry_wait_seconds() == (60, 120, 300)
