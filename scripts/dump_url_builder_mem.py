"""Dump the resource URL-builder machine code from the LIVE (running) game.

The on-disk GameAssembly.dll is packed and its method bodies are only decrypted
in memory at runtime, so a static unpack fails. This attaches to the running
game and reads the raw bytes of the URL-builder methods straight from process
memory -- a PURE memory read (no il2cpp API calls, no thread attach), so it
cannot trigger the Boehm-GC crash the il2cpp hook did.

Run this WHILE the game is running (title or home). It writes the raw bytes of
each method to uma_runtime/url_builder_dump/<name>.bin plus a meta.json with the
module base, so the bytes can be disassembled offline.

Usage:
    python scripts/dump_url_builder_mem.py
"""
import sys
import json
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402

PROCESS_NAME = "UmamusumePrettyDerby.exe"
OUT_DIR = ROOT / "uma_runtime" / "url_builder_dump"

# (name, RVA from dump.cs, bytes to read). RVAs are for Gallop.GameDefine's
# resource URL builders; if the installed build drifted, the disassembly will
# look wrong and we re-derive, but il2cpp method RVAs are usually stable within
# a minor version.
TARGETS = [
    ("GetDirectRootManifestUrl", 0x045319E0, 2048),
    ("GetManifestUrl", 0x045317A0, 1024),
    ("get_ResourceServerURLForManifest", 0x04530AC0, 512),
    ("get_ResourceServerURLForMaster", 0x04530B00, 512),
    ("get_ResourceServerUrlForBundle", 0x04530A80, 512),
    ("GetDirectRootManifestUrl_ctx", 0x045319E0, 4096),
]

JS = """
'use strict';
(function () {
  var targets = %s;
  var ga = Process.findModuleByName('GameAssembly.dll');
  if (!ga) { send({type: 'error', message: 'GameAssembly.dll not found' }); return; }
  send({type: 'base', base: ga.base.toString(), size: ga.size});
  targets.forEach(function (t) {
    var name = t[0], rva = t[1], len = t[2];
    try {
      var addr = ga.base.add(rva);
      var bytes = addr.readByteArray(len);
      send({type: 'dump', name: name, rva: rva, addr: addr.toString(), len: len}, bytes);
    } catch (e) {
      send({type: 'dump_err', name: name, rva: rva, error: '' + e});
    }
  });
  send({type: 'done'});
})();
""" % json.dumps([[n, r, l] for (n, r, l) in TARGETS])


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Attaching to {PROCESS_NAME} (game must be running)...", flush=True)
    deadline = time.monotonic() + 60
    session = None
    while time.monotonic() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(0.5)
    if session is None:
        print("ERROR: game process not found. Launch the game first.", flush=True)
        return 1

    meta = {"targets": {}}
    done = {"flag": False}

    def on_message(message, data):
        if message.get("type") == "error":
            print("Frida error:", message.get("description"), flush=True)
            return
        payload = message.get("payload") or {}
        t = payload.get("type")
        if t == "base":
            meta["base"] = payload.get("base")
            meta["module_size"] = payload.get("size")
            print("GameAssembly.dll base:", payload.get("base"), flush=True)
        elif t == "dump" and data is not None:
            name = payload.get("name")
            (OUT_DIR / f"{name}.bin").write_bytes(data)
            meta["targets"][name] = {"rva": payload.get("rva"), "addr": payload.get("addr"), "len": len(data)}
            print(f"  dumped {name}: {len(data)} bytes @ {payload.get('addr')}", flush=True)
        elif t == "dump_err":
            print(f"  ERR {payload.get('name')}: {payload.get('error')}", flush=True)
        elif t == "error":
            print("  ", payload.get("message"), flush=True)
        elif t == "done":
            done["flag"] = True

    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()

    t0 = time.monotonic()
    while not done["flag"] and time.monotonic() - t0 < 15:
        time.sleep(0.2)

    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        session.detach()
    except Exception:
        pass
    print(f"\nDone. Dumps in {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
