"""Full session traffic recorder -- every request AND response, plaintext.

Attaches to the running game and hooks the IL2CPP HTTP helper
(Gallop.HttpHelper.CompressRequest / DecompressResponse, plus
Cute.Http.WWWRequest.Post for URLs) via
Settings.JS_UMA_FULL_TRAFFIC_HOOKS. That
taps the msgpack BEFORE encryption / AFTER decryption, so we capture BOTH
directions across the WHOLE session (not just career endpoints) with no AES
key needed. Output is one raw.jsonl compatible with
tools/solve_rankpoint_from_icarus.py:

    {"seq": int, "ts": float, "dir": "req"|"resp", "path": str|null,
     "scenario_id": int|null, "data": <decoded msgpack>}

USAGE:
    1. Stop the bot server (main.py) and any other Frida script -- only one
       process may attach to the game at a time.
    2. Launch Umamusume for real and reach Home.
    3. python scripts/record_traffic.py
       (optional: python scripts/record_traffic.py --out some/dir)
    4. Play. Every API call is decoded and appended to
       uma_runtime/traffic/<timestamp>/raw.jsonl. Ctrl+C to stop.

Notes:
    - Frida delivers packets on its own thread; we hand each straight to a queue
      and decode on one consumer thread so the hook can never back-pressure /
      drop packets and req/resp order is preserved.
    - Decode tries raw msgpack, a 4-byte length-prefixed request header, then
      zlib/gzip/deflate fallbacks (a game update can start compressing at these
      hook points).
"""
import sys
import json
import time
import queue
import zlib
import gzip
import argparse
import threading
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
import msgpack  # noqa: E402
from core.settings import Settings  # noqa: E402

PROCESS_NAME = Settings.APP_PROCESS_NAME
PACKET_GRACE_SECONDS = 10.0
HOOK_PATHS = (
    Settings.JS_IL2CPP_THREAD_GUARD_HOOKS,
    Settings.JS_UMA_FULL_TRAFFIC_HOOKS,
)


def _load_hook_source():
    try:
        sources = [path.read_text(encoding="utf-8") for path in HOOK_PATHS]
    except OSError:
        return ""
    if not all(sources):
        return ""
    return "\n".join(sources)


JS_CODE = _load_hook_source()


def _warn_if_no_packet(packet_received, cancelled, grace_seconds=PACKET_GRACE_SECONDS):
    deadline = time.monotonic() + grace_seconds
    while not packet_received.is_set() and not cancelled.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        cancelled.wait(min(remaining, 0.1))
    if not packet_received.is_set() and not cancelled.is_set():
        print(
            f"Warning: no traffic packet arrived within {grace_seconds:g}s after "
            "the hook loaded; the hook may not have bound. Check [hook] diagnostics "
            "and generate game traffic before relying on this capture.",
            flush=True,
        )


def _unpack(b):
    try:
        return msgpack.unpackb(b, raw=False, strict_map_key=False)
    except msgpack.ExtraData as e:
        # Pooled/over-allocated game buffers carry trailing bytes past a complete
        # object. Trust it only if the top level is a real payload (map/array);
        # a bare scalar means a compressed/garbage leading byte was misread.
        if isinstance(e.unpacked, (dict, list)):
            return e.unpacked
        return None
    except Exception:
        return None


def decode_msgpack(data, is_request=False):
    raw = bytes(data)

    def attempt(b):
        r = _unpack(b)
        if r is not None:
            return r
        if is_request and len(b) >= 4:
            hs = 4 + int.from_bytes(b[:4], "little")
            if 0 < hs < len(b):
                return _unpack(b[hs:])
        return None

    r = attempt(raw)
    if r is not None:
        return r
    for decomp in (lambda x: zlib.decompress(x),
                   lambda x: gzip.decompress(x),
                   lambda x: zlib.decompress(x, -15),
                   lambda x: zlib.decompress(x, 47)):
        try:
            b = decomp(raw)
        except Exception:
            continue
        r = attempt(b)
        if r is not None:
            return r
    return None


