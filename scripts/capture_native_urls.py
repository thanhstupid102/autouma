r"""Capture the game's resource root-manifest URL through native HTTP APIs.

This attaches Frida to ``UmamusumePrettyDerby.exe``, loads the native-only URL
hook, and records de-duplicated resource-looking URLs in
``uma_runtime/native_urls.jsonl``. It waits for the game to launch and keeps
capturing until Ctrl-C; it never launches the game itself.

Run steps:
    1. Close the game.
    2. Rename ``%USERPROFILE%\AppData\LocalLow\Cygames\Umamusume\meta`` out
       of the way to force a manifest re-fetch.
    3. Run ``python scripts/capture_native_urls.py``.
    4. Launch the game to TITLE only (do not log in; no re-auth is needed).
    5. Watch for a full URL containing ``root.manifest.bsv.lz4?r=``.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
from core.settings import Settings  # noqa: E402


HOOK_PATH = Settings.JS_NATIVE_HTTP_URLS_HOOKS
OUT_PATH = ROOT / "uma_runtime" / "native_urls.jsonl"
PROCESS_NAME = "UmamusumePrettyDerby.exe"
ROOT_MANIFEST_NAME = "root.manifest.bsv.lz4"


def _print_run_steps():
    print("Run steps:", flush=True)
    print("  1. Close the game.", flush=True)
    print("  2. In PowerShell, move the cached meta directory aside:", flush=True)
    print(
        "     $metaPath = Join-Path $env:USERPROFILE "
        "'AppData\\LocalLow\\Cygames\\Umamusume\\meta'",
        flush=True,
    )
    print(
        "     Rename-Item -LiteralPath $metaPath -NewName "
        "('meta.native-url-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))",
        flush=True,
    )
    print("  3. Run: python scripts/capture_native_urls.py", flush=True)
    print(
        "  4. Launch the game to TITLE only (do not log in; no re-auth is needed).",
        flush=True,
    )
    print(
        "  5. Watch for a full URL containing root.manifest.bsv.lz4?r=",
        flush=True,
    )
    print(flush=True)


def _display_value(url, host, path):
    if url:
        return url
    if host and path:
        return f"host={host} path={path}"
    if host:
        return f"host={host}"
    return f"path={path}"


def main():
    _print_run_steps()

    try:
        js_code = HOOK_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Could not read hook {HOOK_PATH}: {exc}", flush=True)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("", encoding="utf-8")

    lock = threading.Lock()
    seen = set()
    apis = set()
    root_urls = set()

    def on_message(message, data):
        if message.get("type") == "error":
            detail = message.get("description") or message.get("stack") or message
            print(f"Frida error: {detail}", flush=True)
            return

        payload = message.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("type") != "http":
            return

        api = str(payload.get("api") or "unknown")
        url = str(payload.get("url") or "")
        host = str(payload.get("host") or "")
        path = str(payload.get("path") or "")
        display = _display_value(url, host, path)
        identity = url or "\x00".join((host, path))
        if not identity:
            return

        with lock:
            if identity in seen:
                return
            seen.add(identity)
            apis.add(api)
            if ROOT_MANIFEST_NAME in (url + " " + path).lower():
                root_urls.add(url or display)
            record = {
                "type": "http",
                "api": api,
                "url": url,
                "host": host,
                "path": path,
                "module": str(payload.get("module") or ""),
                "port": payload.get("port"),
                "captured_at": time.time(),
            }
            with OUT_PATH.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"[{api}] {display}", flush=True)

    session = None
    exit_code = 0
    try:
        print(f"Waiting to attach to {PROCESS_NAME} ...", flush=True)
        while session is None:
            try:
                session = frida.attach(PROCESS_NAME)
            except frida.ProcessNotFoundError:
                time.sleep(0.5)

        print("Attached. Loading native HTTP hooks ...", flush=True)
        script = session.create_script(js_code)
        script.on("message", on_message)
        script.load()
        print("Capturing resource-related URLs (Ctrl-C to stop).", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nCapture interrupted.", flush=True)
    except Exception as exc:
        print(f"Capture failed: {exc}", flush=True)
        exit_code = 1
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass

    with lock:
        captured_count = len(seen)
        captured_apis = sorted(apis)
        captured_roots = sorted(root_urls)

    print(f"\nCaptured {captured_count} unique value(s) -> {OUT_PATH}", flush=True)
    print(
        "HTTP APIs observed: " + (", ".join(captured_apis) if captured_apis else "none"),
        flush=True,
    )
    if captured_roots:
        print("Root-manifest URL(s):", flush=True)
        for root_url in captured_roots:
            print(f"  - {root_url}", flush=True)
    else:
        print("No root.manifest.bsv.lz4?r= URL was captured.", flush=True)
    if not captured_apis:
        print(
            "If no native HTTP API fires during the forced re-fetch, the downloader "
            "uses a statically-linked TLS library; use mitmproxy as the fallback.",
            flush=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
