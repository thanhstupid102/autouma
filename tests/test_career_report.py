import importlib
import json
import logging
import os
import stat
from pathlib import Path

import pytest

import core.runtime_paths as runtime_paths
import core.settings as settings_module
from career_bot.engine import runner as runner_module
from career_bot.engine.report import (
    _prune_career_logs,
    add_api_call,
    add_event,
    flush_report,
    new_report,
    write_report,
)
from career_bot.engine.runner import CareerRunner
from career_bot.events.catalog import build_catalog_from_logs
from career_bot.scenarios.mant.items import MantItemManager
from career_bot.state_merge import merge_state
from core.settings import (
    DEFAULT_CAREER_API_BODY_MAX_BYTES,
    Settings,
    career_api_body_max_bytes,
)


def _api_calls(report):
    return report["turns"][0]["api_calls"]


def test_career_log_pruning_uses_mtime_not_filename(tmp_path):
    older = tmp_path / "career_log_account_20260730_120000.json"
    newer = tmp_path / "career_log_account_20260730_050000.json"
    older.write_text("older", encoding="utf-8")
    newer.write_text("newer", encoding="utf-8")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    _prune_career_logs(tmp_path, "account", keep=1)

    assert not older.exists()
    assert newer.exists()


def _catalog_event(story_id=123, choice_count=2):
    return {
        "story_id": story_id,
        "chara_id": 456,
        "event_contents_info": {
            "support_card_id": 789,
            "choice_array": [
                {"select_index": index}
                for index in range(1, choice_count + 1)
            ],
        },
    }


def test_add_api_call_caps_oversize_body_and_keeps_small_body():
    report = new_report()
    small = {"ok": True}
    large = {
        "blob": "x" * 128,
        "server_response": {
            "unchecked_event_array": [{
                "story_id": 123,
                "chara_id": 456,
                "event_contents_info": {
                    "support_card_id": 789,
                    "choice_array": [{"select_index": 1}],
                },
            }],
        },
    }

    add_api_call(
        report,
        {"endpoint": "small/endpoint", "direction": "REQ", "data": small},
        max_body_bytes=64,
    )
    add_api_call(
        report,
        {"endpoint": "load/index", "direction": "RES", "data": large},
        max_body_bytes=64,
    )

    small_stored, large_stored = _api_calls(report)
    assert small_stored["data"] == small
    marker = large_stored["data"]
    assert marker["_omitted"] == "api_body_exceeds_limit"
    assert marker["endpoint"] == "load/index"
    assert marker["dropped_body_bytes"] == len(
        json.dumps(large, separators=(",", ":")).encode("utf-8")
    )
    assert marker["top_level_keys"] == ["blob", "server_response"]
    assert marker["event_catalog_shape"][0]["story_id"] == 123


def test_add_api_call_snapshots_small_body_before_later_mutation():
    report = new_report()
    body = {"top_level": "before", "nested": {"value": "before"}}

    add_api_call(
        report,
        {"endpoint": "snapshot", "direction": "RES", "data": body},
        max_body_bytes=512,
    )
    body["top_level"] = "after"
    body["nested"]["value"] = "after"

    stored = _api_calls(report)[0]["data"]
    assert stored == {"top_level": "before", "nested": {"value": "before"}}
    assert stored is not body
    assert stored["nested"] is not body["nested"]


def test_snapshot_survives_merge_and_mant_shop_reconciliation():
    cap = 1024
    report = new_report()
    current = {
        "data": {
            "chara_info": {"turn": 60},
            "free_data_set": {
                "coin_num": 100,
                "user_item_info_array": [{"item_id": 1001, "num": 0}],
                "pick_up_item_info_array": [{
                    "shop_item_id": 1,
                    "item_id": 1001,
                    "item_buy_num": 0,
                }],
            },
        },
    }
    refreshed = {
        "data": {
            "free_data_set": {
                "refresh_block": "x" * (cap * 2),
                "pick_up_item_info_array": [{
                    "shop_item_id": 1,
                    "item_id": 1001,
                    "item_buy_num": 0,
                }],
            },
        },
    }
    assert len(json.dumps(current, separators=(",", ":")).encode("utf-8")) <= cap

    add_api_call(
        report,
        {"endpoint": "single_mode_free/check_event", "direction": "RES", "data": current},
        max_body_bytes=cap,
    )
    add_api_call(
        report,
        {"endpoint": "single_mode_free/check_event", "direction": "RES", "data": refreshed},
        max_body_bytes=cap,
    )

    assert _api_calls(report)[1]["data"]["_omitted"] == "api_body_exceeds_limit"
    merge_state(current, refreshed)
    MantItemManager()._ensure_local_exchange_applied(
        current,
        shop_item_id=1,
        item_id=1001,
        cost=10,
        before_num=0,
        before_buy_num=0,
        before_coin=100,
    )

    stored = _api_calls(report)[0]["data"]
    assert len(json.dumps(stored, separators=(",", ":")).encode("utf-8")) <= cap
    assert stored["data"]["free_data_set"]["pick_up_item_info_array"][0]["item_buy_num"] == 0
    assert current["data"]["free_data_set"]["pick_up_item_info_array"][0]["item_buy_num"] == 1


