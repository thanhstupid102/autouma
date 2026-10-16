"""Pure range, PE, and coverage helpers for the GameAssembly memory dumper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Callable, Iterable, Sequence


PAGE_SIZE = 4096
READ_CHUNK_SIZE = 1024 * 1024
IL2CPP_MIN_COVERAGE = 0.90
PARTIAL_EXIT_CODE = 2
MAX_PE_HEADER_SIZE = 2 * 1024 * 1024


@dataclass(frozen=True)
class ByteRange:
    start: int
    length: int
    protection: str = ""

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("range start cannot be negative")
        if self.length < 0:
            raise ValueError("range length cannot be negative")

    @property
    def end(self) -> int:
        return self.start + self.length


@dataclass(frozen=True)
class ReadGap:
    span: ByteRange
    error: str


@dataclass(frozen=True)
class CaptureResult:
    captured: tuple[ByteRange, ...]
    read_gaps: tuple[ReadGap, ...]


@dataclass(frozen=True)
class CoverageReport:
    total_bytes: int
    captured_bytes: int
    gap_bytes: int
    coverage_ratio: float
    captured_ranges: tuple[ByteRange, ...]
    gaps: tuple[ByteRange, ...]


@dataclass(frozen=True)
class PESection:
    name: str
    virtual_address: int
    virtual_size: int


@dataclass(frozen=True)
class SectionCoverage:
    section: PESection
    captured_bytes: int
    coverage_ratio: float


ReadFunction = Callable[[int, int], bytes]
WriteFunction = Callable[[int, bytes], None]


def intersect_ranges(
    window_start: int,
    window_size: int,
    ranges: Iterable[ByteRange],
) -> list[ByteRange]:
    """Clip absolute ranges to a containing window without changing coordinates."""
    window_end = window_start + window_size
    intersections = []
    for span in ranges:
        start = max(window_start, span.start)
        end = min(window_end, span.end)
        if start < end:
            intersections.append(ByteRange(start, end - start, span.protection))
    return sorted(intersections, key=lambda span: (span.start, span.end))


def relative_ranges(ranges: Iterable[ByteRange], base: int) -> list[ByteRange]:
    return [
        ByteRange(span.start - base, span.length, span.protection)
        for span in ranges
    ]


def merge_ranges(ranges: Iterable[ByteRange]) -> list[ByteRange]:
    """Union ranges for coverage accounting, ignoring protection labels."""
    ordered = sorted(
        (span for span in ranges if span.length),
        key=lambda span: (span.start, span.end),
    )
    merged: list[ByteRange] = []
    for span in ordered:
        if not merged or span.start > merged[-1].end:
            merged.append(ByteRange(span.start, span.length))
            continue
        previous = merged[-1]
        merged[-1] = ByteRange(previous.start, max(previous.end, span.end) - previous.start)
    return merged


def subtract_ranges(
    sources: Iterable[ByteRange],
    covered: Iterable[ByteRange],
) -> list[ByteRange]:
    """Subtract a coverage union while retaining each source's protection."""
    covered_union = merge_ranges(covered)
    remaining = []
    for source in sorted(sources, key=lambda span: (span.start, span.end)):
        cursor = source.start
        for blocker in covered_union:
            if blocker.end <= cursor:
                continue
            if blocker.start >= source.end:
                break
            if blocker.start > cursor:
                remaining.append(
                    ByteRange(cursor, blocker.start - cursor, source.protection)
                )
            cursor = max(cursor, blocker.end)
            if cursor >= source.end:
                break
        if cursor < source.end:
            remaining.append(ByteRange(cursor, source.end - cursor, source.protection))
    return remaining


def coverage_for_span(target: ByteRange, captured: Iterable[ByteRange]) -> int:
    clipped = intersect_ranges(target.start, target.length, merge_ranges(captured))
    return sum(span.length for span in merge_ranges(clipped))


def coverage_report(total_size: int, captured: Iterable[ByteRange]) -> CoverageReport:
    if total_size < 0:
        raise ValueError("total size cannot be negative")
    captured_ranges = tuple(
        merge_ranges(intersect_ranges(0, total_size, merge_ranges(captured)))
    )
    gaps = tuple(subtract_ranges([ByteRange(0, total_size)], captured_ranges))
    captured_bytes = sum(span.length for span in captured_ranges)
    gap_bytes = total_size - captured_bytes
    ratio = captured_bytes / total_size if total_size else 1.0
    return CoverageReport(
        total_bytes=total_size,
        captured_bytes=captured_bytes,
        gap_bytes=gap_bytes,
        coverage_ratio=ratio,
        captured_ranges=captured_ranges,
        gaps=gaps,
    )


def _read_or_error(reader: ReadFunction, start: int, length: int) -> tuple[bytes | None, str]:
    try:
        data = reader(start, length)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if len(data) != length:
        return None, f"short read: expected {length} bytes, got {len(data)}"
    return data, ""


