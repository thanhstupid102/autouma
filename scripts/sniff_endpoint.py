"""Standalone Frida sniffer: prints every umamusume API endpoint plus decoded
request payload and sanitized response hints. Use to capture real request/response
shape for manual game actions.

Usage:
    1. Launch Umamusume and reach the home screen.
    2. Run:  python scripts/sniff_endpoint.py
       (optionally filter:  python scripts/sniff_endpoint.py recover item user)
    3. In the game, manually use ONE TP bottle or click the target UI action.
    4. The matching endpoint + payload prints here. Ctrl+C to stop.

It reuses the same TLS hook + wire parser as main.py's auth capture, then patches
only this script's JS copy to emit HTTP responses. Python pairs each response
with the preceding decoded request. Console output is sanitized: do not paste raw
secrets.
"""
import sys
import pathlib
import time
import base64
import json
import gzip
import zlib
from collections import deque

import frida

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Wire layout: b64(<u32 header len> + header + cipher + key[-32:]), where
# cipher is AES-CBC(pad(<u32 payload len> + msgpack)).
from uma_api.crypto import unpack_request  # noqa: E402
from uma_api.client import unpack  # noqa: E402
from core.settings import Settings  # noqa: E402


PROCESS_NAME = Settings.APP_PROCESS_NAME
# Reuse the exact TLS hook + wire parser from main.py so we capture the same
# authenticated POST bodies the auth-capture path sees.
JS_CODE = Settings.JS_UMA_NETWORK_HOOKS.read_text(encoding="utf-8")

# Endpoints that are pure noise while waiting (heartbeat-ish); skip unless the
# user explicitly filters for them.
NOISE = {"tool/start_session"}
SENSITIVE_KEYS = {
    "viewer_id", "owner_viewer_id", "device", "device_id", "device_name",
    "graphics_device_name", "ip_address", "platform_os_version", "carrier",
    "keychain", "locale", "button_info", "dmm_viewer_id", "dmm_onetime_token",
    "timezone_offset", "steam_id", "steam_session_ticket", "auth_key", "sid",
    "udid", "device_token", "refresh_token",
}


