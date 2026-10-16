"""Console/log rendering of API traffic.

Redaction, error-detail formatting and the request/response summaries used by
console output and traces. None of this touches the wire -- it only *describes*
a call that already happened -- so it lives beside the transport class rather
than inside it.
"""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class PayloadSerializationFailure:
    """Marker returned when a body is already known to be unserializable."""

    marker: dict


SENSITIVE_ERROR_KEYS = {
    "auth_key",
    "credential",
    "device_id",
    "device_token",
    "dmm_onetime_token",
    "input_viewer_id",
    "link_password",
    "nonce",
    "password",
    "refresh_token",
    "session_ticket",
    "sid",
    "steam_session_ticket",
    "target_viewer_id",
    "chained_viewer_id",
    "udid",
}


def redact_for_console(value, key=""):
    if key in SENSITIVE_ERROR_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_for_console(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_console(item, key) for item in value[:20]]
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "...<truncated>"
    return value


def format_api_error(ep, rc, res):
    details = {
        "endpoint": ep,
        "response_code": res.get("response_code"),
        "result_code": rc,
        "data_headers": redact_for_console(res.get("data_headers") or {}),
    }
    data = res.get("data")
    if isinstance(data, dict):
        interesting = {}
        for key in (
            "error_code",
            "error_message",
            "message",
            "result_code",
            "viewer_id",
            "current_turn",
            "chara_info",
            "single_mode_chara_light",
        ):
            if key in data:
                interesting[key] = data[key]
        if interesting:
            details["data"] = redact_for_console(interesting)
    elif data is not None:
        details["data"] = redact_for_console(data)
    return json.dumps(details, ensure_ascii=False, default=str)


def api_payload_summary(ep, payload):
    payload = payload or {}
    summary = {"current_turn": payload.get("current_turn")}
    if ep.endswith("/gain_skills"):
        summary["gain_skill_info_array"] = payload.get("gain_skill_info_array") or []
    elif ep.endswith("/multi_item_exchange"):
        summary["exchange_item_info_array"] = payload.get("exchange_item_info_array") or []
    elif ep.endswith("/multi_item_use"):
        summary["use_item_info_array"] = payload.get("use_item_info_array") or []
    elif ep.endswith(("/master_square", "/reserve_square", "/lottery_square")):
        # Without this the Grand Live trace logs only current_turn, so a run log
        # cannot say WHICH square the bot bought -- reconstructing the 2026-07-27
        # session meant diffing performance tokens between responses instead.
        summary["square_id"] = payload.get("square_id")
    return summary


def safe_payload(payload):
    def redact(value, key=""):
        if key in SENSITIVE_ERROR_KEYS:
            return "<redacted>"
        if isinstance(value, dict):
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(item, key) for item in value]
        return value

    return redact(dict(payload or {}))


def response_summary(res):
    data = res.get("data") or {}
    headers = res.get("data_headers") or {}
    chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
    home = data.get("home_info") or {}
    events = data.get("unchecked_event_array") or []
    race = data.get("race_start_info") or {}
    summary = {
        "result_code": headers.get("result_code"),
        "keys": list(data.keys()),
    }
    if chara:
        summary["chara"] = {
            "turn": chara.get("turn"),
            "vital": chara.get("vital"),
            "max_vital": chara.get("max_vital"),
            "skill_point": chara.get("skill_point"),
            "fans": chara.get("fans"),
            "playing_state": chara.get("playing_state"),
        }
    if home:
        summary["commands"] = [
            {
                "type": item.get("command_type"),
                "id": item.get("command_id"),
                "group": item.get("command_group_id"),
                "enable": item.get("is_enable"),
                "fail": item.get("failure_rate"),
            }
            for item in home.get("command_info_array") or []
        ]
    if events:
        summary["events"] = [
            {
                "event_id": item.get("event_id"),
                "chara_id": item.get("chara_id"),
                "choices": len(((item.get("event_contents_info") or {}).get("choice_array") or [])),
            }
            for item in events
        ]
    if race:
        summary["race_start_info"] = {
            "program_id": race.get("program_id"),
            "race_instance_id": race.get("race_instance_id"),
            "is_short": race.get("is_short"),
        }
    return summary
