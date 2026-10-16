from __future__ import annotations

import struct
from pathlib import Path

from scripts.dump_gameassembly_memory import JS_CODE, run_dump
from scripts.gameassembly_memory import (
    ByteRange,
    PESection,
    capture_ranges,
    classify_output,
    coverage_report,
    intersect_ranges,
    parse_pe_sections,
    section_coverages,
)


MIB = 1024 * 1024


def _synthetic_pe(sections: list[tuple[str, int, int]]) -> bytes:
    pe_offset = 0x80
    optional_size = 0xF0
    table_offset = pe_offset + 24 + optional_size
    data = bytearray(table_offset + 40 * len(sections))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", data, pe_offset + 6, len(sections))
    struct.pack_into("<H", data, pe_offset + 20, optional_size)
    for index, (name, virtual_address, virtual_size) in enumerate(sections):
        offset = table_offset + index * 40
        data[offset:offset + 8] = name.encode("ascii").ljust(8, b"\0")
        struct.pack_into("<II", data, offset + 8, virtual_size, virtual_address)
    return bytes(data)


def test_range_intersection_clips_both_module_ends_and_ignores_outside():
    ranges = [
        ByteRange(0x0800, 0x1000, "r--"),
        ByteRange(0x1800, 0x400, "r-x"),
        ByteRange(0x2800, 0x1000, "rw-"),
        ByteRange(0x0000, 0x800, "r--"),
        ByteRange(0x3000, 0x800, "r--"),
    ]

    assert intersect_ranges(0x1000, 0x2000, ranges) == [
        ByteRange(0x1000, 0x800, "r--"),
        ByteRange(0x1800, 0x400, "r-x"),
        ByteRange(0x2800, 0x800, "rw-"),
    ]


def test_bisection_isolates_a_bad_page_and_keeps_surrounding_data():
    bad_page = ByteRange(0x53000, 0x1000)
    attempts = []

    def reader(offset: int, length: int) -> bytes:
        attempts.append(ByteRange(offset, length))
        if offset < bad_page.end and offset + length > bad_page.start:
            raise OSError("unreadable page")
        return bytes([offset // 0x1000 % 251]) * length

    result = capture_ranges([ByteRange(0, MIB)], reader)
    coverage = coverage_report(MIB, result.captured)

    assert coverage.captured_bytes == MIB - 0x1000
    assert coverage.gaps == (bad_page,)
    assert [gap.span for gap in result.read_gaps] == [bad_page]
    assert bad_page in attempts
    assert any(span.end == bad_page.start for span in coverage.captured_ranges)
    assert any(span.start == bad_page.end for span in coverage.captured_ranges)


def test_coverage_records_gaps_and_does_not_double_count_overlaps():
    report = coverage_report(
        0x4000,
        [
            ByteRange(0x0000, 0x1800),
            ByteRange(0x1000, 0x1800),
            ByteRange(0x3000, 0x0800),
        ],
    )

    assert report.captured_bytes == 0x3000
    assert report.gap_bytes == 0x1000
    assert report.captured_ranges == (
        ByteRange(0x0000, 0x2800),
        ByteRange(0x3000, 0x0800),
    )
    assert report.gaps == (
        ByteRange(0x2800, 0x0800),
        ByteRange(0x3800, 0x0800),
    )


def test_per_section_coverage_uses_synthetic_pe_virtual_ranges():
    pe = _synthetic_pe(
        [
            (".text", 0x1000, 0x1000),
            ("il2cpp", 0x3000, 0x2000),
        ]
    )
    sections = parse_pe_sections(pe)
    reports = section_coverages(
        sections,
        [ByteRange(0x1000, 0x1000), ByteRange(0x3000, 0x1000)],
    )

    assert sections == [
        PESection(".text", 0x1000, 0x1000),
        PESection("il2cpp", 0x3000, 0x2000),
    ]
    assert reports[0].coverage_ratio == 1.0
    assert reports[1].captured_bytes == 0x1000
    assert reports[1].coverage_ratio == 0.5


def test_low_il2cpp_coverage_uses_partial_name_and_nonzero_exit():
    output = Path("GameAssembly.memdump.180000000.bin")
    sections = [PESection("il2cpp", 0x1000, 1000)]

    final_path, exit_code, ratio = classify_output(
        output,
        sections,
        [ByteRange(0x1000, 899)],
    )

    assert final_path.name == "GameAssembly.memdump.180000000.partial.bin"
    assert exit_code != 0
    assert ratio == 0.899


class _ReportOnlyBackend:
    def __init__(self) -> None:
        self.base = 0x180000000
        self.image = bytearray(0x5000)
        pe = _synthetic_pe([("il2cpp", 0x1000, 0x3000)])
        self.image[:len(pe)] = pe

    def find_module(self, name: str):
        return {
            "base": hex(self.base),
            "size": len(self.image),
            "path": r"C:\game\GameAssembly.dll",
        }

    def enumerate_module_ranges(self):
        item = {
            "base": hex(self.base),
            "size": len(self.image),
            "protection": "r-x",
        }
        return {"readable": [item], "committed": [item]}

    def read_chunk(
        self,
        base_string: str,
        offset: int,
        length: int,
        force_protect: bool,
        original_protection: str,
    ) -> bytes:
        return bytes(self.image[offset:offset + length])

    def close(self) -> None:
        pass


def test_report_only_writes_nothing(tmp_path):
    exit_code = run_dump(
        _ReportOnlyBackend(),
        report_only=True,
        force_protect=False,
        out_dir=tmp_path / "must-not-exist",
    )

    assert exit_code == 0
    assert not (tmp_path / "must-not-exist").exists()
    assert list(tmp_path.iterdir()) == []


def test_memory_dumper_has_no_il2cpp_thread_attach_reference():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dump_gameassembly_memory.py"
    forbidden_name = "il2cpp" + "_thread_attach"

    assert forbidden_name not in script_path.read_text(encoding="utf-8")
    assert "Process.enumerateRanges" in JS_CODE
    assert "Memory.protect" in JS_CODE