def patch_js_for_responses(js):
    """Patch this script's in-memory hook copy to emit HTTP responses too.

    Keep the original request parser untouched; Python pairs responses with the
    already-emitted request messages. This avoids losing requests if the TLS
    read/write callbacks use different connection pointers.
    """
    js = js.replace(
        "var buffers = {};\n    var attached = {};",
        "var buffers = {};\n"
        "    var attached = {};\n"
        "    function b64encBinary(s) {\n"
        "      var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';\n"
        "      var out = '';\n"
        "      for (var i = 0; i < s.length; i += 3) {\n"
        "        var a = s.charCodeAt(i) & 255;\n"
        "        var b = i + 1 < s.length ? (s.charCodeAt(i + 1) & 255) : 0;\n"
        "        var c = i + 2 < s.length ? (s.charCodeAt(i + 2) & 255) : 0;\n"
        "        var n = (a << 16) | (b << 8) | c;\n"
        "        out += chars[(n >> 18) & 63] + chars[(n >> 12) & 63] + (i + 1 < s.length ? chars[(n >> 6) & 63] : '=') + (i + 2 < s.length ? chars[n & 63] : '=');\n"
        "      }\n"
        "      return out;\n"
        "    }",
        1,
    )
    start = js.find("  function parseChunk(key, chunk) {")
    end = js.find("  function hookTls() {", start)
    if start < 0 or end < 0:
        return js
    js = js[:start] + r'''
  function parseResponseHttp(headers, body) {
    send({
      type: 'response',
      headers: headers,
      body_b64: b64encBinary(body)
    });
  }

  function decodeChunked(buf, pos) {
    var out = '';
    var p = pos;
    while (true) {
      var lineEnd = buf.indexOf('\r\n', p);
      if (lineEnd < 0) return null;
      var line = buf.substring(p, lineEnd).split(';')[0].trim();
      var size = parseInt(line, 16);
      if (isNaN(size) || size < 0) return null;
      var dataStart = lineEnd + 2;
      var dataEnd = dataStart + size;
      if (buf.length < dataEnd + 2) return null;
      out += buf.substring(dataStart, dataEnd);
      p = dataEnd + 2;
      if (size === 0) {
        if (buf.substring(p, p + 2) === '\r\n') return { end: p + 2, body: out };
        var trailerEnd = buf.indexOf('\r\n\r\n', p);
        if (trailerEnd < 0) return null;
        return { end: trailerEnd + 4, body: out };
      }
    }
  }

  function responseStart(buf) {
    if (buf.indexOf('HTTP/') === 0) return 0;
    var idx = buf.indexOf('\r\nHTTP/');
    return idx >= 0 ? idx + 2 : -1;
  }

  function parseChunk(connKey, bufferKey, chunk, mode) {
    var buf = (buffers[bufferKey] || '') + chunk;
    if (buf.length > 4194304) buf = buf.substring(buf.length - 2097152);
    while (true) {
      var reqStart = mode === 'req' ? buf.indexOf('POST ') : -1;
      var resStart = mode === 'res' ? responseStart(buf) : -1;
      if (reqStart < 0 && resStart < 0) {
        buffers[bufferKey] = buf.slice(-4096);
        return;
      }
      var start = (reqStart >= 0 && (resStart < 0 || reqStart < resStart)) ? reqStart : resStart;
      var kind = start === reqStart ? 'req' : 'res';
      if (start > 0) buf = buf.substring(start);
      var headerEnd = buf.indexOf('\r\n\r\n');
      if (headerEnd < 0) {
        buffers[bufferKey] = buf;
        return;
      }
      var headers = buf.substring(0, headerEnd);
      var lm = headers.match(/Content-Length:\s*(\d+)/i);
      var isChunked = /Transfer-Encoding:\s*chunked/i.test(headers);
      var total = headerEnd + 4;
      var body = '';
      if (isChunked) {
        var decoded = decodeChunked(buf, headerEnd + 4);
        if (!decoded) {
          buffers[bufferKey] = buf;
          return;
        }
        total = decoded.end;
        body = decoded.body;
      } else if (lm) {
        var length = parseInt(lm[1], 10);
        total = headerEnd + 4 + length;
        if (buf.length < total) {
          buffers[bufferKey] = buf;
          return;
        }
        body = buf.substring(headerEnd + 4, total);
      }
      if (kind === 'req') parseHttp(buf.substring(0, total));
      else parseResponseHttp(headers, body);
      if (buf.length <= total) {
        buffers[bufferKey] = '';
        return;
      }
      buf = buf.substring(total);
    }
  }

''' + js[end:]

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

  function addLen(out, n) {
    try {
      n = n | 0;
      if (n > 0 && n <= 1048576 && out.indexOf(n) < 0) out.push(n);
    } catch (e) {}
  }

  function addPtrLen(out, ptr) {
    try {
      if (!ptr || ptr.isNull()) return;
      addLen(out, ptr.readU32());
      try { addLen(out, ptr.readU64().toNumber()); } catch (e) {}
    } catch (e) {}
  }

  function probeResponses(connKey, bufferKey, argv, retval) {
    var lens = [];
    var bufs = [];
    try { if (retval) addLen(lens, retval.toInt32()); } catch (e) {}
    for (var i = 0; i < argv.length; i++) {
      var p = argv[i];
      try {
        if (p && !p.isNull()) bufs.push({idx: i, ptr: p});
      } catch (e) {}
      try { addLen(lens, p.toInt32()); } catch (e) {}
      addPtrLen(lens, p);
    }
    for (var bi = 0; bi < bufs.length; bi++) {
      for (var li = 0; li < lens.length; li++) {
        try {
          var n = lens[li];
          if (n <= 0 || n > 1048576) continue;
          var s = bytesToString(bufs[bi].ptr, n);
          if (responseStart(s) < 0) continue;
          parseChunk(connKey, bufferKey + ':arg' + bufs[bi].idx, s, 'res');
        } catch (e) {}
      }
    }
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
            this.connKey = args[0].toString();
            this.bufPtr = args[1];
            this.requestedLen = args[2].toInt32();
            this.argv = [args[0], args[1], args[2], args[3], args[4], args[5]];
            this.off = offLabel;
            probeResponses(this.connKey, this.connKey + ':res:' + offLabel + ':enter', this.argv, null);
            if (this.requestedLen <= 0 || this.requestedLen > 1048576 || this.bufPtr.isNull()) return;
            try {
              parseChunk(this.connKey, this.connKey + ':req', bytesToString(this.bufPtr, this.requestedLen), 'req');
            } catch (e) {}
          },
          onLeave: function(retval) {
            if (!this.bufPtr || this.bufPtr.isNull()) return;
            probeResponses(this.connKey, this.connKey + ':res:' + this.off + ':leave', this.argv || [], retval);
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


def decode_http_response_body(raw, headers):
    headers_text = str(headers or "")
    raw = maybe_dechunk_http_body(raw)
    enc = ""
    for line in headers_text.splitlines():
        if line.lower().startswith("content-encoding:"):
            enc = line.split(":", 1)[1].strip().lower()
            break
    if "gzip" in enc:
        return gzip.decompress(raw)
    if "deflate" in enc:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def maybe_dechunk_http_body(raw):
    """Best-effort fallback if chunk framing leaked through the JS parser."""
    out = bytearray()
    pos = 0
    try:
        while True:
            line_end = raw.find(b"\r\n", pos)
            if line_end < 0:
                return raw
            line = raw[pos:line_end].split(b";", 1)[0].strip()
            if not line:
                return raw
            size = int(line, 16)
            data_start = line_end + 2
            data_end = data_start + size
            if len(raw) < data_end + 2:
                return raw
            out += raw[data_start:data_end]
            pos = data_end + 2
            if size == 0:
                return bytes(out)
    except Exception:
        return raw


def header_hints(headers):
    keep = ("content-length", "transfer-encoding", "content-encoding")
    out = []
    for line in str(headers or "").splitlines():
        if any(line.lower().startswith(k + ":") for k in keep):
            out.append(line.strip())
    return "; ".join(out)


def decode_response_wire(payload):
    udid = payload.get("udid") or ""
    if len(udid.replace("-", "")) != 32:
        raise ValueError("response has no paired request/udid yet")
    headers = payload.get("headers") or ""
    if payload.get("body_b64"):
        raw = base64.b64decode(payload.get("body_b64"))
        raw = decode_http_response_body(raw, headers)
        body = raw.decode("ascii").strip()
    else:
        # Backward-compatible fallback for the older JS patch.
        body = (payload.get("body") or "").strip()
    return unpack(body, udid)


def is_sensitive_key(key):
    key = str(key or "").lower()
    return key in SENSITIVE_KEYS or key.endswith("viewer_id") or key.endswith("sid")


def compact_value(value, depth=0):
    if depth > 6:
        return "<max-depth>"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            if is_sensitive_key(k):
                out[k] = "<redacted>"
            else:
                out[k] = compact_value(v, depth + 1)
        if len(value) > 40:
            out["<truncated_keys>"] = len(value) - 40
        return out
    if isinstance(value, list):
        limit = 40 if all(not isinstance(item, (dict, list)) for item in value) else 6
        out = [compact_value(item, depth + 1) for item in value[:limit]]
        if len(value) > limit:
            out.append({"<truncated_items>": len(value) - limit})
        return out
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "...<truncated>"
    return value


def collect_interesting(value, path="data", out=None):
    if out is None:
        out = []
    if len(out) >= 80:
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            if is_sensitive_key(k):
                continue
            key = str(k).lower()
            p = f"{path}.{k}"
            if (
                "factor" in key
                or "lottery" in key
                or key in {"resume_factor_select", "tp_info", "coin_info"}
            ):
                out.append({"path": p, "value": compact_value(v)})
            elif isinstance(v, (dict, list)):
                collect_interesting(v, p, out)
    elif isinstance(value, list):
        for i, item in enumerate(value[:6]):
            collect_interesting(item, f"{path}[{i}]", out)
    return out


def clean_ints(values):
    out = []
    for value in values or []:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item:
            out.append(item)
    return out


def factor_ids_in(value):
    if isinstance(value, dict):
        ids = clean_ints(value.get("factor_id_array"))
        if ids:
            return ids
        infos = value.get("factor_info_array")
        if isinstance(infos, list):
            return clean_ints(item.get("factor_id") for item in infos if isinstance(item, dict))
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value[:20]):
        return clean_ints(item.get("factor_id") for item in value if isinstance(item, dict))
    return []