_REAL_CAREER_REPORT = (
    Path(__file__).resolve().parents[1]
    / "uma_runtime"
    / "bot_logs"
    / "career_log_yuko_20260726_184227.json"
)


@pytest.mark.skipif(
    not _REAL_CAREER_REPORT.exists(),
    reason="operator real-career fixture is unavailable",
)
def test_real_career_rebuild_keeps_every_nonmarker_body_within_default_cap():
    with _REAL_CAREER_REPORT.open(encoding="utf-8") as handle:
        source_report = json.load(handle)

    rebuilt = new_report()
    for source_turn in source_report["turns"]:
        for event in source_turn.get("api_calls") or []:
            add_api_call(rebuilt, event)

    for event in (event for turn in rebuilt["turns"] for event in turn["api_calls"]):
        body = event["data"]
        if not (isinstance(body, dict) and "_omitted" in body):
            assert len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= (
                Settings.UMA_MAX_CAREER_API_BODY_BYTES
            )


def test_api_body_threshold_default_and_setting_are_explicit(monkeypatch):
    assert DEFAULT_CAREER_API_BODY_MAX_BYTES == 2048

    monkeypatch.setattr(Settings, "UMA_MAX_CAREER_API_BODY_BYTES", 8)
    report = new_report()
    add_api_call(
        report,
        {
            "endpoint": "configured",
            "direction": "RES",
            "data": {"x": "12345678"},
        },
    )

    assert _api_calls(report)[0]["data"]["configured_limit_bytes"] == 8


def test_api_body_cap_config_falls_back_and_has_explicit_disable_values(
    monkeypatch, caplog,
):
    assert DEFAULT_CAREER_API_BODY_MAX_BYTES == 2048
    try:
        with monkeypatch.context() as environment:
            environment.setenv("UMA_MAX_CAREER_API_BODY_BYTES", "not-a-number")
            caplog.set_level(logging.WARNING, logger="settings")
            assert (
                importlib.reload(settings_module).Settings.UMA_MAX_CAREER_API_BODY_BYTES
                == DEFAULT_CAREER_API_BODY_MAX_BYTES
            )
        assert "UMA_MAX_CAREER_API_BODY_BYTES value 'not-a-number'" in caplog.text

        for raw, expected in (("0", 0), ("-8", 0), ("123", 123)):
            with monkeypatch.context() as environment:
                environment.setenv("UMA_MAX_CAREER_API_BODY_BYTES", raw)
                assert (
                    importlib.reload(settings_module).Settings.UMA_MAX_CAREER_API_BODY_BYTES
                    == expected
                )
    finally:
        importlib.reload(settings_module)

    assert career_api_body_max_bytes() == DEFAULT_CAREER_API_BODY_MAX_BYTES


@pytest.mark.parametrize("cap", (0, -1))
def test_nonpositive_api_body_cap_keeps_a_verbatim_snapshot(monkeypatch, cap):
    body = {"blob": "x" * 128, "nested": {"value": "before"}}
    expected_bytes = json.dumps(
        body, separators=(",", ":"),
    ).encode("utf-8")
    monkeypatch.setattr(Settings, "UMA_MAX_CAREER_API_BODY_BYTES", cap)
    report = new_report()

    body_bytes = add_api_call(
        report, {"endpoint": "debug/body", "direction": "RES", "data": body},
    )
    body["nested"]["value"] = "after"

    assert body_bytes == expected_bytes
    assert _api_calls(report)[0]["data"] == {
        "blob": "x" * 128,
        "nested": {"value": "before"},
    }


def test_measurement_failures_keep_api_rows_and_log_context(monkeypatch, tmp_path):
    class BadString:
        def __str__(self):
            raise RuntimeError("string conversion failed")

    circular = {}
    circular["self"] = circular
    bodies = [circular, {"broken": BadString()}]
    log_fields = []

    monkeypatch.setattr(CareerRunner, "_run", lambda *args: None)
    monkeypatch.setattr(
        runner_module, "set_log_fields", lambda **fields: log_fields.append(fields),
    )
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    client = type("Client", (), {})()
    runner.start(client, {"name": "test"}, initial_result={})
    runner.thread.join()

    client.on_api_log("REQ", "test/measure", bodies.pop(0))
    client.on_api_log("REQ", "test/measure", bodies.pop(0))

    markers = [row["data"] for row in _api_calls(runner.report)]
    assert [marker["_omitted"] for marker in markers] == [
        "api_body_measurement_failed",
        "api_body_measurement_failed",
    ]
    assert [marker["measurement_error"] for marker in markers] == [
        "ValueError",
        "RuntimeError",
    ]
    assert all(marker["endpoint"] == "test/measure" for marker in markers)
    assert all(marker["direction"] == "REQ" for marker in markers)
    assert all(marker["body_type"] == "dict" for marker in markers)
    assert log_fields == [
        {"endpoint": "test/measure", "result_code": None},
        {"endpoint": "test/measure", "result_code": None},
    ]


