"""Capture the title-screen manifest and master resource URLs with Frida.

Run this one-time phase-1 capture while the game process is open, then return
to the title screen so its resource-version check fetches the manifest and
master.mdb.lz4. Those fetches happen at title before account login, so the user
does not need to log in or risk re-authentication. Requests are recorded in
uma_runtime/resource_urls.jsonl for scripts/probe_master_download.py.

Usage:
    python scripts/capture_resource_urls.py
"""
import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
from core.settings import Settings  # noqa: E402


HOOK_PATH = Settings.JS_UMA_RESOURCE_URLS_HOOKS
OUT_PATH = ROOT / "uma_runtime" / "resource_urls.jsonl"
PROCESS_NAME = "UmamusumePrettyDerby.exe"
ATTACH_TIMEOUT_SEC = 120


def _print_summary(hosts, manifest_urls, master_urls):
    print("\nResource URL capture summary:", flush=True)
    print("Distinct resource hosts:", flush=True)
    if hosts:
        for host in sorted(hosts):
            print(f"  - {host}", flush=True)
    else:
        print("  (none)", flush=True)
    print("Manifest-looking URLs:", flush=True)
    if manifest_urls:
        for url in sorted(manifest_urls):
            print(f"  - {url}", flush=True)
    else:
        print("  (none)", flush=True)
    print("Master/.lz4-looking URLs:", flush=True)
    if master_urls:
        for url in sorted(master_urls):
            print(f"  - {url}", flush=True)
    else:
        print("  (none)", flush=True)
    print(f"Capture log: {OUT_PATH}", flush=True)


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("", encoding="utf-8")
    js_code = HOOK_PATH.read_text(encoding="utf-8")

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

    state_lock = threading.Lock()
    complete = threading.Event()
    seen_urls = set()
    hosts = set()
    manifest_urls = set()
    master_urls = set()

    def record(rec):
        with open(OUT_PATH, "a", encoding="utf-8") as output:
            output.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("type") != "resource_req":
            return
        method = str(payload.get("method") or "")
        host = str(payload.get("host") or "")
        path = str(payload.get("path") or "")
        url = str(payload.get("url") or "")
        rec = {
            "method": method,
            "host": host,
            "path": path,
            "url": url,
            "ts": time.time(),
        }
        lower_url = url.lower()
        with state_lock:
            record(rec)
            is_new = bool(url) and url not in seen_urls
            if is_new:
                seen_urls.add(url)
                if host:
                    hosts.add(host)
                if "manifest" in lower_url:
                    manifest_urls.add(url)
                if "master" in lower_url or ".lz4" in lower_url:
                    master_urls.add(url)
                print(f"{method.upper():4} {url}", flush=True)
            if manifest_urls and master_urls:
                complete.set()

    try:
        script = session.create_script(js_code)
        script.on("message", on_message)
        script.load()
        print(
            "Attach done. In the game, go Menu -> Return to Title (or restart to title). "
            "The title/boot performs the resource version check + manifest/master download. "
            "Watch this log.",
            flush=True,
        )
        print("Capturing resource URLs (Ctrl-C to stop).", flush=True)
        while not complete.wait(0.25):
            pass
        print("Manifest and master/.lz4-looking URLs seen; capture complete.", flush=True)
    except KeyboardInterrupt:
        print("\nCapture interrupted.", flush=True)
    except Exception as exc:
        print(f"Capture failed: {exc}", flush=True)
        return 1
    finally:
        try:
            session.detach()
        except Exception:
            pass

    with state_lock:
        summary = (set(hosts), set(manifest_urls), set(master_urls))
    _print_summary(*summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
