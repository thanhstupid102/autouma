"""Resolve the string literals referenced by the URL-builder methods, live.

Disassembles the dumped method bytes to find every RIP-relative global the
method loads, then reads those globals from the LIVE game process and interprets
each as a possible Il2CppString (length @ +0x10, UTF-16 chars @ +0x14). This
reveals the exact string literals the URL builder concatenates -- including the
root-manifest path prefix -- without any il2cpp API call (pure memory reads).

Run WHILE the game is running, after scripts/dump_url_builder_mem.py.
"""
import sys
import json
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import frida  # noqa: E402
import capstone  # noqa: E402

PROCESS_NAME = "UmamusumePrettyDerby.exe"
DUMP_DIR = ROOT / "uma_runtime" / "url_builder_dump"


def rip_targets(code_bytes, start_va):
    """Return absolute addresses of RIP-relative memory operands (lea/mov)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    targets = []
    for insn in md.disasm(code_bytes, start_va):
        for op in insn.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                ea = insn.address + insn.size + op.mem.disp
                targets.append((insn.address, insn.mnemonic, ea))
    return targets


def main():
    meta = json.loads((DUMP_DIR / "meta.json").read_text(encoding="utf-8"))
    base = int(meta["base"], 16)

    all_targets = {}
    for name, info in meta["targets"].items():
        if name.endswith("_ctx"):
            continue
        p = DUMP_DIR / f"{name}.bin"
        if not p.exists():
            continue
        start = base + info["rva"]
        eas = rip_targets(p.read_bytes(), start)
        all_targets[name] = eas

    # unique global addresses to probe
    addrs = sorted({ea for eas in all_targets.values() for (_, _, ea) in eas})
    print(f"{len(addrs)} distinct RIP-relative globals to probe", flush=True)

    session = frida.attach(PROCESS_NAME)
    js = """
    'use strict';
    (function () {
      var addrs = %s;   // decimal strings
      function readStr(p) {
        try {
          if (p.isNull()) return null;
          var len = p.add(0x10).readS32();
          if (len < 0 || len > 4096) return null;
          if (len === 0) return '';
          return p.add(0x14).readUtf16String(len);
        } catch (e) { return null; }
      }
      addrs.forEach(function (s) {
        var ga = ptr(s);
        var out = {addr: ga.toString()};
        try {
          // the global may itself hold the Il2CppString*, or point near it
          var deref = ga.readPointer();
          out.direct = readStr(ga);       // ga as Il2CppString*
          out.deref = readStr(deref);     // *ga as Il2CppString*
        } catch (e) {}
        if (out.direct || out.deref) send(out);
      });
      send({done: true});
    })();
    """ % json.dumps([str(a) for a in addrs])

    found = []
    done = {"f": False}

    def on_message(message, data):
        if message.get("type") == "error":
            print("frida err:", message.get("description"), flush=True)
            return
        p = message.get("payload") or {}
        if p.get("done"):
            done["f"] = True
            return
        s = p.get("deref") or p.get("direct")
        if s and s.strip():
            found.append((p.get("addr"), s))

    script = session.create_script(js)
    script.on("message", on_message)
    script.load()
    t0 = time.monotonic()
    while not done["f"] and time.monotonic() - t0 < 20:
        time.sleep(0.2)
    try:
        session.detach()
    except Exception:
        pass

    print("\n=== resolved string literals (addr -> value) ===", flush=True)
    seen = set()
    for addr, s in found:
        if s in seen:
            continue
        seen.add(s)
        printable = s if s.isprintable() else repr(s)
        print(f"  {addr}: {printable}", flush=True)
    (DUMP_DIR / "literals.json").write_text(
        json.dumps([{"addr": a, "value": s} for a, s in found], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
