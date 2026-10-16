import gzip
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from career_bot.engine.report import add_api_call, new_report, set_error
from career_bot.engine.runner import CareerRunner
import core.settings as settings_module
from core.settings import (
    DEFAULT_CAREER_API_TRACE_ENABLED,
    DEFAULT_CAREER_API_TRACE_MAX_BYTES,
    DEFAULT_CAREER_API_TRACE_MIN_FREE_BYTES,
    DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES,
    Settings,
)
from uma_api.trace import TraceLog, iter_trace_records
from uma_api.client import UmaClient
from uma_api.log_context import log_context
import uma_api.trace as trace_module


def test_trace_log_writes_full_request_and_response_as_gzip(tmp_path):
    trace = TraceLog(tmp_path, flush_interval=2)
    path = trace.initialize()
    request = {"payload": {"password": "local-secret", "blob": "r" * 1024}}
    response = {"data_headers": {"result_code": 1}, "data": {"blob": "s" * 2048}}

    trace.write("REQ", "single_mode/start", request, "request-1")
    trace.write("RES", "single_mode/start", response, "request-1")
    trace.close()

    assert path.name.endswith("_payloads.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle]
    assert [record["direction"] for record in records] == ["REQ", "RES"]
    assert records[0]["data"] == request
    assert records[1]["data"] == response


def test_career_production_funnel_records_both_directions_full_fidelity(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(CareerRunner, "_run", lambda *args: None)
    monkeypatch.setattr(Settings, "UMA_CAREER_API_TRACE", True)
    client = UmaClient.__new__(UmaClient)
    client.on_api_log = None
    client._trace_log = None
    client.trace_file = None
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.start(client, {"name": "trace-test"}, initial_result={})
    runner.thread.join(timeout=10)
    runner._prime_run(client, {})
    request = {"payload": {"password": "local-secret", "blob": "q" * 64}}
    response = {
        "data_headers": {"result_code": 500},
        "data": {"blob": "z" * (32 * 1024)},
    }

    with log_context():
        client.api_log("REQ", "single_mode/exec_command", request, "call-1")
        client.api_log("RES", "single_mode/exec_command", response, "call-1")
    path = runner._close_career_trace()

    records = list(iter_trace_records(path))
    assert [record["direction"] for record in records] == ["REQ", "RES"]
    assert records[0]["data"] == request
    assert records[1]["data"] == response
    report_calls = runner.report["turns"][0]["api_calls"]
    assert report_calls[1]["data"]["_omitted"] == "api_body_exceeds_limit"


def test_trace_reuses_report_body_serialization(tmp_path):
    calls = 0

    class CountedValue:
        def __str__(self):
            nonlocal calls
            calls += 1
            return "serialized-once"

    body = {"value": CountedValue()}
    report = new_report()
    body_bytes = add_api_call(
        report,
        {"endpoint": "test/reuse", "direction": "REQ", "data": body},
    )
    trace = TraceLog(tmp_path, flush_interval=1)
    path = trace.initialize()
    trace.write("REQ", "test/reuse", body, data_bytes=body_bytes)
    trace.close()

    assert calls == 1
    assert list(iter_trace_records(path))[0]["data"] == {
        "value": "serialized-once",
    }


def test_trace_uses_add_api_call_bytes_after_the_body_mutates(tmp_path):
    body = {"nested": {"value": "before"}}
    report = new_report()

    body_bytes = add_api_call(
        report,
        {"endpoint": "test/snapshot", "direction": "RES", "data": body},
    )
    expected_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body["nested"]["value"] = "after"

    trace = TraceLog(tmp_path, flush_interval=1)
    path = trace.initialize()
    trace.write("RES", "test/snapshot", body, data_bytes=body_bytes)
    trace.close()

    assert body_bytes == expected_bytes
    assert report["turns"][0]["api_calls"][0]["data"] == {
        "nested": {"value": "before"},
    }
    assert list(iter_trace_records(path))[0]["data"] == {"nested": {"value": "before"}}


def test_failed_body_measurement_uses_trace_sentinel_without_retry(tmp_path):
    calls = 0

    class FailingValue:
        def __str__(self):
            nonlocal calls
            calls += 1
            raise ValueError("cannot serialize")

    body = {"value": FailingValue()}
    report = new_report()
    body_bytes = add_api_call(
        report,
        {"endpoint": "test/failure", "direction": "REQ", "data": body},
    )
    trace = TraceLog(tmp_path, flush_interval=1)
    path = trace.initialize()
    trace.write("REQ", "test/failure", body, data_bytes=body_bytes)
    trace.close()

    assert calls == 1
    assert list(iter_trace_records(path))[0]["data"] == {
        "_omitted": "api_body_measurement_failed",
        "endpoint": "test/failure",
        "direction": "REQ",
        "body_type": "dict",
        "measurement_error": "ValueError",
        "configured_limit_bytes": Settings.UMA_MAX_CAREER_API_BODY_BYTES,
    }


def test_parallel_accounts_use_separate_files_and_compressors(tmp_path):
    ready = threading.Barrier(2)
    paths = {}

    def write_account(account):
        trace = TraceLog(tmp_path, flush_interval=1)
        paths[account] = trace.initialize()
        ready.wait(timeout=10)
        trace.write("REQ", "test/account", {"account": account})
        trace.close()

    threads = [
        threading.Thread(target=write_account, args=(account,))
        for account in ("account-a", "account-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert paths["account-a"] != paths["account-b"]
    assert list(iter_trace_records(paths["account-a"]))[0]["data"] == {
        "account": "account-a",
    }
    assert list(iter_trace_records(paths["account-b"]))[0]["data"] == {
        "account": "account-b",
    }


def test_trace_checkpoints_do_not_fsync_periodically(tmp_path, monkeypatch):
    fsync_calls = []
    monkeypatch.setattr(trace_module.os, "fsync", lambda fd: fsync_calls.append(fd))
    trace = TraceLog(tmp_path, flush_interval=20)
    trace.initialize()

    for index in range(39):
        trace.write("RES", "test/fsync", {"index": index})

    assert fsync_calls == []
    trace.close()

    assert fsync_calls == []


def test_trace_free_space_floor_stops_writes_and_warns_once(
    tmp_path, monkeypatch, caplog,
):
    free_bytes = iter([50])
    disk_usage = SimpleNamespace(
        disk_usage=lambda _path: SimpleNamespace(free=next(free_bytes)),
    )
    monkeypatch.setattr(trace_module, "shutil", disk_usage, raising=False)
    monkeypatch.setattr(
        Settings,
        "UMA_CAREER_API_TRACE_MAX_BYTES",
        1024 * 1024,
        raising=False,
    )
    monkeypatch.setattr(
        Settings,
        "UMA_CAREER_API_TRACE_MIN_FREE_BYTES",
        100,
        raising=False,
    )
    caplog.set_level(logging.WARNING, logger="uma_api.trace")
    trace = TraceLog(tmp_path, flush_interval=20)
    path = trace.initialize()

    trace.write("RES", "test/free-space", {"index": 1})
    trace.write("RES", "test/free-space", {"index": 2})
    trace.close()

    assert list(iter_trace_records(path)) == []
    assert caplog.text.count("trace circuit breaker stopped writes") == 1


def test_trace_prunes_to_configured_file_count(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "UMA_MAX_TRACE_LOGS", 2)

    for index in range(3):
        trace = TraceLog(tmp_path, flush_interval=1)
        trace.initialize()
        trace.write("RES", "test/prune", {"index": index})
        trace.close()

    files = sorted((tmp_path / "api_payloads").glob("*_payloads.jsonl.gz"))
    assert len(files) == 2


def test_trace_pruning_uses_mtime_not_filename(tmp_path):
    log_dir = tmp_path / "api_payloads"
    log_dir.mkdir()
    older = log_dir / "20260730_120000_aaaaaa_payloads.jsonl.gz"
    newer = log_dir / "20260730_050000_bbbbbb_payloads.jsonl.gz"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    trace_module._prune_trace_files(log_dir, keep=1)

    assert not older.exists()
    assert newer.exists()


def test_career_trace_replaces_then_resumes_existing_debug_writer(tmp_path):
    previous = TraceLog(tmp_path / "trace_logs", flush_interval=7)
    previous.initialize()
    client = SimpleNamespace(_trace_log=previous, trace_file=previous.trace_file)
    runner = CareerRunner(tmp_path, state_root=tmp_path)

    career_path = runner._begin_career_trace(client)

    assert previous._gzip_file is not None
    assert client._trace_log is runner._career_trace_log
    assert client.trace_file == career_path

    runner._close_career_trace()

    assert client._trace_log is previous
    assert client.trace_file == previous.trace_file
    assert client._trace_log.flush_interval == 7
    previous.close()


def test_running_stays_true_until_teardown_outputs_finish(tmp_path, monkeypatch):
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.status.update(running=True, finished=True)
    runner._live_monitor = object()
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def slow_stop(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr("career_bot.engine.runner.notify.stop_live_monitor", slow_stop)
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.notify.send_career_summary",
        lambda *args, **kwargs: True,
    )

    def finalize():
        try:
            runner._finalize_run()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=finalize)
    worker.start()
    try:
        assert entered.wait(timeout=10)
        assert runner.snapshot()["running"] is True
    finally:
        release.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert errors == []
    assert runner.snapshot()["running"] is False


def test_closed_trace_can_remain_reserved_until_notification_finishes(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(Settings, "UMA_MAX_TRACE_LOGS", 1)
    first = TraceLog(tmp_path, flush_interval=1)
    first_path = first.initialize()
    first.write("RES", "test/first", {"index": 1})
    second = TraceLog(tmp_path, flush_interval=1)
    second_path = second.initialize()
    second.write("RES", "test/second", {"index": 2})

    first.close(reserve=True)

    assert first_path.exists()
    assert second_path.exists()
    trace_module.release_trace_file(first_path)
    assert not first_path.exists()
    assert second_path.exists()
    second.close()


def test_finish_report_failure_still_closes_trace_and_restores_writer(
    tmp_path, monkeypatch,
):
    previous = TraceLog(tmp_path / "debug", flush_interval=7)
    previous.initialize()
    client = SimpleNamespace(_trace_log=previous, trace_file=previous.trace_file)
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.status.update(running=True, finished=True)
    career_path = runner._begin_career_trace(client)

    monkeypatch.setattr(
        "career_bot.engine.runner.finish_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad report row")),
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.notify.send_career_summary",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(ValueError, match="bad report row"):
        runner._finalize_run()

    assert runner._career_trace_log is None
    assert client._trace_log is previous
    assert previous._gzip_file is not None
    assert runner.snapshot()["running"] is False
    assert list(iter_trace_records(career_path)) == []
    previous.close()


@pytest.mark.parametrize(
    ("exit_path", "expected_status"),
    [
        ("normal", "finished"),
        ("stop", "stopped"),
        ("pause", "paused"),
        ("terminal_error", "error"),
    ],
)
def test_teardown_closes_and_restores_for_runner_exit_paths(
    tmp_path, monkeypatch, exit_path, expected_status,
):
    previous = TraceLog(tmp_path / "debug", flush_interval=7)
    previous.initialize()
    client = SimpleNamespace(_trace_log=previous, trace_file=previous.trace_file)
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.status.update(running=True, finished=exit_path == "normal")
    runner._live_monitor = object()
    career_path = runner._begin_career_trace(client)
    runner._career_trace_log.write("REQ", "test/exit", {"exit": exit_path})
    if exit_path == "stop":
        runner.stop_requested = True
    elif exit_path == "pause":
        runner.pause_exit_requested = True
    elif exit_path == "terminal_error":
        error = RuntimeError("turn loop failed")
        runner.status["last_error"] = str(error)
        set_error(runner.report, error)

    monkeypatch.setattr(
        "career_bot.engine.runner.notify.stop_live_monitor",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.notify.send_career_summary",
        lambda *args, **kwargs: True,
    )

    runner._finalize_run()

    assert runner.snapshot()["status"] == expected_status
    assert runner.snapshot()["running"] is False
    assert runner._live_monitor is None
    assert runner._career_trace_log is None
    assert client._trace_log is previous
    assert previous._gzip_file is not None
    assert list(iter_trace_records(career_path))[0]["data"] == {
        "exit": exit_path,
    }
    previous.close()


def test_notification_failure_releases_reserved_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "UMA_MAX_TRACE_LOGS", 1)
    client = SimpleNamespace(_trace_log=None, trace_file=None)
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.status.update(running=True, finished=False)
    set_error(runner.report, RuntimeError("career failed"))
    career_path = runner._begin_career_trace(client)
    runner._career_trace_log.write("REQ", "test/failure", {"index": 1})
    competing = TraceLog(tmp_path / "trace_logs", flush_interval=1)
    competing_path = competing.initialize()
    competing.write("REQ", "test/competing", {"index": 2})

    monkeypatch.setattr(
        "career_bot.engine.runner.notify.stop_live_monitor",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.notify.send_career_summary",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("discord down")),
    )

    runner._finalize_run()

    assert not career_path.exists()
    assert competing_path.exists()
    assert client._trace_log is None
    assert runner.snapshot()["running"] is False
    competing.close()


def test_restoration_exception_still_publishes_completion(tmp_path, monkeypatch):
    client = SimpleNamespace(_trace_log=None, trace_file=None)
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.status.update(running=True, finished=True)
    career_path = runner._begin_career_trace(client)
    runner._career_trace_log.write("REQ", "test/restore", {"index": 1})

    monkeypatch.setattr(
        "career_bot.engine.runner.notify.stop_live_monitor",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: tmp_path / "career.json",
    )
    monkeypatch.setattr(
        "career_bot.engine.runner.notify.send_career_summary",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        runner,
        "_resume_debug_trace",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("restore failed")),
    )

    with pytest.raises(RuntimeError, match="restore failed"):
        runner._finalize_run()

    assert runner.snapshot()["running"] is False
    assert runner._career_trace_log is None
    assert list(iter_trace_records(career_path))[0]["data"] == {"index": 1}


def test_killed_writer_leaves_records_before_last_flush(tmp_path):
    trace_root = tmp_path / "trace"
    ready_path = tmp_path / "ready"
    code = "\n".join([
        "import sys, time",
        "from pathlib import Path",
        "from uma_api.trace import TraceLog",
        "trace = TraceLog(Path(sys.argv[1]), flush_interval=20)",
        "trace.initialize()",
        "for index in range(20):",
        "    trace.write('RES', 'test/crash', {'index': index})",
        "Path(sys.argv[2]).write_text('ready', encoding='ascii')",
        "index = 20",
        "while True:",
        "    trace.write('RES', 'test/crash', {'index': index})",
        "    index += 1",
        "    time.sleep(0.01)",
    ])
    process = subprocess.Popen([
        sys.executable,
        "-c",
        code,
        str(trace_root),
        str(ready_path),
    ], cwd=Path(__file__).parents[1])
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_path.exists()
        process.kill()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    path = next((trace_root / "api_payloads").glob("*.jsonl.gz"))
    records = list(iter_trace_records(path))
    assert len(records) >= 20
    assert [record["data"]["index"] for record in records[:20]] == list(range(20))


def test_new_settings_fall_back_on_malformed_values(monkeypatch, caplog):
    try:
        with monkeypatch.context() as environment:
            environment.setenv("UMA_CAREER_API_TRACE", "definitely")
            environment.setenv("UMA_CAREER_API_TRACE_MAX_BYTES", "broken")
            environment.setenv("UMA_CAREER_API_TRACE_MIN_FREE_BYTES", "broken")
            environment.setenv("UMA_DISCORD_CAREER_TRACE_MAX_BYTES", "broken")
            caplog.set_level(logging.WARNING, logger="settings")
            reloaded = importlib.reload(settings_module)
            assert reloaded.Settings.UMA_CAREER_API_TRACE is DEFAULT_CAREER_API_TRACE_ENABLED
            assert (
                reloaded.Settings.UMA_DISCORD_CAREER_TRACE_MAX_BYTES
                == DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES
            )
            assert (
                reloaded.Settings.UMA_CAREER_API_TRACE_MAX_BYTES
                == DEFAULT_CAREER_API_TRACE_MAX_BYTES
            )
            assert (
                reloaded.Settings.UMA_CAREER_API_TRACE_MIN_FREE_BYTES
                == DEFAULT_CAREER_API_TRACE_MIN_FREE_BYTES
            )
        assert "Invalid UMA_CAREER_API_TRACE value" in caplog.text
        assert "Invalid UMA_CAREER_API_TRACE_MAX_BYTES value" in caplog.text
        assert "Invalid UMA_CAREER_API_TRACE_MIN_FREE_BYTES value" in caplog.text
        assert "Invalid UMA_DISCORD_CAREER_TRACE_MAX_BYTES value" in caplog.text
    finally:
        importlib.reload(settings_module)

    assert Settings.UMA_CAREER_API_TRACE is DEFAULT_CAREER_API_TRACE_ENABLED


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_trace_file_permissions_are_private(tmp_path):
    import stat

    trace = TraceLog(tmp_path)
    path = trace.initialize()
    trace.close()

    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
