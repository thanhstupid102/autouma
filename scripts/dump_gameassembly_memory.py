"""Dump the live, self-unpacked GameAssembly.dll image for offline analysis.

The installed DLL is packed: the large ``il2cpp`` virtual section has almost no
raw file data. This tool captures the materialized memory image while preserving
RVA == file offset. It enumerates readable ranges, reads them in 1 MiB chunks,
bisects failures to 4 KiB, and records every captured range and gap in
``<output>.coverage.json``. It never silently treats a failed read as valid data.

Use ``--report-only`` first. It reads only the in-memory PE headers, then prints
the section table, readable/unreadable map, and projected overall/per-section
coverage without creating an output directory or dump file. A real dump whose
``il2cpp`` coverage is below 90% is named ``*.partial.bin``, carries a prominent
warning, and exits with status 2. Such a dump cannot reliably answer code-level
questions; its covered ranges may still be useful for targeted inspection.

``--force-protect`` additionally attempts committed-but-unreadable ranges by
temporarily applying ``rwx`` protection around each read. The embedded Frida
code restores the exact original protection in a ``finally`` path, including
failed reads. This mutates the live process and may destabilise the game, so it
is off by default.

The output is a flat memory-layout image, not a normal on-disk PE. Uncaptured
offsets remain placeholders solely to preserve RVA alignment; consult the
coverage sidecar before using any address. IDA/Ghidra can load sufficiently
covered output as raw x86-64 at the reported module base.

Il2CppDumper caveat (still unresolved): GameAssembly.dll normally remains at its
preferred ImageBase 0x180000000. Il2CppDumper v6.7.46's PE ``CheckDump()`` uses
``ImageBase != 0x180000000`` as its dump-mode test, so a same-base memory image
is mistaken for disk layout and mapped through PointerToRawData/SizeOfRawData.
``PE.LoadFromMemory(addr)`` would correct the section mapping, but the stock PE
flow never calls it (only the ELF path asks for a dump address). Using this dump
with Il2CppDumper therefore still requires patching/rebuilding it or driving its
library classes directly and calling ``LoadFromMemory(0x180000000)`` before
``PlusSearch``. This script does not solve that tooling problem.

Usage, after the owner has launched the game and reached Home so the packer's
one-time self-unpack has finished::

    .venv\\Scripts\\python.exe scripts\\dump_gameassembly_memory.py --report-only
    .venv\\Scripts\\python.exe scripts\\dump_gameassembly_memory.py

Add ``--force-protect`` to the second command only if the report shows important
committed ranges as unreadable and the process-mutation risk is acceptable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Protocol


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.gameassembly_memory import (  # noqa: E402
    ByteRange,
    CaptureResult,
    CoverageReport,
    IL2CPP_MIN_COVERAGE,
    PESection,
    READ_CHUNK_SIZE,
    capture_ranges,
    classify_output,
    combine_capture_results,
    coverage_report,
    intersect_ranges,
    read_pe_sections_from_memory,
    relative_ranges,
    section_coverages,
    subtract_ranges,
)


MODULE_NAME = "GameAssembly.dll"
OUT_DIR = ROOT / "uma_runtime" / "re_rankpoint"
ATTACH_TIMEOUT_SEC = 120

# This agent uses only Process/Memory primitives. It does not call the IL2CPP
# runtime, so no managed-runtime or GC thread attachment is needed.
JS_CODE = r"""
'use strict';

function serializeRanges(ranges) {
  return ranges.map(function (range) {
    return {
      base: range.base.toString(),
      size: range.size,
      protection: range.protection
    };
  });
}

