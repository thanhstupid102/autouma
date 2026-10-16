"""Capture real-game group outing exec_command ids for Sirius/Throne schedule.

Usage:
    1. Launch Umamusume, enter target career, reach turn 51/58/59.
    2. Run:  python scripts/capture_outing_ids.py
    3. In game, manually click the available group outing/date.
    4. Read printed select_id and JSONL output.

Output: uma_runtime/outing_capture_<timestamp>.jsonl
"""
import json
import pathlib
import sys
import time

import frida

from uma_api.crypto import unpack_request
from core.settings import Settings


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


PROCESS_NAME = Settings.APP_PROCESS_NAME
JS_CODE = Settings.JS_UMA_NETWORK_HOOKS.read_text(encoding="utf-8")
GROUP_OUTING_COMMAND_ID = 390
OUT = ROOT / "uma_runtime" / f"outing_capture_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"


def is_group_outing_exec(ep, wire):
    if ep != "single_mode_free/exec_command":
        return False
    command_type = int(wire.get("command_type") or 0)
    command_id = int(wire.get("command_id") or 0)
    command_group_id = int(wire.get("command_group_id") or 0)
    return command_type == 3 and GROUP_OUTING_COMMAND_ID in {command_id, command_group_id}


def main():
    print(f"Attaching to {PROCESS_NAME} ... output={OUT}", flush=True)
    session = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {PROCESS_NAME} not found within 120s. Launch the game first.", flush=True)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = {"n": 0}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if payload.get("type") != "creds":
            return
        ep = payload.get("endpoint", "")
        try:
            wire = unpack_request(payload.get("body") or "", payload.get("udid") or "")
        except Exception as exc:
            print(f"[{ep}] decode failed: {exc}", flush=True)
            return
        if not is_group_outing_exec(ep, wire):
            return
        rec = {"ts": time.time(), "endpoint": ep, "payload": wire}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        count["n"] += 1
        print(
            "OUTING_CAPTURE "
            f"turn={wire.get('current_turn')} "
            f"command_type={wire.get('command_type')} "
            f"command_id={wire.get('command_id')} "
            f"command_group_id={wire.get('command_group_id')} "
            f"select_id={wire.get('select_id')} "
            f"current_vital={wire.get('current_vital')}",
            flush=True,
        )

    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()
        print("Hook loaded. Manually click group outing/date in-game. Ctrl+C to stop.", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\nStopped. Captured {count['n']} outing request(s) -> {OUT}", flush=True)
    finally:
        try:
            session.detach()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