def extract_scenario_id(decoded):
    if not isinstance(decoded, dict):
        return None
    for key in ("chara_info", "single_mode_chara_light", "single_mode_chara"):
        v = decoded.get(key)
        if isinstance(v, dict) and v.get("scenario_id"):
            try:
                return int(v.get("scenario_id"))
            except (TypeError, ValueError):
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="output dir (default uma_runtime/traffic/<ts>)")
    ap.add_argument("--attach-timeout", type=int, default=120)
    args = ap.parse_args()

    if not JS_CODE:
        print("Error: IL2CPP guard or uma_full_traffic.js not found or empty.", flush=True)
        return 1

    out_dir = pathlib.Path(args.out) if args.out else (
        ROOT / "uma_runtime" / "traffic" / time.strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw.jsonl"
    print(f"Attaching to {PROCESS_NAME} ...", flush=True)

    session = None
    deadline = time.monotonic() + args.attach_timeout
    while time.monotonic() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {PROCESS_NAME} not found within {args.attach_timeout}s. Launch the game first.", flush=True)
        return 1

    raw_queue = queue.Queue()
    counts = {"req": 0, "resp": 0, "fail": 0}
    stop = threading.Event()
    packet_received = threading.Event()
    watchdog_cancelled = threading.Event()
    target_detached = threading.Event()
    intentional_detach = threading.Event()

    def on_detached(reason, crash=None):
        target_detached.set()
        watchdog_cancelled.set()
        if intentional_detach.is_set():
            return
        if str(reason) == "process-terminated":
            print(
                "Error: target process died while Frida was attached "
                "(reason: process-terminated).",
                flush=True,
            )
        else:
            print(f"Error: Frida session detached unexpectedly (reason: {reason}).", flush=True)

    session.on("detached", on_detached)

    def writer():
        seq = 0
        with open(raw_path, "a", encoding="utf-8") as f:
            while not (stop.is_set() and raw_queue.empty()):
                try:
                    t, data, path = raw_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                is_request = (t == "Q")
                decoded = decode_msgpack(data, is_request)
                if decoded is None:
                    counts["fail"] += 1
                    continue
                direction = "req" if is_request else "resp"
                counts[direction] += 1
                seq += 1
                rec = {
                    "seq": seq,
                    "ts": time.time(),
                    "dir": direction,
                    "path": path,
                    "scenario_id": extract_scenario_id(decoded),
                    "data": decoded,
                }
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                f.flush()
                label = path or ("request" if is_request else "response")
                print(f"[{seq:4}] {direction:4} {label}", flush=True)

    writer_thread = threading.Thread(target=writer, name="writer", daemon=True)
    writer_thread.start()

    def on_message(message, data):
        if message.get("type") != "send":
            if message.get("type") == "error":
                print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        t = payload.get("t")
        if t == "log":
            print(f"[hook] {payload.get('msg')}", flush=True)
            return
        if data is None:
            return
        packet_received.set()
        raw_queue.put((t, bytes(data), payload.get("path")))

    script = None
    warning_thread = None
    exit_code = 0
    try:
        script = session.create_script(JS_CODE)
        script.on("message", on_message)
        script.load()
        warning_thread = threading.Thread(
            target=_warn_if_no_packet,
            args=(packet_received, watchdog_cancelled),
            name="packet-watchdog",
            daemon=True,
        )
        warning_thread.start()
        print(f"Recording -> {raw_path}\nPlay the game. Ctrl+C to stop.\n", flush=True)
        while not target_detached.wait(0.5):
            pass
        exit_code = 1
    except KeyboardInterrupt:
        print(f"\nStopping... {counts['req']} req, {counts['resp']} resp, "
              f"{counts['fail']} decode-fail.", flush=True)
    finally:
        watchdog_cancelled.set()
        stop.set()
        if warning_thread is not None:
            warning_thread.join(timeout=1)
        writer_thread.join(timeout=5)
        if script is not None:
            try:
                script.unload()
            except Exception:
                pass
        intentional_detach.set()
        try:
            session.detach()
        except Exception:
            pass
        print(f"Saved -> {raw_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
