"""Download captured master resources and reveal the master.mdb payload format.

Run this phase-1 probe after scripts/capture_resource_urls.py, or pass explicit
manifest/master URL overrides. The game obtains these resources during its
title-screen check before account login, so the capture does not require login
or risk re-authentication. This script downloads only enough to decide whether
phase 2 needs direct LZ4 decompression or additional cipher reverse engineering.

Usage:
    python scripts/probe_master_download.py
    python scripts/probe_master_download.py --master-url https://.../master.mdb.lz4
"""
import argparse
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

try:
    import lz4.frame as lz4_frame
except ImportError:
    lz4_frame = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CAPTURE_PATH = ROOT / "uma_runtime" / "resource_urls.jsonl"
PROBE_DIR = ROOT / "uma_runtime" / "master_probe"
MANIFEST_PATH = PROBE_DIR / "manifest.bin"
RAW_MASTER_PATH = PROBE_DIR / "master.mdb.lz4"
MASTER_PATH = PROBE_DIR / "master.mdb"
DECOMPRESSED_PATH = PROBE_DIR / "master.decompressed.bin"
SQLITE_MAGIC = b"SQLite format 3\x00"
RESOURCE_VERSION_RE = re.compile(r"(?<![0-9A-Za-z])\d{8,}(?![0-9A-Za-z])")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class ProbeError(Exception):
    pass


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Download a captured master.mdb.lz4 and identify its format.",
    )
    parser.add_argument(
        "--capture-file",
        type=pathlib.Path,
        default=DEFAULT_CAPTURE_PATH,
        help="Captured resource JSONL (default: uma_runtime/resource_urls.jsonl).",
    )
    parser.add_argument("--manifest-url", help="Explicit manifest URL.")
    parser.add_argument("--master-url", help="Explicit master.mdb.lz4 URL.")
    parser.add_argument(
        "--base-url",
        help="Rebase captured relative/path URLs onto this CDN base URL.",
    )
    parser.add_argument(
        "--res-ver",
        help="Prefer and replace captured standalone resource-version digits.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Download timeout in seconds (default: 120).",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.res_ver is not None and not args.res_ver.isdigit():
        parser.error("--res-ver must contain digits only")
    return args


def _read_captured_urls(path):
    if not path.exists():
        return []
    urls = []
    malformed = 0
    with open(path, "r", encoding="utf-8") as capture:
        for line in capture:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                malformed += 1
                continue
            url = record.get("url") if isinstance(record, dict) else None
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
    if malformed:
        print(f"Skipped {malformed} malformed capture line(s).")
    return urls


def _choose_latest(urls, predicate, res_ver):
    matches = [url for url in urls if predicate(url.lower())]
    if res_ver:
        version_matches = [url for url in matches if res_ver in url]
        if version_matches:
            return version_matches[-1]
    return matches[-1] if matches else None


def _apply_res_ver(url, res_ver):
    if "{res_ver}" in url:
        if not res_ver:
            raise ProbeError("URL contains {res_ver}, but --res-ver was not provided.")
        return url.replace("{res_ver}", res_ver)
    if res_ver and res_ver not in url:
        return RESOURCE_VERSION_RE.sub(res_ver, url, count=1)
    return url


def _rebase_url(url, base_url):
    base = base_url.strip()
    if "://" not in base:
        base = "https://" + base
    base_parts = urllib.parse.urlsplit(base)
    if not base_parts.netloc:
        raise ProbeError(f"Invalid --base-url: {base_url}")
    source_parts = urllib.parse.urlsplit(url)
    if not source_parts.netloc:
        return urllib.parse.urljoin(base.rstrip("/") + "/", url.lstrip("/"))
    base_path = base_parts.path.rstrip("/")
    source_path = source_parts.path
    if (
        base_path
        and base_path != "/"
        and source_path != base_path
        and not source_path.startswith(base_path + "/")
    ):
        source_path = base_path + "/" + source_path.lstrip("/")
    return urllib.parse.urlunsplit(
        (base_parts.scheme or "https", base_parts.netloc, source_path,
         source_parts.query, "")
    )


def _normalize_url(url, base_url, res_ver, rebase):
    normalized = _apply_res_ver(url.strip(), res_ver)
    if base_url:
        expanded_base = _apply_res_ver(base_url, res_ver)
        if rebase or not urllib.parse.urlsplit(normalized).netloc:
            normalized = _rebase_url(normalized, expanded_base)
    parts = urllib.parse.urlsplit(normalized)
    if parts.scheme.lower() != "https" or not parts.netloc:
        raise ProbeError(
            f"Resource URL must be absolute HTTPS (or paired with --base-url): {normalized}"
        )
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, "")
    )


