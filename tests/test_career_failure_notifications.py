import json
from types import SimpleNamespace

import pytest

from backend.app.routers.careers.services.career_run import _CareerLoop
from career_bot.engine.report import new_report
from career_bot.engine.runner import CareerRunner
from integrations.discord import notify
from uma_api.trace import TraceLog


AUTO_BACKOFF_REASON = (
    "Auto-backoff: too many server errors in a short time "
    "(server likely throttling). Stopped to avoid hammering -- "
    "wait a while before running again."
)


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return self.status


def _configure_webhook(state_root):
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "discord.json").write_text(
        json.dumps({
            "webhook_url": "https://discord.test/hook",
            "error_mention": {"kind": "user", "id": "12345678901234567"},
        }),
        encoding="utf-8",
    )


def _capture_requests(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout=10):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    return requests


def _multipart_payload(request):
    content_type = request.get_header("Content-type")
    boundary = content_type.split("boundary=", 1)[1].encode("ascii")
    for part in request.data.split(b"--" + boundary):
        if b' name="payload_json"' in part and b"\r\n\r\n" in part:
            return json.loads(part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
    raise AssertionError("multipart request did not contain payload_json")


def _trace(tmp_path):
    trace = TraceLog(tmp_path / "trace_logs", flush_interval=1)
    path = trace.initialize()
    trace.write("REQ", "single_mode_free/continue", {"current_turn": 72})
    trace.close()
    return path


def _circuit_runner(tmp_path, state_root, trace_path):
    runner = CareerRunner(tmp_path, state_root=state_root)
    runner.report = new_report()
    runner.status.update(
        running=True,
        circuit_tripped=True,
        last_error=AUTO_BACKOFF_REASON,
    )
    runner.stop_requested = True
    runner._career_trace_path = trace_path
    return runner


def test_auto_backoff_pings_uploads_and_explains_local_abort(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = CareerRunner(tmp_path, state_root=state_root)
    runner.report = new_report()
    runner.status.update(running=True)
    runner._career_trace_path = _trace(tmp_path)
    assert runner._run_break_requested(
        SimpleNamespace(circuit_tripped=True),
    ) is True
    # This must never be embedded, even though it remains in the private report.
    runner.report["error"] = {"message": "server supplied secret detail"}

    runner._finalize_run()

    assert runner.snapshot()["status"] == "stopped"
    assert runner.report["status"] == "stopped"
    assert len(requests) == 1
    payload = _multipart_payload(requests[0])
    assert payload["content"].startswith("<@12345678901234567> Account")
    assert payload["allowed_mentions"] == {
        "parse": [], "users": ["12345678901234567"],
    }
    assert payload["embeds"][0]["title"].endswith("Automatically Aborted")
    fields = {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}
    assert fields["Abort Reason"] == AUTO_BACKOFF_REASON
    assert fields["📋 Status"] == "\U0001f534 Automatic abort"
    assert b' name="files[0]"' in requests[0].data
    assert b"server supplied secret detail" not in json.dumps(payload).encode("utf-8")
    assert not any(row["action"] == "stop" for row in runner.status["log"])


@pytest.mark.parametrize("status", ["stopped", "paused", "finished"])
def test_non_failure_terminal_outcomes_do_not_ping_or_upload(
        tmp_path, monkeypatch, status):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = CareerRunner(tmp_path, state_root=state_root)
    runner.report = new_report()
    runner.status.update(running=True, finished=status == "finished")
    runner._career_trace_path = _trace(tmp_path)
    if status == "stopped":
        runner.stop_requested = True
    elif status == "paused":
        runner.pause_exit_requested = True

    runner._finalize_run()

    assert runner.snapshot()["status"] == status
    assert len(requests) == 1
    assert requests[0].get_header("Content-type") == "application/json"
    payload = json.loads(requests[0].data)
    assert "content" not in payload
    assert "allowed_mentions" not in payload
    assert b"files[0]" not in requests[0].data


def test_exception_failure_still_pings_and_uploads(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = CareerRunner(tmp_path, state_root=state_root)
    runner.report = new_report()
    runner.status.update(running=True)
    runner.set_resume_attempt(2, 3)
    runner._career_trace_path = _trace(tmp_path)
    try:
        raise RuntimeError("turn loop failed")
    except RuntimeError as error:
        runner._handle_run_crash(error)

    runner._finalize_run()

    assert runner.snapshot()["status"] == "error"
    payload = _multipart_payload(requests[0])
    assert payload["content"].startswith("<@12345678901234567> Account")
    assert "Resume attempt 2/3" in payload["content"]
    fields = {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}
    assert fields["Resume Attempt"] == "2/3"
    assert b' name="files[0]"' in requests[0].data


def test_auto_backoff_trace_upload_is_attempted_once_per_runner(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    runner = _circuit_runner(tmp_path, state_root, _trace(tmp_path))
    runner.report["status"] = "stopped"
    uploads = []
    monkeypatch.setattr(notify, "stop_live_monitor", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        notify,
        "send_career_summary",
        lambda *args, **kwargs: uploads.append(kwargs.get("attachment_path")),
    )

    runner._emit_run_outputs()
    runner._emit_run_outputs()

    assert uploads == [runner._career_trace_path, None]


def test_auto_backoff_live_embed_is_not_an_operator_stop():
    embed = notify._build_live_embed({
        "status": "stopped",
        "circuit_tripped": True,
        "last_error": AUTO_BACKOFF_REASON,
    })
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert fields["Status"] == "\U0001f534 Automatically Aborted"
    assert fields["Abort Reason"] == AUTO_BACKOFF_REASON


def test_resume_attempt_notifications_include_attempt_and_final_marker():
    attempt_embed = notify._build_embed({
        "status": "error",
        "resume_attempt": 2,
        "resume_attempt_limit": 3,
    })
    attempt_fields = {
        field["name"]: field["value"] for field in attempt_embed["fields"]
    }
    assert attempt_fields["Resume Attempt"] == "2/3"

    final_embed = notify._build_embed({
        "status": "stopped",
        "circuit_tripped": True,
        "resume_attempt": 3,
        "resume_attempt_limit": 3,
    })
    final_fields = {
        field["name"]: field["value"] for field in final_embed["fields"]
    }
    assert final_fields["Resume Attempt"].startswith("3/3 - FINAL")


def test_nonretryable_notification_is_marked_final():
    embed = notify._build_embed({
        "status": "error",
        "error": {
            "type": "AuthInvalidatedError",
            "message": "API error 102; Sign in again",
        },
    })
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert fields["Resume Attempt"].startswith("FINAL;")
    assert "authentication is invalid" in fields["Resume Attempt"]


def test_breaker_notification_finishes_before_resume_ladder(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = _circuit_runner(tmp_path, state_root, _trace(tmp_path))
    session = SimpleNamespace(
        runner=runner,
        loop_stop=False,
        loop_paused=False,
        client=SimpleNamespace(login=lambda: None, circuit_tripped=True),
        name="slot-a",
    )
    service = SimpleNamespace(session=session)
    service._resume_active_career = lambda _req, _preset: {"data": {"career": "active"}}
    loop = _CareerLoop(
        service,
        SimpleNamespace(max_steps=1, run_count=2),
        {},
        {},
    )
    # The runner owns the terminal notification. The loop cannot enter recovery
    # until finalize has completed and published running=False.
    monkeypatch.setattr(loop, "_launch_runner", runner._finalize_run)
    monkeypatch.setattr(loop, "_idle", lambda _seconds: False)
    monkeypatch.setattr(loop, "_rerun_session", lambda: True)

    def reset_circuit(resume_session):
        resume_session.client.circuit_tripped = False

    monkeypatch.setattr("uma_api.game_service.reset_circuit", reset_circuit)

    outcome = loop._run_cycle()

    assert outcome == "next-cycle"
    assert loop.resume_attempts == 1
    assert session.loop_stop is False
    assert len(requests) == 1