@pytest.mark.parametrize("event_count, truncated", ((32, False), (33, True)))
def test_event_catalog_marker_marks_only_omitted_events(event_count, truncated):
    body = {
        "blob": "x" * 1024,
        "unchecked_event_array": [
            _catalog_event(story_id=index + 1) for index in range(event_count)
        ],
    }
    report = new_report()

    add_api_call(
        report,
        {"endpoint": "load/index", "direction": "RES", "data": body},
        max_body_bytes=32,
    )

    marker = _api_calls(report)[0]["data"]
    assert len(marker["event_catalog_shape"]) == min(event_count, 32)
    assert ("event_catalog_shape_truncated" in marker) is truncated


@pytest.mark.parametrize("choice_count, truncated", ((16, False), (17, True)))
def test_event_catalog_marker_marks_only_omitted_choices(choice_count, truncated):
    body = {"blob": "x" * 1024, "unchecked_event_array": [_catalog_event(choice_count=choice_count)]}
    report = new_report()

    add_api_call(
        report,
        {"endpoint": "load/index", "direction": "RES", "data": body},
        max_body_bytes=32,
    )

    contents = _api_calls(report)[0]["data"]["event_catalog_shape"][0]["event_contents_info"]
    assert len(contents["choice_array"]) == min(choice_count, 16)
    assert ("choice_array_truncated" in contents) is truncated
    if truncated:
        assert contents["choice_count"] == choice_count


def test_capped_api_marker_survives_flush_and_populates_event_catalog(tmp_path):
    event = {
        "story_id": 123,
        "chara_id": 456,
        "event_contents_info": {
            "support_card_id": 789,
            "choice_array": [{"select_index": 1}, {"select_index": 3}],
        },
    }
    report = new_report()
    add_api_call(
        report,
        {
            "endpoint": "load/index",
            "direction": "RES",
            "data": {
                "blob": "x" * 1024,
                "server_response": {"unchecked_event_array": [event, event]},
            },
        },
        max_body_bytes=32,
    )
    flush_report(report, tmp_path / "bot_logs" / "career_log_capped.json")

    catalog = build_catalog_from_logs(tmp_path, state_root=tmp_path, include_master=False)

    entry = catalog["123"]
    assert entry["story_id"] == "123"
    assert entry["chara_id"] == 456
    assert entry["support_card_id"] == 789
    assert entry["n_choices"] == 2
    assert entry["select_indexes"] == [1, 3]
    assert entry["seen_count"] == 2


def test_realtime_flush_is_atomic_nondurable_and_final_write_is_durable(
    tmp_path, monkeypatch,
):
    fsync_calls = []
    replace_destinations = []
    real_replace = runtime_paths.os.replace

    monkeypatch.setattr(
        runtime_paths.os, "fsync", lambda fd: fsync_calls.append(fd),
    )

    def record_replace(source, destination):
        replace_destinations.append(destination)
        real_replace(source, destination)

    monkeypatch.setattr(runtime_paths.os, "replace", record_replace)
    report = new_report()
    add_event(report, {"event": "turn", "turn": 1, "stats": {"speed": 1}})
    path = tmp_path / "career_log_test.json"

    flush_report(report, path)

    assert fsync_calls == []
    assert replace_destinations == [path]
    assert "\n" not in path.read_text(encoding="utf-8")

    fsync_calls.clear()
    replace_destinations.clear()
    write_report(report, tmp_path, path=path)

    assert len(fsync_calls) == 2
    assert replace_destinations == [path, tmp_path / "latest_career_log.json"]
    assert "\n  \"started_at\"" in path.read_text(encoding="utf-8")


def test_unchanged_report_flush_is_skipped_but_changed_report_is_written(
    tmp_path, monkeypatch,
):
    calls = []
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner._report_path = tmp_path / "career_log_test.json"
    monkeypatch.setattr(
        "career_bot.engine.reporting.flush_report",
        lambda report, path: calls.append((report, path)),
    )

    runner._flush_report(force=True)
    runner._flush_report(force=True)
    add_event(runner.report, {"event": "changed", "turn": 1})
    runner._flush_report(force=True)

    assert len(calls) == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_career_report_files_remain_private_on_posix(tmp_path):
    report = new_report()
    add_event(report, {"event": "turn", "turn": 1})
    path = tmp_path / "bot_logs" / "career_log_test.json"

    flush_report(report, path)
    write_report(report, path.parent, path=path)

    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    latest = path.parent / "latest_career_log.json"
    assert stat.S_IMODE(latest.stat().st_mode) == 0o600