def _resolve_urls(args):
    captured = _read_captured_urls(args.capture_file)
    captured_master = _choose_latest(
        captured,
        lambda url: "master" in url and ".lz4" in url,
        args.res_ver,
    )
    captured_manifest = _choose_latest(
        captured,
        lambda url: "manifest" in url,
        args.res_ver,
    )
    master_source = args.master_url or captured_master
    manifest_source = args.manifest_url or captured_manifest
    master_url = None
    manifest_url = None
    if master_source:
        master_url = _normalize_url(
            master_source,
            args.base_url,
            args.res_ver,
            rebase=args.master_url is None,
        )
    if manifest_source:
        manifest_url = _normalize_url(
            manifest_source,
            args.base_url,
            args.res_ver,
            rebase=args.manifest_url is None,
        )
    return master_url, manifest_url


def _download(url, timeout):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.getcode(), response.read()


def _print_verdict(master_url, raw_size, lz4_ok, sqlite_ok, recommendation):
    print("\n=== MASTER PROBE VERDICT ===")
    print(f"master url: {master_url}")
    print(f"raw size: {raw_size} bytes")
    print(f"lz4 ok?: {'yes' if lz4_ok else 'no'}")
    print(f"sqlite ok?: {'yes' if sqlite_ok else 'no'}")
    print(f"recommended next step: {recommendation}")


def _probe_master(master_url, timeout):
    if lz4_frame is None:
        raise ProbeError("lz4 is not installed; install requirements.txt and rerun.")
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    status, raw = _download(master_url, timeout)
    RAW_MASTER_PATH.write_bytes(raw)
    print(f"Master download: HTTP {status}, {len(raw)} bytes.")
    print(f"Raw master saved to {RAW_MASTER_PATH}")

    try:
        decompressed = lz4_frame.decompress(raw)
    except Exception as exc:
        print(
            "raw bytes are not a valid LZ4 frame -> encrypted-then-lz4 or custom "
            f"container. First 32 bytes: {raw[:32].hex()}."
        )
        print(f"LZ4 error: {type(exc).__name__}: {exc}")
        recommendation = (
            "Reverse the outer encryption/custom container before phase 2, then "
            "validate the recovered LZ4 payload."
        )
        _print_verdict(master_url, len(raw), False, False, recommendation)
        return

    if decompressed[:16] == SQLITE_MAGIC:
        MASTER_PATH.write_bytes(decompressed)
        print(
            "MASTER IS PLAIN LZ4 (not encrypted). Decompressed SQLite OK, "
            f"{len(decompressed)} bytes."
        )
        print(f"Decompressed database saved to {MASTER_PATH}")
        recommendation = (
            "Build phase 2 as download + lz4.frame decompression; no cipher RE "
            "is needed."
        )
        _print_verdict(master_url, len(raw), True, True, recommendation)
        return

    DECOMPRESSED_PATH.write_bytes(decompressed)
    print(
        "LZ4 decompressed but NOT SQLite -> payload is ENCRYPTED under LZ4. "
        f"First bytes: {decompressed[:16].hex()}."
    )
    print(f"Decompressed payload saved to {DECOMPRESSED_PATH}")
    recommendation = (
        "Reverse the cipher on the decompressed payload before building phase 2."
    )
    _print_verdict(master_url, len(raw), True, False, recommendation)


def main():
    args = _parse_args()
    try:
        master_url, manifest_url = _resolve_urls(args)
        if master_url:
            _probe_master(master_url, args.timeout)
            return 0
        if manifest_url:
            PROBE_DIR.mkdir(parents=True, exist_ok=True)
            status, manifest = _download(manifest_url, args.timeout)
            MANIFEST_PATH.write_bytes(manifest)
            print(f"Manifest download: HTTP {status}, {len(manifest)} bytes.")
            print(f"Manifest saved to {MANIFEST_PATH}")
            print(
                "manifest saved; need manifest parse to locate master — rerun "
                "with --master-url once identified"
            )
            return 0
        raise ProbeError(
            "No master or manifest URL found. Run capture_resource_urls.py or pass "
            "--master-url/--manifest-url. --base-url and --res-ver only override "
            "a captured URL template; they cannot infer the native manifest path."
        )
    except urllib.error.HTTPError as exc:
        print(f"Download failed: HTTP {exc.code} for {exc.url}")
    except urllib.error.URLError as exc:
        print(f"Download failed: {exc.reason}")
    except (OSError, ProbeError) as exc:
        print(f"Probe failed: {exc}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
