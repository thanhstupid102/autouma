"""Frida boot-sequence capturer -- diagnose the post-game-update login 102.

After a game client update the bot's saved app_ver/res_ver go stale and the
server starts rejecting read_info/index (result_code 102) even though
tool/start_session and load/index still pass. This script attaches to the live
(updated) game and dumps the BOOT endpoints (tool/start_session, load/index,
read_info/index) with their current APP-VER / RES-VER headers plus the full
decrypted request payload -- what we need to (a) read the new version strings
and (b) confirm whether the read_info/index request schema gained a field.

The game's TLS hook reads the *already-installed* interface pointer, so
attaching AFTER boot works -- but read_info/index only fires once during
boot->home. So to (re)capture it, once attached, go BACK TO TITLE and re-enter
HOME (that re-fires the boot calls). The APP-VER/RES-VER of ANY request is also
recorded as a fallback, so even a single in-game server action reveals the
current version.

This deliberately does NOT `import main` (that runs a slow pip install +
master.mdb generation on import, which delayed the first attempt past boot).
JS_CODE is lifted out of main.py by text.

Usage:
    1. Run:  python scripts/capture_boot.py
    2. In the game (already at home), tap Menu -> Return to Title, then tap to
       re-enter Home. read_info/index fires again and is captured.
    3. Reads uma_runtime/capture_boot.jsonl; exits once read_info/index seen.
"""
import sys
import json
import time
import pathlib

from core.settings import Settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
from uma_api.client import unpack_request  # noqa: E402 (safe import, no side effects)

PROCESS_NAME = "UmamusumePrettyDerby.exe"

# Lift JS_CODE out of main.py without importing it (avoids its pip/master.mdb
# import-time side effects that delayed the first capture past boot).
JS_CODE = Settings.JS_UMA_NETWORK_HOOKS.read_text(encoding="utf-8")

# Augment: also emit the RAW request header block so we can diff headers (a game
# update can add a required header, not just body fields). Inject a send() right
# before the existing parseWire() call inside parseHttp().
_anchor = "parseWire(em[1], vm[1], text.substring(idx + 4)"
_inject = "send({type:'rawhead', endpoint: em[1], head: text.substring(0, idx)});\n        "
if _anchor in JS_CODE:
    JS_CODE = JS_CODE.replace(_anchor, _inject + _anchor, 1)

# Capture EVERY endpoint the client hits at boot, in order, so we can see what
# (if anything) replaced read_info/index after the game update.
CAPTURE_ALL = True
BOOT_ENDPOINTS = ("tool/start_session", "load/index", "read_info/index")
OUT_PATH = ROOT / "uma_runtime" / "capture_boot.jsonl"

BOILERPLATE = {
    "viewer_id", "device", "device_id", "device_name", "graphics_device_name",
    "ip_address", "platform_os_version", "carrier", "keychain", "locale",
    "button_info", "dmm_viewer_id", "dmm_onetime_token", "timezone_offset",
    "steam_id", "steam_session_ticket",
}

ATTACH_TIMEOUT_SEC = 120    # poll for the game process this long
OVERALL_DEADLINE_SEC = 600  # keep listening this long once attached
CAPTURE_GRACE_SEC = 3.0     # keep listening this long after read_info seen


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("", encoding="utf-8")

    print(f"Attaching to {PROCESS_NAME} ...", flush=True)
    session = None
    attach_deadline = time.monotonic() + ATTACH_TIMEOUT_SEC
    while time.monotonic() < attach_deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {PROCESS_NAME} not found within {ATTACH_TIMEOUT_SEC}s.", flush=True)
        return 1
    print("Attached. Hooking TLS...", flush=True)
    print(">>> In game: Menu -> Return to Title, then re-enter Home to re-fire read_info.", flush=True)

    state = {"count": 0, "version_seen": False, "last_event_at": None,
             "seen_load_index": False, "seen_target_at": None, "order": []}
    # Endpoints whose FULL raw headers we also want (boot + the career-start call).
    HEADER_EPS = set(BOOT_ENDPOINTS) | {"single_mode_free/start", "single_mode_free/load"}
    TARGET_EP = "single_mode_free/start"

    def record(rec):
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if payload.get("type") == "rawhead":
            ep = payload.get("endpoint", "")
            if ep in HEADER_EPS:
                record({"endpoint": ep, "raw_headers": payload.get("head", "")})
            return
        if payload.get("type") != "creds":
            return
        ep = payload.get("endpoint", "")
        app_ver = payload.get("app_ver")
        res_ver = payload.get("res_ver")
        state["last_event_at"] = time.monotonic()

        if not state["version_seen"] and (app_ver or res_ver):
            state["version_seen"] = True
            print(f"\n*** CURRENT VERSION (from {ep}): APP-VER={app_ver}  RES-VER={res_ver} ***\n", flush=True)

        if not (CAPTURE_ALL or ep in BOOT_ENDPOINTS):
            return
        udid = payload.get("udid") or ""
        body = payload.get("body") or ""
        try:
            wire = unpack_request(body, udid)
        except Exception as exc:
            wire = {"__decode_error__": str(exc)}
        auth_key = payload.get("auth_key")
        record({"endpoint": ep, "app_ver": app_ver, "res_ver": res_ver,
                "auth_key_len": payload.get("auth_key_len"),
                "auth_key": auth_key, "udid": payload.get("udid"),
                "viewer_id": payload.get("viewer_id"), "payload": wire})
        if not state.get("auth_printed"):
            state["auth_printed"] = True
            print(f"\n*** LIVE auth_key: {auth_key}", flush=True)
            print(f"*** LIVE udid: {payload.get('udid')}  viewer_id: {payload.get('viewer_id')}\n", flush=True)
        state["count"] += 1
        state["order"].append(ep)
        if ep == "load/index":
            state["seen_load_index"] = True
        if ep == TARGET_EP:
            state["seen_target_at"] = time.monotonic()
            print(f"\n>>> Captured {TARGET_EP} -- stopping shortly.", flush=True)
        meaningful = {k: v for k, v in wire.items() if k not in BOILERPLATE} \
            if isinstance(wire, dict) else wire
        print("\n" + "=" * 44, flush=True)
        print(f"#{state['count']}  ENDPOINT : {ep}", flush=True)
        print("PAYLOAD (endpoint-specific keys):", flush=True)
        print(json.dumps(meaningful, ensure_ascii=False, indent=2, default=str), flush=True)
        print("=" * 44, flush=True)

    QUIESCENCE_SEC = 300.0  # long fallback; primary exit is capturing the target call
    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()
        print("Hook loaded. Capturing full boot sequence (Ctrl+C to stop).", flush=True)
        overall_deadline = time.monotonic() + OVERALL_DEADLINE_SEC
        while time.monotonic() < overall_deadline:
            tgt = state["seen_target_at"]
            if tgt is not None and (time.monotonic() - tgt) >= CAPTURE_GRACE_SEC:
                break
            le = state["last_event_at"]
            if state["seen_load_index"] and le is not None and (time.monotonic() - le) >= QUIESCENCE_SEC:
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            session.detach()
        except Exception:
            pass

    print(f"\nCaptured {state['count']} request(s) -> {OUT_PATH}", flush=True)
    print("Boot endpoint order:", " -> ".join(state["order"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
