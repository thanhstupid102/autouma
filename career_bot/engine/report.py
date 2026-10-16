import hashlib
import json
import re
import traceback
from pathlib import Path

import core.operational_time as operational_time
from core.settings import Settings
from uma_api.diagnostics import PayloadSerializationFailure
from uma_api.errors import api_error_result_code
from core.runtime_paths import (
    atomic_write_private_bytes,
    atomic_write_private_text,
    atomic_write_private_text_nondurable,
    ensure_private_dir,
)

# Cap how many career_log_<account>_*.json files are kept per account. Each report can
# be tens of MB, so unbounded growth bloats bot_logs/ to GBs. Override via env.
CAREER_LOG_KEEP = Settings.UMA_MAX_CAREER_LOGS
# Configured by UMA_MAX_CAREER_API_BODY_BYTES; defaults to 2 KiB in settings.py.
_MARKER_TOP_LEVEL_KEY_LIMIT = 32
_MARKER_EVENT_LIMIT = 32
_MARKER_CHOICE_LIMIT = 16


class CareerReport(dict):
    """Report mapping with an in-memory revision that is never serialized."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.revision = 0


def mark_report_dirty(report):
    revision = getattr(report, "revision", None)
    if isinstance(revision, int):
        report.revision = revision + 1


def report_revision(report):
    revision = getattr(report, "revision", None)
    return revision if isinstance(revision, int) else None


def _prune_career_logs(output_dir, safe, keep=CAREER_LOG_KEEP):
    """Delete all but the most recent `keep` career logs for this account. The timestamp
    `latest_career_log_*` pointer is a different prefix and is never
    matched/removed. Best-effort: never raises."""
    try:
        pattern = f"career_log_{safe}_*.json" if safe else "career_log_*.json"
        files = sorted(
            Path(output_dir).glob(pattern),
            key=lambda path: path.stat().st_mtime_ns,
        )
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:  # unlink() only ever fails with OSError
                pass
    except Exception:
        pass


def now_iso():
    return operational_time.utc_iso_seconds()


def new_report(preset=None, scenario_id=0):
    preset = preset or {}
    return CareerReport({
        "started_at": now_iso(),
        "ended_at": None,
        "preset_name": preset.get("name", ""),
        "scenario_id": scenario_id,
        "status": "running",
        "error": None,
        "final_turn": 0,
        "clocks_used": 0,
        "clocks_bought": 0,
        "turns": [],
    })


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def turn_from_event(event):
    data = event.get("data") or {}
    for key in ("payload", "request_payload"):
        payload = data.get(key) or {}
        if payload.get("current_turn") is not None:
            return safe_int(payload.get("current_turn"))
    if event.get("turn") is not None:
        return safe_int(event.get("turn"))
    return 0


def get_turn(report, turn_number):
    turn_number = safe_int(turn_number)
    for turn in report.setdefault("turns", []):
        if safe_int(turn.get("turn")) == turn_number:
            return turn
    turn = {
        "turn": turn_number,
        "api_calls": [],
        "skill_buy_attempts": [],
        "item_buy_attempts": [],
        "item_usage_attempts": [],
    }
    report.setdefault("turns", []).append(turn)
    report["turns"].sort(key=lambda row: safe_int(row.get("turn")))
    return turn


def merge_turn(report, row):
    turn_number = safe_int(row.get("turn"))
    turn = get_turn(report, turn_number)
    preserved = {
        "api_calls": turn.get("api_calls") or [],
        "skill_buy_attempts": turn.get("skill_buy_attempts") or [],
        "item_buy_attempts": turn.get("item_buy_attempts") or [],
        "item_usage_attempts": turn.get("item_usage_attempts") or [],
    }
    turn.update(row)
    for key, value in preserved.items():
        turn[key] = value
    report["final_turn"] = max(safe_int(report.get("final_turn")), turn_number)
    mark_report_dirty(report)
    return turn


def add_event(report, row):
    event = row.get("event")
    turn = get_turn(report, row.get("turn"))
    if event == "turn":
        return merge_turn(report, row)
    if event == "skills_attempt":
        turn.setdefault("skill_buy_attempts", []).append(row)
    elif event == "items_buy_attempt":
        turn.setdefault("item_buy_attempts", []).append(row)
    elif event == "items_use_attempt":
        turn.setdefault("item_usage_attempts", []).append(row)
    else:
        turn.setdefault("events", []).append(row)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(row.get("turn")))
    mark_report_dirty(report)
    return turn


def _json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _event_catalog_summary(event):
    if not isinstance(event, dict) or not event.get("story_id"):
        return None
    contents = event.get("event_contents_info") or {}
    if isinstance(contents, dict):
        choice_array = contents.get("choice_array") or []
    else:
        choice_array = []
    choices = []
    if isinstance(choice_array, list):
        for choice in choice_array[:_MARKER_CHOICE_LIMIT]:
            if isinstance(choice, dict):
                choices.append({"select_index": choice.get("select_index")})
    contents_summary = {
        "support_card_id": (
            contents.get("support_card_id")
            if isinstance(contents, dict)
            else None
        ),
        "choice_array": choices,
    }
    if isinstance(choice_array, list) and len(choice_array) > _MARKER_CHOICE_LIMIT:
        contents_summary["choice_count"] = len(choice_array)
        contents_summary["choice_array_truncated"] = True
    return {
        "story_id": event.get("story_id"),
        "chara_id": event.get("chara_id"),
        "event_contents_info": contents_summary,
    }


def _collect_event_catalog_shape(value, summaries):
    if isinstance(value, dict):
        events = value.get("unchecked_event_array") or []
        if isinstance(events, list):
            for event in events:
                summary = _event_catalog_summary(event)
                if summary is not None:
                    if len(summaries) >= _MARKER_EVENT_LIMIT:
                        return True
                    summaries.append(summary)
            # Walk event contents too, but do not re-read this array and mistake
            # reaching the cap for having omitted a later event.
            for event in events:
                if _collect_event_catalog_shape(event, summaries):
                    return True
        for key, nested in value.items():
            if key == "unchecked_event_array":
                continue
            if _collect_event_catalog_shape(nested, summaries):
                return True
    elif isinstance(value, list):
        for nested in value:
            if _collect_event_catalog_shape(nested, summaries):
                return True
    return False


def _oversize_body_marker(event, body, body_bytes, max_body_bytes):
    endpoint = event.get("endpoint") or event.get("url") or ""
    marker = {
        "_omitted": "api_body_exceeds_limit",
        "endpoint": endpoint,
        "direction": event.get("direction"),
        "dropped_body_bytes": len(body_bytes),
        "configured_limit_bytes": max_body_bytes,
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "body_type": type(body).__name__,
    }
    if isinstance(body, dict):
        keys = [str(key) for key in body]
        marker["top_level_keys"] = keys[:_MARKER_TOP_LEVEL_KEY_LIMIT]
        marker["top_level_key_count"] = len(keys)
    elif isinstance(body, list):
        marker["item_count"] = len(body)

    summaries: list[dict] = []
    truncated = _collect_event_catalog_shape(body, summaries)
    if summaries:
        marker["event_catalog_shape"] = summaries
        if truncated:
            marker["event_catalog_shape_truncated"] = True
    return marker


def _measurement_failed_body_marker(event, body, exc, max_body_bytes):
    return {
        "_omitted": "api_body_measurement_failed",
        "endpoint": event.get("endpoint") or event.get("url") or "",
        "direction": event.get("direction"),
        "body_type": type(body).__name__,
        "measurement_error": type(exc).__name__,
        "configured_limit_bytes": max_body_bytes,
    }


def add_api_call(report, event, max_body_bytes=None):
    max_body_bytes = (
        Settings.UMA_MAX_CAREER_API_BODY_BYTES
        if max_body_bytes is None
        else int(max_body_bytes)
    )
    stored_event = dict(event)
    body_bytes = None
    if "data" in stored_event:
        body = stored_event["data"]
        try:
            body_bytes = _json_bytes(body)
            if max_body_bytes > 0 and len(body_bytes) > max_body_bytes:
                stored_event["data"] = _oversize_body_marker(
                    stored_event, body, body_bytes, max_body_bytes,
                )
            else:
                # Store exactly the JSON representation measured for the report and
                # trace, so later state reconciliation cannot mutate this snapshot.
                stored_event["data"] = json.loads(body_bytes)
        except Exception as exc:
            marker = _measurement_failed_body_marker(
                stored_event, body, exc, max_body_bytes,
            )
            stored_event["data"] = marker
            body_bytes = PayloadSerializationFailure(marker)
    turn = get_turn(report, turn_from_event(event))
    turn.setdefault("api_calls", []).append(stored_event)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(turn.get("turn")))
    mark_report_dirty(report)
    return body_bytes


def add_decision(report, state, decision):
    data = (state or {}).get("data") or {}
    chara = data.get("chara_info") or {}
    payload = dict(getattr(decision, "payload", {}) or {})
    turn = get_turn(report, payload.get("current_turn") or chara.get("turn") or 0)
    turn["current_command"] = payload
    turn["selected_action"] = getattr(decision, "action", "")
    turn["decision_reason"] = getattr(decision, "reason", "")
    turn["current_action_taken"] = getattr(decision, "action", "")
    mark_report_dirty(report)


def set_error(report, exc):
    error = {
        "type": type(exc).__name__,
        "message": str(exc),
        "stack_trace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    endpoint = getattr(exc, "endpoint", None)
    if endpoint:
        error["endpoint"] = str(endpoint)
    result_code = api_error_result_code(exc)
    if result_code is not None:
        error["result_code"] = result_code
    report["status"] = "error"
    report["error"] = error
    mark_report_dirty(report)


def finish_report(report, status=None):
    if status:
        report["status"] = status
    if report.get("status") == "running":
        report["status"] = "finished"
    report["ended_at"] = now_iso()
    turns = report.get("turns") or []
    if turns:
        report["final_turn"] = max(safe_int(turn.get("turn")) for turn in turns)
    mark_report_dirty(report)


def _json_default(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def _safe_account(account):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(account or "").strip())


def begin_report_path(output_dir, account=""):
    """Compute the on-disk path for this career's log ONCE, at career start, so every
    realtime flush rewrites the SAME file instead of minting a new timestamped file
    each flush (which would spam hundreds of files per career)."""
    output_dir = Path(output_dir)
    ensure_private_dir(output_dir)
    stamp = operational_time.utc_filename_stamp()
    safe = _safe_account(account)
    return output_dir / (f"career_log_{safe}_{stamp}.json" if safe else f"career_log_{stamp}.json")


def flush_report(report, path):
    """Process-crash-safe realtime write via a same-directory atomic replace.

    This best-effort debug artifact intentionally skips fsync; final reports remain
    durable and pretty-printed through write_report().
    """
    path = Path(path)
    atomic_write_private_text_nondurable(
        path,
        json.dumps(
            report,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        ),
    )
    return path


def write_report(report, output_dir, account="", path=None):
    """Finalize the career log. Writes to the SAME `path` used by the realtime flushes
    (or mints one if called standalone), then updates the latest_career_log pointer and
    prunes old logs."""
    output_dir = Path(output_dir)
    ensure_private_dir(output_dir)
    safe = _safe_account(account)
    if path is None:
        path = begin_report_path(output_dir, account)
    path = Path(path)

    atomic_write_private_text(
        path,
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default),
    )

    latest = output_dir / (f"latest_career_log_{safe}.json" if safe else "latest_career_log.json")
    try:
        atomic_write_private_bytes(latest, path.read_bytes())
    except OSError:  # copyfile() (incl. SameFileError) only ever fails with OSError
        pass
    _prune_career_logs(output_dir, safe)
    return path
