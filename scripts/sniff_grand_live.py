"""Request-only Grand Live traffic sniffer.

Usage:
  1. Launch Umamusume and reach Home.
  2. Run: python scripts/sniff_grand_live.py
  3. Start / resume Grand Live manually and play through the screens to map.
  4. Ctrl+C after capture.

Writes sanitized request JSONL to uma_runtime/captures/.

This intentionally captures requests only.  The filter is Grand-Live-specific:
`single_mode_live/*` endpoints are always kept, and any request payload carrying
`scenario_id == 3` is also kept.  Each event includes the static route mapping
from docs/scenarios/grand-live-endpoints.md so endpoint -> client call -> phase
is obvious while capturing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import frida  # noqa: E402
import sniff_endpoint as base  # noqa: E402
import sniff_unity_cup as unity_sniff  # noqa: E402


SCENARIO_ID = 3
ENDPOINT_PREFIX = "single_mode_live/"

NOISE = {"tool/start_session"}

# Static route map copied from docs/scenarios/grand-live-endpoints.md.  Keep it
# near the sniffer so every captured line tells us which client method/screen
# likely emitted the request, without opening the doc during live RE.
ROUTES = {
    "single_mode_live/start": {
        "method": "SingleModeLiveAPI.SendStart",
        "phase": "boot/create",
        "request_fields": [
            "start_chara",
            "tp_info",
            "current_money",
            "use_tp",
            "current_succession_rank_point",
        ],
    },
    "single_mode_live/load": {
        "method": "SingleModeLiveAPI.SendLoadAsync",
        "phase": "boot/resume",
        "request_fields": [],
    },
    "single_mode_live/exec_command": {
        "method": "SingleModeLiveAPI.SendExecCommandAsync",
        "phase": "per-turn command",
        "request_fields": [
            "command_type",
            "command_id",
            "command_group_id",
            "select_id",
            "current_turn",
            "current_vital",
        ],
    },
    "single_mode_live/check_event": {
        "method": "SingleModeLiveAPI.SendCheckEvent",
        "phase": "per-turn event",
        "request_fields": ["event_id", "chara_id", "choice_number", "current_turn"],
    },
    "single_mode_live/continue": {
        "method": "SingleModeLiveAPI.SendContinueAsync",
        "phase": "per-turn continuation",
        "request_fields": ["continue_type", "current_turn"],
    },
    "single_mode_live/gain_skills": {
        "method": "SingleModeLiveAPI.SendGainSkills",
        "phase": "per-turn post-command",
        "request_fields": ["gain_skill_info_array", "current_turn"],
    },
    "single_mode_live/change_short_cut": {
        "method": "SingleModeLiveAPI.SendChangeShortCut",
        "phase": "per-turn shortcut",
        "request_fields": ["short_cut_state", "current_turn"],
    },
    "single_mode_live/minigame_end": {
        "method": "SingleModeLiveAPI.SendMiniGameEnd",
        "phase": "per-turn minigame",
        "request_fields": ["result", "current_turn"],
    },
    "single_mode_live/get_choice_reward": {
        "method": "SingleModeLiveAPI.SendGetChoiceRewardRequest",
        "phase": "event reward",
        "request_fields": ["event_id"],
    },
    "single_mode_live/master_square": {
        "method": "SingleModeLiveAPI.SendSingleModeLiveMasterSquareRequest",
        "phase": "live tree-square choice",
        "request_fields": ["square_id", "current_turn"],
    },
    "single_mode_live/reserve_square": {
        "method": "SingleModeLiveAPI.SendSingleModeLiveReserveSquareRequest",
        "phase": "live tree-square reservation",
        "request_fields": ["square_id", "current_turn"],
    },
    "single_mode_live/lottery_square": {
        "method": "SingleModeLiveAPI.SendSingleModeLiveLotterySquareRequest",
        "phase": "live tree-square lottery",
        "request_fields": ["square_id", "current_turn"],
    },
    "single_mode_live/live_start": {
        "method": "SingleModeScenarioLiveTopController.RequestLiveStart",
        "phase": "live performance start",
        "request_fields": ["current_turn"],
    },
    "single_mode_live/multi_race_reserve": {
        "method": "SingleModeRaceReserveConnect.LiveRequester.IRequester.Execute",
        "phase": "race deck reservation",
        "request_fields": [
            "deck_num",
            "deck_name",
            "add_race_array",
            "cancel_race_array",
        ],
    },
    "single_mode_live/race_entry": {
        "method": "SingleModeLiveAPI.SendRaceEntryAsync",
        "phase": "race entry",
        "request_fields": ["program_id", "current_turn"],
    },
    "single_mode_live/race_start": {
        "method": "SingleModeLiveAPI.SendRaceStart",
        "phase": "race/live start",
        "request_fields": ["is_short", "current_turn"],
    },
    "single_mode_live/race_analyze": {
        "method": "SingleModeLiveAPI.SendAnalyzeRequest",
        "phase": "race analysis",
        "request_fields": ["program_id", "current_turn"],
    },
    "single_mode_live/change_running_style": {
        "method": "SingleModeLiveAPI.SendChangeRunningStyleRequest",
        "phase": "race setup",
        "request_fields": ["program_id", "running_style", "current_turn"],
    },
    "single_mode_live/race_end": {
        "method": "SingleModeLiveAPI.SendRaceEndAsync",
        "phase": "race result",
        "request_fields": ["current_turn"],
    },
    "single_mode_live/race_out": {
        "method": "SingleModeLiveAPI.SendRaceOut",
        "phase": "race exit/continue",
        "request_fields": ["current_turn"],
    },
    "single_mode_live/finish": {
        "method": "SingleModeLiveAPI.SendFinish",
        "phase": "career end",
        "request_fields": ["is_force_delete", "factor_lottery_id", "current_turn"],
    },
    "single_mode_live/factor_select": {
        "method": "SingleModeLiveAPI.SendFactorSelect",
        "phase": "post-career factor selection",
        "request_fields": ["current_turn", "skill_id_array"],
    },
    "single_mode_live/factor_lottery": {
        "method": "SingleModeLiveAPI.SendFactorLottery",
        "phase": "post-career factor lottery",
        "request_fields": ["lottery_count", "tp_info", "use_tp"],
    },
}


def normalize_endpoint(endpoint: str) -> str:
    value = str(endpoint or "").split("?", 1)[0].strip("/")
    if value.startswith("umamusume/"):
        value = value[len("umamusume/") :]
    return value


def route_info(endpoint: str) -> dict:
    endpoint = normalize_endpoint(endpoint)
    info = ROUTES.get(endpoint)
    if info:
        return {"endpoint": endpoint, **info}
    return {
        "endpoint": endpoint,
        "method": None,
        "phase": None,
        "request_fields": [],
    }


def collect_scenario_ids(value, path="request", out=None, *, depth=0):
    if out is None:
        out = []
    if depth > 8 or len(out) >= 40:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) == "scenario_id":
                try:
                    out.append({"path": child_path, "value": int(child)})
                except (TypeError, ValueError):
                    out.append({"path": child_path, "value": child})
            elif isinstance(child, (dict, list)):
                collect_scenario_ids(child, child_path, out, depth=depth + 1)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:40]):
            collect_scenario_ids(child, f"{path}[{idx}]", out, depth=depth + 1)
    return out


def is_grand_live(endpoint: str, wire) -> bool:
    endpoint = normalize_endpoint(endpoint)
    if endpoint.startswith(ENDPOINT_PREFIX):
        return True
    return any(item.get("value") == SCENARIO_ID for item in collect_scenario_ids(wire))


def meaningful_request(wire):
    if not isinstance(wire, dict):
        return unity_sniff.sanitize(wire)
    return {
        key: unity_sniff.sanitize(value, list_limit=120)
        for key, value in wire.items()
        if key not in unity_sniff.BOILERPLATE and not base.is_sensitive_key(key)
    }


def observed_keys(wire) -> list[str]:
    if not isinstance(wire, dict):
        return []
    return [
        str(key)
        for key in wire.keys()
        if key not in unity_sniff.BOILERPLATE and not base.is_sensitive_key(key)
    ]


def write_event(handle, event):
    handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    handle.flush()


def _self_check():
    start = {
        "viewer_id": 123,
        "start_chara": {"scenario_id": 3, "card_id": 100101},
    }
    assert is_grand_live("single_mode_live/start", {"start_chara": {"scenario_id": 4}})
    assert is_grand_live("single_mode_free/start", start)
    assert not is_grand_live("single_mode_team/start", {"start_chara": {"scenario_id": 2}})
    assert route_info("/umamusume/single_mode_live/exec_command")["phase"] == "per-turn command"
    assert meaningful_request(start) == {"start_chara": {"scenario_id": 3, "card_id": 100101}}
    print("self-check ok")


def main():
    parser = argparse.ArgumentParser(
        description="Sniff Grand Live request-only traffic (scenario_id == 3 / single_mode_live/*)."
    )
    parser.add_argument("filters", nargs="*", help="endpoint substring filters after Grand Live filtering")
    parser.add_argument("--out", type=pathlib.Path, help="output JSONL path")
    parser.add_argument("--legacy-hook", action="store_true", help="use older narrow TLS hook")
    parser.add_argument(
        "--include-non-live",
        action="store_true",
        help="capture filter matches even when endpoint/payload is not Grand Live",
    )
    parser.add_argument("--self-check", action="store_true", help="run local asserts and exit")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    filters = [item.lower() for item in args.filters]
    out_path = args.out or ROOT / "uma_runtime" / "captures" / f"grand_live_requests_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = out_path.with_suffix(".summary.json")

    def matches(endpoint: str, wire) -> bool:
        endpoint = normalize_endpoint(endpoint)
        if endpoint in NOISE:
            return False
        if not args.include_non_live and not is_grand_live(endpoint, wire):
            return False
        return not filters or any(item in endpoint.lower() for item in filters)

    print(f"Attaching to {base.PROCESS_NAME} ...", flush=True)
    print(f"Output: {out_path}", flush=True)
    print(f"Summary: {summary_path}", flush=True)
    print("Mode: request-only; Grand Live filter = scenario_id == 3 or single_mode_live/*", flush=True)
    if filters:
        print(f"Endpoint filters: {filters}", flush=True)
    print("In game: start/resume Grand Live manually, click target screens, Ctrl+C after mapping.", flush=True)

    session = None
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            session = frida.attach(base.PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {base.PROCESS_NAME} not found within 60s.", flush=True)
        return 1

    seen = {"request_id": 0, "saved_requests": 0, "decode_errors": 0, "ignored_non_live": 0}
    route_counts: dict[str, int] = {}
    route_sequence: list[str] = []

    with out_path.open("w", encoding="utf-8") as handle:

        def on_message(message, data):
            if message.get("type") == "error":
                print(f"Frida error: {message.get('description')}", flush=True)
                return
            payload = message.get("payload") or {}
            if payload.get("type") != "creds":
                return

            endpoint = normalize_endpoint(payload.get("endpoint", ""))
            udid = payload.get("udid") or ""
            body = payload.get("body") or ""
            try:
                wire = base.unpack_request(body, udid)
            except Exception as exc:
                seen["decode_errors"] += 1
                print(f"[{endpoint}] request decode failed: {exc}", flush=True)
                return

            live_match = is_grand_live(endpoint, wire)
            if not live_match:
                seen["ignored_non_live"] += 1
            if not matches(endpoint, wire):
                return

            seen["request_id"] += 1
            request_id = seen["request_id"]
            info = route_info(endpoint)
            scenario_ids = collect_scenario_ids(wire)
            route_counts[endpoint] = route_counts.get(endpoint, 0) + 1
            if not route_sequence or route_sequence[-1] != endpoint:
                route_sequence.append(endpoint)

            event = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "kind": "request",
                "request_id": request_id,
                "scenario_filter": {
                    "target_scenario_id": SCENARIO_ID,
                    "matched": live_match,
                    "observed_scenario_ids": scenario_ids,
                },
                "endpoint": endpoint,
                "route": info,
                "app_ver": payload.get("app_ver"),
                "res_ver": payload.get("res_ver"),
                "observed_keys": observed_keys(wire),
                "request": meaningful_request(wire),
            }
            write_event(handle, event)
            seen["saved_requests"] += 1

            fields = ", ".join(info["request_fields"]) or "<none>"
            method = info["method"] or "<unknown static method>"
            phase = info["phase"] or "<unknown phase>"
            print(f"\n>> #{request_id} REQUEST {endpoint}", flush=True)
            print(f"   map: {method} | {phase}", flush=True)
            print(f"   doc fields: {fields}", flush=True)
            if scenario_ids:
                print(f"   scenario ids: {scenario_ids}", flush=True)
            print(json.dumps(event["request"], ensure_ascii=False, indent=2, default=str)[:5000], flush=True)

        try:
            js_code = base.JS_CODE if args.legacy_hook else unity_sniff.patch_js_wide_requests(base.JS_CODE)
            script = session.create_script(js_code)
            script.on("message", on_message)
            script.load()
            print("Hook loaded. Waiting for Grand Live requests.", flush=True)
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopped by user.", flush=True)
        finally:
            try:
                session.detach()
            except Exception:
                pass

    summary = {
        "output": str(out_path),
        "scenario_id": SCENARIO_ID,
        "mode": "request-only",
        "saved_requests": seen["saved_requests"],
        "decode_errors": seen["decode_errors"],
        "ignored_non_live": seen["ignored_non_live"],
        "route_counts": route_counts,
        "route_sequence": route_sequence,
        "routes": {endpoint: route_info(endpoint) for endpoint in sorted(route_counts)},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        f"Saved {seen['saved_requests']} Grand Live request(s), "
        f"{seen['decode_errors']} decode error(s) -> {out_path}",
        flush=True,
    )
    print(f"Route summary -> {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())