def _bisect_read(
    reader: ReadFunction,
    start: int,
    length: int,
    page_size: int,
    captured: list[ByteRange],
    gaps: list[ReadGap],
    on_data: WriteFunction | None,
) -> None:
    data, error = _read_or_error(reader, start, length)
    if data is not None:
        captured.append(ByteRange(start, length))
        if on_data is not None:
            on_data(start, data)
        return

    if length <= page_size:
        gaps.append(ReadGap(ByteRange(start, length), error))
        return

    left_length = (length // 2 // page_size) * page_size
    if left_length <= 0:
        left_length = min(page_size, length)
    if left_length >= length:
        left_length = length // 2
    _bisect_read(
        reader,
        start,
        left_length,
        page_size,
        captured,
        gaps,
        on_data,
    )
    _bisect_read(
        reader,
        start + left_length,
        length - left_length,
        page_size,
        captured,
        gaps,
        on_data,
    )


def capture_ranges(
    ranges: Iterable[ByteRange],
    reader: ReadFunction,
    *,
    chunk_size: int = READ_CHUNK_SIZE,
    page_size: int = PAGE_SIZE,
    on_data: WriteFunction | None = None,
) -> CaptureResult:
    """Read ranges in modest chunks and isolate failures to page granularity."""
    if chunk_size <= 0 or page_size <= 0:
        raise ValueError("chunk and page sizes must be positive")
    captured: list[ByteRange] = []
    gaps: list[ReadGap] = []
    for span in ranges:
        offset = span.start
        while offset < span.end:
            length = min(chunk_size, span.end - offset)
            _bisect_read(
                reader,
                offset,
                length,
                page_size,
                captured,
                gaps,
                on_data,
            )
            offset += length
    return CaptureResult(tuple(captured), tuple(gaps))


def combine_capture_results(results: Iterable[CaptureResult]) -> CaptureResult:
    captured = []
    gaps = []
    for result in results:
        captured.extend(result.captured)
        gaps.extend(result.read_gaps)
    return CaptureResult(tuple(captured), tuple(gaps))


def _require_memory_bytes(
    start: int,
    length: int,
    eligible_ranges: Sequence[ByteRange],
    reader: ReadFunction,
) -> bytes:
    planned = intersect_ranges(start, length, eligible_ranges)
    pieces: list[tuple[int, bytes]] = []
    result = capture_ranges(
        planned,
        reader,
        on_data=lambda offset, data: pieces.append((offset, data)),
    )
    if coverage_for_span(ByteRange(start, length), result.captured) != length:
        raise ValueError(
            f"PE headers are not fully readable at RVA 0x{start:X}-0x{start + length:X}"
        )
    blob = bytearray(length)
    for offset, data in pieces:
        relative = offset - start
        blob[relative:relative + len(data)] = data
    return bytes(blob)


def parse_pe_sections(data: bytes) -> list[PESection]:
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("memory image does not contain a valid DOS header")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("memory image does not contain a valid PE header")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    table_offset = pe_offset + 24 + optional_size
    table_end = table_offset + section_count * 40
    if table_end > len(data):
        raise ValueError("memory buffer ends before the PE section table")

    sections = []
    for index in range(section_count):
        offset = table_offset + index * 40
        raw_name = data[offset:offset + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", errors="replace")
        virtual_size, virtual_address = struct.unpack_from("<II", data, offset + 8)
        sections.append(PESection(name, virtual_address, virtual_size))
    return sections


def read_pe_sections_from_memory(
    reader: ReadFunction,
    eligible_ranges: Sequence[ByteRange],
) -> list[PESection]:
    dos_header = _require_memory_bytes(0, 64, eligible_ranges, reader)
    pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
    coff_end = pe_offset + 24
    if coff_end > MAX_PE_HEADER_SIZE:
        raise ValueError(f"implausible PE header offset 0x{pe_offset:X}")
    coff_headers = _require_memory_bytes(0, coff_end, eligible_ranges, reader)
    if coff_headers[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("memory image does not contain a valid PE signature")
    section_count = struct.unpack_from("<H", coff_headers, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", coff_headers, pe_offset + 20)[0]
    table_end = pe_offset + 24 + optional_size + section_count * 40
    if table_end > MAX_PE_HEADER_SIZE:
        raise ValueError(f"implausible PE section table size 0x{table_end:X}")
    headers = _require_memory_bytes(0, table_end, eligible_ranges, reader)
    return parse_pe_sections(headers)


def section_coverages(
    sections: Iterable[PESection],
    captured: Iterable[ByteRange],
) -> list[SectionCoverage]:
    captured_union = merge_ranges(captured)
    reports = []
    for section in sections:
        span = ByteRange(section.virtual_address, section.virtual_size)
        captured_bytes = coverage_for_span(span, captured_union)
        ratio = captured_bytes / section.virtual_size if section.virtual_size else 1.0
        reports.append(SectionCoverage(section, captured_bytes, ratio))
    return reports


def il2cpp_coverage_ratio(
    sections: Iterable[PESection],
    captured: Iterable[ByteRange],
) -> float | None:
    for report in section_coverages(sections, captured):
        if report.section.name.lower() == "il2cpp":
            return report.coverage_ratio
    return None


def partial_output_path(path: Path) -> Path:
    if path.name.endswith(".partial.bin"):
        return path
    if path.suffix.lower() == ".bin":
        return path.with_name(f"{path.stem}.partial.bin")
    return path.with_name(f"{path.name}.partial.bin")


def classify_output(
    path: Path,
    sections: Iterable[PESection],
    captured: Iterable[ByteRange],
    *,
    minimum: float = IL2CPP_MIN_COVERAGE,
) -> tuple[Path, int, float | None]:
    ratio = il2cpp_coverage_ratio(sections, captured)
    if ratio is None or ratio < minimum:
        return partial_output_path(path), PARTIAL_EXIT_CODE, ratio
    return path, 0, ratio
