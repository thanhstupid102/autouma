"""Capture EVERY umamusume API request the REAL game client sends (full decoded
payload) to a JSONL file, so we can compare the official client's friend-parent
rental flow against the bot's.

Usage:
    1. Launch Umamusume (UmamusumePrettyDerby.exe), reach the home screen.
    2. Make sure the bot dashboard/server (main.py) is NOT running.
    3. Run:  python scripts/capture_rental.py
    4. In game, do the repro:
         - start a career, BORROW friend X as the parent, begin the career
         - abandon/give up that career
         - start ANOTHER career and BORROW THE SAME friend X again
    5. Ctrl+C to stop.
Output: uma_runtime/rental_capture_<timestamp>.jsonl  (one JSON record per request)

Reuses main.py's exact TLS hook + wire parser, so it sees the authenticated POST
bodies (the requests carrying auth_key), request side only (no responses).
"""
import sys
import pathlib
import time
import json

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida

from uma_api.crypto import unpack_request
from core.settings import Settings


PROCESS_NAME = Settings.APP_PROCESS_NAME
JS_CODE = Settings.JS_UMA_NETWORK_HOOKS.read_text(encoding="utf-8")
NOISE = {"tool/start_session"}  # heartbeat-ish; skip
OUT = ROOT / "uma_runtime" / f"rental_capture_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"


def main():
    print(f"Attaching to {PROCESS_NAME} ...  output -> {OUT}", flush=True)
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
    n = {"c": 0}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        p = message.get("payload") or {}
        if p.get("type") != "creds":
            return
        ep = p.get("endpoint", "")
        if ep in NOISE:
            return
        udid = p.get("udid") or ""
        body = p.get("body") or ""
        try:
            wire = unpack_request(body, udid)
        except Exception as exc:
            print(f"[{ep}] decode failed: {exc}", flush=True)
            return
        rec = {"ts": time.time(), "endpoint": ep, "payload": wire}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        n["c"] += 1
        mark = ""
        if ep == "single_mode_free/start":
            sc = wire.get("start_chara") or {}
            r = sc.get("rental_succession_trained_chara") or {}
            mark = (f"   <<< START  rental={r.get('viewer_id')}:{r.get('trained_chara_id')}"
                    f"  p1={sc.get('succession_trained_chara_id_1')}"
                    f"  p2={sc.get('succession_trained_chara_id_2')}")
        print(f"[{n['c']:3}] {ep}{mark}", flush=True)

    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()
        print("Hook loaded. Do the repro in-game now. Ctrl+C to stop.", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\nStopped. {n['c']} requests captured -> {OUT}", flush=True)
    finally:
        try:
            session.detach()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
