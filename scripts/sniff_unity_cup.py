"""Capture a manual Unity Cup run from the live game.

Usage:
  1. Launch Umamusume and reach Home.
  2. Run: python scripts/sniff_unity_cup.py
  3. Start Unity Cup manually and play one run.
  4. Ctrl+C after finish.

Writes sanitized request JSONL to uma_runtime/captures/.
Use --responses only after request-only capture works.
Default captures every endpoint except noise; Unity Cup may not use single_mode_free/*.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections import deque

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import frida  # noqa: E402
import sniff_endpoint as base  # noqa: E402


DEFAULT_FILTERS = ()
NOISE = {"tool/start_session"}
BOILERPLATE = {
    "viewer_id",
    "device",
    "device_id",
    "device_name",
    "graphics_device_name",
    "ip_address",
    "platform_os_version",
    "carrier",
    "keychain",
    "locale",
    "button_info",
    "dmm_viewer_id",
    "dmm_onetime_token",
    "timezone_offset",
    "steam_id",
    "steam_session_ticket",
}


def sanitize(value, depth=0, *, max_depth=9, dict_limit=120, list_limit=40, path=""):
    if depth > max_depth:
        return "<max-depth>"
    if isinstance(value, dict):
        out = {}
        for idx, (key, child) in enumerate(value.items()):
            if idx >= dict_limit:
                out["<truncated_keys>"] = len(value) - dict_limit
                break
            skey = str(key)
            if base.is_sensitive_key(skey):
                out[skey] = "<redacted>"
                continue
            child_limit = 80 if skey in {"command_info_array", "unchecked_event_array"} else list_limit
            child_path = f"{path}.{skey}" if path else skey
            out[skey] = sanitize(
                child,
                depth + 1,
                max_depth=max_depth,
                dict_limit=dict_limit,
                list_limit=child_limit,
                path=child_path,
            )
        return out
    if isinstance(value, list):
        out = [
            sanitize(
                child,
                depth + 1,
                max_depth=max_depth,
                dict_limit=dict_limit,
                list_limit=list_limit,
                path=f"{path}[{idx}]",
            )
            for idx, child in enumerate(value[:list_limit])
        ]
        if len(value) > list_limit:
            out.append({"<truncated_items>": len(value) - list_limit})
        return out
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str) and len(value) > 512:
        return value[:512] + f"...<truncated:{len(value) - 512}>"
    return value


def meaningful_request(wire):
    if not isinstance(wire, dict):
        return sanitize(wire)
    return {
        key: sanitize(value, list_limit=120)
        for key, value in wire.items()
        if key not in BOILERPLATE and not base.is_sensitive_key(key)
    }


def command_summary(command):
    if not isinstance(command, dict):
        return sanitize(command)
    keep = (
        "command_type",
        "command_id",
        "command_group_id",
        "is_enable",
        "failure_rate",
        "gain_speed",
        "gain_stamina",
        "gain_power",
        "gain_guts",
        "gain_wiz",
        "gain_skill_point",
        "vital",
        "motivation",
    )
    return {key: sanitize(command.get(key)) for key in keep if key in command}


def response_summary(wire):
    if not isinstance(wire, dict):
        return {"decoded": sanitize(wire)}
    headers = wire.get("data_headers") or {}
    data = wire.get("data") or {}
    summary = {
        "response_code": wire.get("response_code"),
        "result_code": headers.get("result_code") if isinstance(headers, dict) else None,
        "data_keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__,
    }
    if not isinstance(data, dict):
        return summary

    chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
    if isinstance(chara, dict) and chara:
        keep = (
            "scenario_id",
            "turn",
            "card_id",
            "speed",
            "stamina",
            "power",
            "guts",
            "wiz",
            "skill_point",
            "vital",
            "max_vital",
            "motivation",
            "fans",
        )
        summary["chara"] = {key: sanitize(chara.get(key)) for key in keep if key in chara}

    home = data.get("home_info") or {}
    commands = home.get("command_info_array") if isinstance(home, dict) else None
    if isinstance(commands, list):
        summary["commands"] = [command_summary(command) for command in commands[:80]]

    for key in (
        "unchecked_event_array",
        "single_mode_load_common",
        "single_mode_finish_common",
        "race_start_info",
        "race_result_info",
        "team_data_set",
    ):
        if key in data:
            summary[key] = sanitize(data[key], dict_limit=80, list_limit=20)
    return summary


def write_event(handle, event):
    handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    handle.flush()


def patch_js_wide_requests(js):
    hook_start = js.find("  function hookTls() {")
    hook_end = js.find("  var tlsDone = false;", hook_start)
    if hook_start < 0 or hook_end < 0:
        return js
    return js[:hook_start] + r'''
  function bytesToString(ptr, len) {
    var bytes = ptr.readByteArray(len);
    var u8 = new Uint8Array(bytes);
    var s = '';
    for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
    return s;
  }

  function hookTls() {
    var ga = Process.findModuleByName('GameAssembly.dll');
    if (!ga) return false;
    var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
    if (!installFn) return false;
    var rb = new Uint8Array(installFn.readByteArray(16));
    var realFn = installFn;
    if (rb[0] === 0xe9) {
      var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
      if (off > 0x7fffffff) off -= 0x100000000;
      realFn = installFn.add(5 + off);
      rb = new Uint8Array(realFn.readByteArray(16));
    }
    var globalPtr = null;
    if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
      var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
      if (disp > 0x7fffffff) disp -= 0x100000000;
      globalPtr = realFn.add(7 + disp);
    }
    if (!globalPtr) return false;
    var iface = globalPtr.readPointer();
    if (!iface || iface.isNull()) return false;
    var hookedTls = 0;
    function tryHook(addr, offLabel) {
      if (!addr || addr.isNull()) return;
      var key = 'tls_' + addr.toString();
      if (attached[key]) return;
      try {
        Interceptor.attach(addr, {
          onEnter: function(args) {
            try {
              var len = args[2].toInt32();
              if (len <= 0 || len > 1048576 || args[1].isNull()) return;
              var s = bytesToString(args[1], len);
              if (s.indexOf('/umamusume/') < 0 && s.indexOf('POST ') < 0) return;
              parseChunk(args[0].toString() + ':' + offLabel, s);
            } catch (e) {}
          }
        });
        attached[key] = true;
        hookedTls++;
      } catch (e) {}
    }
    for (var off = 0; off <= 0x220; off += 8) {
      try {
        tryHook(iface.add(off).readPointer(), off);
      } catch (e) {}
    }
    return hookedTls > 0;
  }

''' + js[hook_end:]


def _self_check():
    sample = {
        "viewer_id": 1,
        "device_id": "secret",
        "ok": {"command_info_array": list(range(45)), "name": "x"},
    }
    got = sanitize(sample, list_limit=2)
    assert got["viewer_id"] == "<redacted>"
    assert got["device_id"] == "<redacted>"
    assert got["ok"]["command_info_array"] == list(range(45))
    req = meaningful_request({"viewer_id": 1, "current_turn": 2})
    assert req == {"current_turn": 2}
    print("self-check ok")


def main():
    parser = argparse.ArgumentParser(description="Sniff a manual Unity Cup run from live Umamusume traffic.")
    parser.add_argument("filters", nargs="*", help="endpoint substring filters; default: all endpoints except noise")
    parser.add_argument("--all", action="store_true", help="capture every endpoint except noise (default)")
    parser.add_argument("--legacy-hook", action="store_true", help="use older narrow TLS hook")
    parser.add_argument("--responses", action="store_true", help="also capture/decode responses; slower and more invasive")
    parser.add_argument("--summary-only", action="store_true", help="do not store sanitized full decoded responses")
    parser.add_argument("--out", type=pathlib.Path, help="output JSONL path")
    parser.add_argument("--self-check", action="store_true", help="run local asserts and exit")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    filters = [] if args.all else [item.lower() for item in (args.filters or DEFAULT_FILTERS)]
    out_path = args.out or ROOT / "uma_runtime" / "captures" / f"unity_cup_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def matches(endpoint):
        if endpoint in NOISE:
            return False
        return not filters or any(item in endpoint.lower() for item in filters)

    print(f"Attaching to {base.PROCESS_NAME} ...", flush=True)
    print(f"Output: {out_path}", flush=True)
    if filters:
        print(f"Filters: {filters}", flush=True)
    else:
        print("Filters: <all endpoints except noise>", flush=True)
    print(f"Responses: {'on' if args.responses else 'off'}", flush=True)
    print("In game: start Unity Cup manually, play one run, Ctrl+C after finish.", flush=True)

    session = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            session = frida.attach(base.PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {base.PROCESS_NAME} not found within 60s.", flush=True)
        return 1

    pending = deque(maxlen=500)
    seen = {"request_id": 0, "saved_requests": 0, "saved_responses": 0, "decode_errors": 0}

    with out_path.open("w", encoding="utf-8") as handle:

        def on_message(message, data):
            if message.get("type") == "error":
                print(f"Frida error: {message.get('description')}", flush=True)
                return
            payload = message.get("payload") or {}
            if payload.get("type") == "response" and args.responses:
                if not pending:
                    return
                req = pending.popleft()
                endpoint = req["endpoint"]
                if not matches(endpoint):
                    return
                payload = dict(payload)
                payload["endpoint"] = endpoint
                payload["udid"] = req["udid"]
                try:
                    wire = base.decode_response_wire(payload)
                except Exception as exc:
                    seen["decode_errors"] += 1
                    hints = base.header_hints(payload.get("headers") or "")
                    print(f"[{endpoint}] response decode failed: {exc}; {hints}", flush=True)
                    return
                event = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "kind": "response",
                    "request_id": req["request_id"],
                    "endpoint": endpoint,
                    "summary": response_summary(wire),
                }
                if not args.summary_only:
                    event["response"] = sanitize(wire, dict_limit=140, list_limit=40)
                write_event(handle, event)
                seen["saved_responses"] += 1
                rc = event["summary"].get("result_code")
                print(f"<< #{req['request_id']} RESPONSE {endpoint} result_code={rc}", flush=True)
                return

            if payload.get("type") != "creds":
                return
            endpoint = payload.get("endpoint", "")
            udid = payload.get("udid") or ""
            body = payload.get("body") or ""
            try:
                wire = base.unpack_request(body, udid)
            except Exception as exc:
                seen["decode_errors"] += 1
                print(f"[{endpoint}] request decode failed: {exc}", flush=True)
                return
            seen["request_id"] += 1
            request_id = seen["request_id"]
            pending.append({"request_id": request_id, "endpoint": endpoint, "udid": udid})
            if not matches(endpoint):
                return
            event = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "kind": "request",
                "request_id": request_id,
                "endpoint": endpoint,
                "app_ver": payload.get("app_ver"),
                "res_ver": payload.get("res_ver"),
                "request": meaningful_request(wire),
            }
            write_event(handle, event)
            seen["saved_requests"] += 1
            print(f"\n>> #{request_id} REQUEST {endpoint}", flush=True)
            print(json.dumps(event["request"], ensure_ascii=False, indent=2, default=str)[:5000], flush=True)

        try:
            js_code = base.patch_js_for_responses(base.JS_CODE) if args.responses else base.JS_CODE
            if not args.legacy_hook and not args.responses:
                js_code = patch_js_wide_requests(js_code)
            script = session.create_script(js_code)
            script.on("message", on_message)
            script.load()
            print("Hook loaded. Waiting for traffic.", flush=True)
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopped by user.", flush=True)
        finally:
            try:
                session.detach()
            except Exception:
                pass

    print(
        f"Saved {seen['saved_requests']} request(s), {seen['saved_responses']} response(s), "
        f"{seen['decode_errors']} decode error(s) -> {out_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
