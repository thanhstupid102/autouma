from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading

import core.operational_time as operational_time
from backend.app.domain import master_data_preflight
from career_bot.engine import report
from career_bot.engine import reporting
from integrations.discord import notify
from core.runtime_paths import MASTER_JSON_FILENAMES, state_paths_for
from scripts import scrape_gametora_effects
from uma_api import trace
from uma_data import legacy_json, mdb_config


_INSTANT = datetime(2026, 7, 30, 18, 23, 45, tzinfo=timezone.utc)


def _host_datetime(offset_hours):
    host_zone = timezone(timedelta(hours=offset_hours))

    class HostDateTime:
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return _INSTANT.astimezone(tz)
            return _INSTANT.astimezone(host_zone).replace(tzinfo=None)

    return HostDateTime


def _operational_artifacts(tmp_path, monkeypatch, offset_hours):
    monkeypatch.setattr(
        operational_time, "datetime", _host_datetime(offset_hours),
    )
    monkeypatch.setattr(
        trace.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="abcdef123456"),
    )

    trace_log = trace.TraceLog(tmp_path / f"trace-{offset_hours}")
    trace_log.initialize()
    live_host = SimpleNamespace(status={}, lock=threading.Lock())
    reporting.RunnerReportMixin._log_locked(
        live_host, "train", 12, "deterministic",
    )

    return {
        "report_timestamp": report.now_iso(),
        "report_filename": report.begin_report_path(
            tmp_path / f"reports-{offset_hours}", "account",
        ).name,
        "trace_filename": trace_log.trace_file.name,
        "discord_timestamp": notify._build_embed({
            "status": "finished",
        })["timestamp"],
        "live_clock": live_host.status["log"][0]["time"],
        "crash_stamp": operational_time.utc_log_stamp(),
    }


def test_operational_timestamps_are_identical_across_host_timezones(
    tmp_path, monkeypatch,
):
    utc_minus_seven = _operational_artifacts(
        tmp_path, monkeypatch, -7,
    )
    utc_plus_seven = _operational_artifacts(
        tmp_path, monkeypatch, 7,
    )

    assert utc_minus_seven == utc_plus_seven == {
        "report_timestamp": "2026-07-30T18:23:45+00:00",
        "report_filename": "career_log_account_20260730_182345.json",
        "trace_filename": "20260730_182345_abcdef_payloads.jsonl.gz",
        "discord_timestamp": "2026-07-30T18:23:45+00:00",
        "live_clock": "18:23:45",
        "crash_stamp": "2026-07-30 18:23:45 UTC",
    }


def _translated_write_text(line_ending):
    def write_text(path, data, encoding=None, errors=None, newline=None):
        payload = str(data).replace("\r\n", "\n").replace("\n", line_ending)
        return Path(path).write_bytes(payload.encode(encoding or "utf-8"))

    return write_text


def test_generated_outputs_have_identical_hashes_under_host_newline_modes(
    tmp_path, monkeypatch,
):
    data = {"z": "line one\nline two", "a": "Uma"}
    hashes = {}
    for platform_name, line_ending in (("windows", "\r\n"), ("posix", "\n")):
        monkeypatch.setattr(
            Path, "write_text", _translated_write_text(line_ending),
        )
        master_path = tmp_path / platform_name / "master.json"
        scraper_path = tmp_path / platform_name / "scraper.json"
        master_path.parent.mkdir(parents=True, exist_ok=True)
        mdb_config.write_json(master_path, data)
        scraper_path.parent.mkdir(parents=True, exist_ok=True)
        scrape_gametora_effects._write_output(scraper_path, data)
        hashes[platform_name] = (
            hashlib.sha256(master_path.read_bytes()).hexdigest(),
            hashlib.sha256(scraper_path.read_bytes()).hexdigest(),
        )
        assert b"\r\n" not in master_path.read_bytes()
        assert b"\r\n" not in scraper_path.read_bytes()

    assert hashes["windows"] == hashes["posix"]


def _write_generated_set(source_root, state_root, database_path, mtimes):
    output_dir = state_paths_for(source_root, state_root).master_json_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, filename in enumerate(MASTER_JSON_FILENAMES):
        path = output_dir / filename
        path.write_bytes(b"{}")
        timestamp = mtimes[index % len(mtimes)]
        path.touch()
        path.chmod(0o600)
        os.utime(path, ns=(timestamp, timestamp))
    legacy_json._write_provenance(
        source_root,
        state_root,
        legacy_json.master_mdb_sha256(database_path),
        complete=True,
    )


def test_provenance_not_mtime_controls_generated_staleness(tmp_path):
    database_path = tmp_path / "master.mdb"
    database_path.write_bytes(b"identical master content")
    source_root = tmp_path / "source"
    coarse_state = tmp_path / "coarse-state"
    divergent_state = tmp_path / "divergent-state"
    coarse = 1_700_000_000_000_000_000
    _write_generated_set(
        source_root, coarse_state, database_path, (coarse,),
    )
    _write_generated_set(
        source_root,
        divergent_state,
        database_path,
        (coarse - 9_000_000_000, coarse + 9_000_000_000),
    )

    assert legacy_json.stale_master_json_files(
        source_root, coarse_state, database_path,
    ) == []
    assert legacy_json.stale_master_json_files(
        source_root, divergent_state, database_path,
    ) == []


def test_mismatched_or_missing_provenance_blocks_only_present_output(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    database_path = tmp_path / "master.mdb"
    database_path.write_bytes(b"current master")
    source_root.mkdir()
    (source_root / "settings.json").write_text(
        json.dumps({
            "master_data": {"master_mdb_path": str(database_path)},
        }),
        encoding="utf-8",
    )

    assert master_data_preflight.career_master_data_error(
        source_root, state_root, 4,
    ) is None

    output_dir = state_paths_for(source_root, state_root).master_json_dir
    output_dir.mkdir(parents=True)
    present = output_dir / "race_map.json"
    present.write_bytes(b"{}")
    detail = master_data_preflight.career_master_data_error(
        source_root, state_root, 4,
    )
    assert detail is not None
    assert str(present) in detail

    legacy_json._write_provenance(
        source_root,
        state_root,
        hashlib.sha256(b"different master").hexdigest(),
        complete=True,
    )
    assert "does not match master.mdb" in (
        master_data_preflight.career_master_data_error(
            source_root, state_root, 4,
        ) or ""
    )