def collect_factor_candidates(value, path="data", out=None):
    if out is None:
        out = []
    if len(out) >= 80:
        return out
    ids = factor_ids_in(value)
    if ids:
        out.append({"path": path, "factor_ids": ids[:80], "count": len(ids)})
    if isinstance(value, dict):
        for key, child in value.items():
            if is_sensitive_key(key):
                continue
            collect_factor_candidates(child, f"{path}.{key}", out)
    elif isinstance(value, list):
        for i, child in enumerate(value[:20]):
            collect_factor_candidates(child, f"{path}[{i}]", out)
    return out


def response_hints(wire):
    if not isinstance(wire, dict):
        return {"decoded": compact_value(wire)}
    data = wire.get("data") or {}
    headers = wire.get("data_headers") or {}
    hints = {
        "response_code": wire.get("response_code"),
        "result_code": headers.get("result_code") if isinstance(headers, dict) else None,
        "data_keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__,
        "factor_candidates": collect_factor_candidates(data),
        "interesting": collect_interesting(data),
    }
    return hints


def main():
    capture_responses = "--no-responses" not in sys.argv[1:]
    filters = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]

    def matches(ep):
        if not filters:
            return True
        return any(f in ep.lower() for f in filters)

    print(f"Attaching to {PROCESS_NAME} ... (use a TP bottle in-game now)", flush=True)
    if not capture_responses:
        print("Response capture disabled; request-only mode.", flush=True)
    if filters:
        print(f"Filtering endpoints containing: {filters}", flush=True)

    session = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1.0)
    if not session:
        print(f"Error: {PROCESS_NAME} not found within 60s.", flush=True)
        return 1

    pending = deque(maxlen=50)
    seen = {"count": 0, "responses": 0, "unpaired_responses": 0}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"Frida error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload") or {}
        if payload.get("type") == "response":
            if not pending:
                seen["unpaired_responses"] += 1
                return
            req = pending.popleft()
            payload = dict(payload)
            payload["endpoint"] = req.get("endpoint") or ""
            payload["udid"] = req.get("udid") or ""
            ep = payload.get("endpoint", "")
            if ep in NOISE or not matches(ep):
                return
            try:
                wire = decode_response_wire(payload)
            except Exception as exc:
                body_len = len(payload.get("body_b64") or payload.get("body") or "")
                hints = header_hints(payload.get("headers") or "")
                suffix = f", headers={hints}" if hints else ""
                print(f"[{ep or '<unpaired>'}] response decode failed: {exc} (body_len={body_len}{suffix})", flush=True)
                return
            seen["responses"] += 1
            print("\n<<<<<<<<<<<<<<<< RESPONSE <<<<<<<<<<<<<<", flush=True)
            print(f"ENDPOINT: {ep}", flush=True)
            print("RESPONSE HINTS (sanitized):", flush=True)
            print(json.dumps(response_hints(wire), ensure_ascii=False, indent=2, default=str), flush=True)
            print("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<", flush=True)
            return

        if payload.get("type") != "creds":
            return
        ep = payload.get("endpoint", "")
        udid = payload.get("udid") or ""
        body = payload.get("body") or ""
        try:
            wire = unpack_request(body, udid)
        except Exception as exc:
            print(f"[{ep}] (decode failed: {exc})", flush=True)
            return
        pending.append({"endpoint": ep, "udid": udid})
        if ep in NOISE or not matches(ep):
            return
        # Strip the device-fingerprint boilerplate so the meaningful params stand out.
        boilerplate = {
            "viewer_id", "device", "device_id", "device_name", "graphics_device_name",
            "ip_address", "platform_os_version", "carrier", "keychain", "locale",
            "button_info", "dmm_viewer_id", "dmm_onetime_token", "timezone_offset",
        }
        meaningful = {
            k: compact_value(v)
            for k, v in wire.items()
            if k not in boilerplate and not is_sensitive_key(k)
        }
        seen["count"] += 1
        print("\n========================================", flush=True)
        print(f"ENDPOINT: {ep}", flush=True)
        print("PAYLOAD (meaningful keys):", flush=True)
        print(json.dumps(meaningful, ensure_ascii=False, indent=2, default=str), flush=True)
        print("========================================", flush=True)

    try:
        script = session.create_script(patch_js_for_responses(JS_CODE) if capture_responses else JS_CODE)
        script.on("message", on_message)
        script.load()
        print("Hook loaded. Waiting for traffic. Ctrl+C to stop.", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(
            f"\nStopped. Captured {seen['count']} matching request(s), "
            f"{seen['responses']} matching response(s), "
            f"ignored {seen['unpaired_responses']} unpaired response(s).",
            flush=True,
        )
    finally:
        try:
            session.detach()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