rpc.exports = {
  findModule: function (name) {
    var module = Process.findModuleByName(name);
    if (module === null) return null;
    return {
      base: module.base.toString(),
      size: module.size,
      path: module.path
    };
  },

  enumerateModuleRanges: function () {
    return {
      readable: serializeRanges(Process.enumerateRanges({
        protection: 'r--',
        coalesce: false
      })),
      committed: serializeRanges(Process.enumerateRanges({
        protection: '---',
        coalesce: false
      }))
    };
  },

  readChunk: function (baseString, offset, length, forceProtect, originalProtection) {
    var address = ptr(baseString).add(offset);
    var changedProtection = false;
    var data = null;
    var readError = null;

    try {
      if (forceProtect) {
        if (!Memory.protect(address, length, 'rwx')) {
          throw new Error('Memory.protect(rwx) returned false');
        }
        changedProtection = true;
      }
      data = address.readByteArray(length);
    } catch (error) {
      readError = error;
    } finally {
      if (changedProtection) {
        var restored = false;
        try {
          restored = Memory.protect(address, length, originalProtection);
        } catch (restoreError) {
          throw new Error('read failed and protection restore threw: ' + restoreError);
        }
        if (!restored) {
          throw new Error('Memory.protect restore returned false for ' + originalProtection);
        }
      }
    }

    if (readError !== null) throw readError;
    return data;
  }
};
"""


class DumperBackend(Protocol):
    def find_module(self, name: str) -> dict[str, Any] | None: ...

    def enumerate_module_ranges(self) -> dict[str, list[dict[str, Any]]]: ...

    def read_chunk(
        self,
        base_string: str,
        offset: int,
        length: int,
        force_protect: bool,
        original_protection: str,
    ) -> bytes: ...

    def close(self) -> None: ...


class FridaBackend:
    def __init__(self, process_name: str) -> None:
        import frida

        print(f"Attaching to {process_name} ...", flush=True)
        session = None
        deadline = time.monotonic() + ATTACH_TIMEOUT_SEC
        while time.monotonic() < deadline:
            try:
                session = frida.attach(process_name)
                break
            except Exception:
                time.sleep(1.0)
        if session is None:
            raise RuntimeError(
                f"{process_name} not found within {ATTACH_TIMEOUT_SEC}s"
            )
        self._session = session
        self._script = session.create_script(JS_CODE)
        self._script.load()
        self._api = self._script.exports_sync

    def find_module(self, name: str) -> dict[str, Any] | None:
        return self._api.find_module(name)

    def enumerate_module_ranges(self) -> dict[str, list[dict[str, Any]]]:
        return self._api.enumerate_module_ranges()

    def read_chunk(
        self,
        base_string: str,
        offset: int,
        length: int,
        force_protect: bool,
        original_protection: str,
    ) -> bytes:
        result = self._api.read_chunk(
            base_string,
            offset,
            length,
            force_protect,
            original_protection,
        )
        if result is None:
            raise RuntimeError("Frida returned no bytes")
        return bytes(result)

    def close(self) -> None:
        try:
            self._session.detach()
        except Exception:
            pass


def _parse_exported_ranges(items: list[dict[str, Any]]) -> list[ByteRange]:
    return [
        ByteRange(
            int(str(item["base"]), 0),
            int(item["size"]),
            str(item.get("protection", "")),
        )
        for item in items
    ]


def _format_span(span: ByteRange) -> str:
    return (
        f"RVA 0x{span.start:08X}-0x{span.end:08X} "
        f"len=0x{span.length:X} protection={span.protection or 'unknown'}"
    )


def _print_range_map(
    readable: list[ByteRange],
    unreadable: list[ByteRange],
    unmapped: list[ByteRange],
) -> None:
    print("\nReadable ranges inside the module:", flush=True)
    for span in readable:
        print(f"  {_format_span(span)}", flush=True)
    if not readable:
        print("  (none)", flush=True)

    print("\nCommitted but unreadable ranges inside the module:", flush=True)
    for span in unreadable:
        print(f"  {_format_span(span)}", flush=True)
    if not unreadable:
        print("  (none)", flush=True)

    print("\nUnmapped/reserved gaps inside the module:", flush=True)
    for span in unmapped:
        print(f"  {_format_span(span)}", flush=True)
    if not unmapped:
        print("  (none)", flush=True)


def _print_coverage(
    label: str,
    module_size: int,
    sections: list[PESection],
    captured: list[ByteRange] | tuple[ByteRange, ...],
) -> None:
    overall = coverage_report(module_size, captured)
    print(
        f"\n{label} overall coverage: {overall.coverage_ratio * 100:.2f}% "
        f"({overall.captured_bytes} / {overall.total_bytes} bytes)",
        flush=True,
    )
    print(f"{label} section coverage:", flush=True)
    for report in section_coverages(sections, captured):
        section = report.section
        marker = "  <== required" if section.name.lower() == "il2cpp" else ""
        print(
            f"  {section.name or '<unnamed>':8} "
            f"RVA=0x{section.virtual_address:08X} "
            f"VirtualSize=0x{section.virtual_size:X} "
            f"coverage={report.coverage_ratio * 100:6.2f}% "
            f"({report.captured_bytes}/{section.virtual_size}){marker}",
            flush=True,
        )


def _warn_partial(ratio: float | None, report_only: bool) -> None:
    measured = "missing" if ratio is None else f"{ratio * 100:.2f}%"
    qualifier = "Projected" if report_only else "Captured"
    print("\n" + "!" * 78, flush=True)
    print(
        f"WARNING: {qualifier} il2cpp coverage is {measured}; "
        f"the required minimum is {IL2CPP_MIN_COVERAGE * 100:.0f}%.",
        flush=True,
    )
    print(
        "This image cannot be trusted to answer code-level questions.",
        flush=True,
    )
    print("!" * 78, flush=True)


def _sidecar_path(output_path: Path) -> Path:
    return Path(f"{output_path}.coverage.json")


def _range_json(span: ByteRange) -> dict[str, int]:
    return {"offset": span.start, "length": span.length}


def _section_json(
    sections: list[PESection],
    captured: tuple[ByteRange, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "name": report.section.name,
            "virtual_address": report.section.virtual_address,
            "virtual_size": report.section.virtual_size,
            "captured_bytes": report.captured_bytes,
            "coverage_percent": report.coverage_ratio * 100,
        }
        for report in section_coverages(sections, captured)
    ]


def _write_sidecar(
    path: Path,
    info: dict[str, Any],
    force_protect: bool,
    coverage: CoverageReport,
    sections: list[PESection],
    result: CaptureResult,
) -> None:
    payload = {
        "module": MODULE_NAME,
        "base": str(info["base"]),
        "size": int(info["size"]),
        "path": str(info["path"]),
        "memory_layout": True,
        "force_protect": force_protect,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "captured_ranges": [
            _range_json(span) for span in coverage.captured_ranges
        ],
        "gaps": [_range_json(span) for span in coverage.gaps],
        "read_failures": [
            {
                "offset": gap.span.start,
                "length": gap.span.length,
                "error": gap.error,
            }
            for gap in result.read_gaps
        ],
        "totals": {
            "module_bytes": coverage.total_bytes,
            "captured_bytes": coverage.captured_bytes,
            "gap_bytes": coverage.gap_bytes,
            "coverage_percent": coverage.coverage_ratio * 100,
        },
        "sections": _section_json(sections, coverage.captured_ranges),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_dump(
    backend: DumperBackend,
    *,
    report_only: bool,
    force_protect: bool,
    out_dir: Path = OUT_DIR,
) -> int:
    info = backend.find_module(MODULE_NAME)
    if info is None:
        print(f"Error: module {MODULE_NAME} not found in process.", flush=True)
        return 1

    base_string = str(info["base"])
    module_base = int(base_string, 0)
    module_size = int(info["size"])
    print(
        f"Found {MODULE_NAME}: base={base_string} size=0x{module_size:X} "
        f"({module_size / (1024 * 1024):.1f} MiB)",
        flush=True,
    )
    print(f"path={info['path']}", flush=True)

    exported = backend.enumerate_module_ranges()
    readable_absolute = intersect_ranges(
        module_base,
        module_size,
        _parse_exported_ranges(exported["readable"]),
    )
    committed_absolute = intersect_ranges(
        module_base,
        module_size,
        _parse_exported_ranges(exported["committed"]),
    )
    readable = relative_ranges(readable_absolute, module_base)
    committed = relative_ranges(committed_absolute, module_base)
    unreadable = subtract_ranges(committed, readable)
    unmapped = subtract_ranges(
        [ByteRange(0, module_size, "unmapped/reserved")],
        [*committed, *readable],
    )
    _print_range_map(readable, unreadable, unmapped)

    def plain_reader(offset: int, length: int) -> bytes:
        return backend.read_chunk(base_string, offset, length, False, "")

    try:
        sections = read_pe_sections_from_memory(plain_reader, readable)
    except ValueError as exc:
        print(f"Error: could not parse PE headers from memory: {exc}", flush=True)
        return 1

    candidates = [(span, False) for span in readable]
    if force_protect:
        candidates.extend((span, True) for span in unreadable)
    candidates.sort(key=lambda item: (item[0].start, item[0].end))
    projected_ranges = [span for span, _force in candidates]
    _print_coverage("Projected", module_size, sections, projected_ranges)

    base_hex = base_string.removeprefix("0x").lower()
    base_output_path = out_dir / f"GameAssembly.memdump.{base_hex}.bin"
    projected_path, projected_exit, projected_il2cpp = classify_output(
        base_output_path,
        sections,
        projected_ranges,
    )
    if projected_exit:
        _warn_partial(projected_il2cpp, report_only)
    if report_only:
        print("\nReport-only mode: no directory, dump, or sidecar was written.", flush=True)
        return projected_exit

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = projected_path
    print(f"\nDumping to {output_path} ...", flush=True)
    print(
        "Uncaptured offsets remain placeholders for RVA alignment and are listed "
        "in the coverage sidecar.",
        flush=True,
    )

    results = []
    processed = 0
    with output_path.open("wb+") as output:
        output.truncate(module_size)

        def write_data(offset: int, data: bytes) -> None:
            output.seek(offset)
            output.write(data)

        for candidate, force in candidates:
            def candidate_reader(offset: int, length: int) -> bytes:
                return backend.read_chunk(
                    base_string,
                    offset,
                    length,
                    force,
                    candidate.protection,
                )

            result = capture_ranges(
                [candidate],
                candidate_reader,
                chunk_size=READ_CHUNK_SIZE,
                on_data=write_data,
            )
            results.append(result)
            processed += candidate.length
            print(
                f"  planned {processed / module_size * 100:6.2f}% "
                f"(through RVA 0x{candidate.end:X})",
                flush=True,
            )

    combined = combine_capture_results(results)
    actual = coverage_report(module_size, combined.captured)
    _print_coverage("Captured", module_size, sections, combined.captured)
    final_path, exit_code, il2cpp_ratio = classify_output(
        base_output_path,
        sections,
        combined.captured,
    )
    if final_path != output_path:
        output_path.replace(final_path)
        output_path = final_path
    if exit_code:
        _warn_partial(il2cpp_ratio, False)

    sidecar_path = _sidecar_path(output_path)
    _write_sidecar(
        sidecar_path,
        info,
        force_protect,
        actual,
        sections,
        combined,
    )
    print(f"\nRaw dump -> {output_path}", flush=True)
    print(f"Coverage -> {sidecar_path}", flush=True)
    print(
        f"Captured {actual.captured_bytes} bytes; "
        f"{actual.gap_bytes} bytes are explicitly recorded as gaps.",
        flush=True,
    )
    print(
        f"Read failures isolated to {len(combined.read_gaps)} page-level gap(s).",
        flush=True,
    )
    print(
        f"This is a flat memory-layout image; load as raw x86-64 at {base_string}.",
        flush=True,
    )
    return exit_code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print the range map and projected coverage without writing files",
    )
    parser.add_argument(
        "--force-protect",
        action="store_true",
        help="temporarily set committed unreadable ranges to rwx while reading",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.force_protect:
        print("!" * 78, flush=True)
        if args.report_only:
            print(
                "WARNING: a real --force-protect dump mutates live page "
                "protections and may destabilise the game.",
                flush=True,
            )
            print(
                "Report-only mode projects those ranges but does not change "
                "their protections.",
                flush=True,
            )
        else:
            print(
                "WARNING: --force-protect mutates live page protections and may "
                "destabilise the game.",
                flush=True,
            )
        print(
            "During a real dump, each changed range is restored to its original "
            "protection in the embedded reader's finally path.",
            flush=True,
        )
        print("!" * 78, flush=True)

    from core.settings import Settings

    backend = None
    try:
        backend = FridaBackend(Settings.APP_PROCESS_NAME)
        return run_dump(
            backend,
            report_only=args.report_only,
            force_protect=args.force_protect,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", flush=True)
        return 1
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
