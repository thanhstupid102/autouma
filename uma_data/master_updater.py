"""Headless downloader for Umamusume's current ``master.mdb``.

The CDN manifest chain is made of LZ4-compressed Cyan BSV files.  Two BSV
schemas occur in the chain:

* simplified: ``name\0, size (BE base-128), checksum (BE uint64)``
* full: ``name\0, deps\0, group (varuint), priority (varuint), size
  (varuint), checksum (BE uint64), encryption key (BE int64)``

Unlike every child in the chain, the versioned root manifest is not
content-addressed.  Its client-derived URL is built from the resource-server
base, resource version, and a Unix-seconds cache buster; callers may still
override it when needed.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import os
import socket
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

import lz4.frame

from uma_api import client_version as _client_version
from core.runtime_paths import ensure_private_dir, resolve_state_root

log = logging.getLogger(__name__)


SQLITE_MAGIC = b"SQLite format 3\x00"
BSV_MAGIC = b"\xbf\x11"
SIMPLIFIED_SCHEMA = bytes.fromhex("2518200340122108")
ROOT_SIMPLIFIED_SCHEMA = bytes.fromhex("0318200340122108")
FULL_SCHEMA = bytes.fromhex("013011074040111112210813")
DEFAULT_ROOT_URL_TEMPLATE = (
    "{base}/{res_ver}/manifests/manifestdat/"
    "root.manifest.bsv.lz4?r={timestamp}"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 ManhattanCafeMasterUpdater/1.0"
)
UINT64_MAX = (1 << 64) - 1
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class MasterUpdateError(RuntimeError):
    """Base error for a failed update that left the destination untouched."""


class ManifestFormatError(MasterUpdateError):
    """A downloaded object is not a supported Cyan BSV manifest."""


class DownloadError(MasterUpdateError):
    """A resource could not be downloaded after the configured attempts."""


@dataclass(frozen=True)
class ManifestEntry:
    """One decoded manifest row.

    Simplified manifest-node names are exposed in their meta-database form
    (``//Windows``, ``//master``).  Their hash still uses the encoded BSV name
    without the leading slashes, as the game does.
    """

    name: str
    size: int
    checksum: int
    hname: str
    deps: str = ""
    group: int = 0
    priority: int = 0
    encryption_key: int = 0


@dataclass(frozen=True)
class MasterUpdateResult:
    destination: Path
    old_size: int | None
    new_size: int
    compressed_size: int
    integrity_result: str
    resource_version: str
    root_url: str
    windows_manifest_hname: str
    master_manifest_hname: str
    master_hname: str
    replaced: bool


class _BSVReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise ManifestFormatError(
                f"truncated BSV {field} at byte {self.offset}: "
                f"needed {size}, have {self.remaining}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def read_cstring(self, field: str) -> str:
        end = self.data.find(b"\x00", self.offset)
        if end < 0:
            raise ManifestFormatError(
                f"unterminated BSV {field} at byte {self.offset}"
            )
        raw = self.data[self.offset:end]
        self.offset = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManifestFormatError(
                f"invalid UTF-8 in BSV {field} at byte {exc.start + self.offset - len(raw) - 1}"
            ) from exc

    def read_varuint(self, field: str) -> int:
        """Read Cyan's most-significant-group-first base-128 integer."""

        value = 0
        for _ in range(10):
            byte = self.read(1, field)[0]
            value = (value << 7) | (byte & 0x7F)
            if value > UINT64_MAX:
                raise ManifestFormatError(f"BSV {field} exceeds uint64")
            if not byte & 0x80:
                return value
        raise ManifestFormatError(f"BSV {field} has an overlong base-128 integer")

    def read_uint64(self, field: str) -> int:
        return int.from_bytes(self.read(8, field), "big", signed=False)

    def read_int64(self, field: str) -> int:
        return int.from_bytes(self.read(8, field), "big", signed=True)


def calculate_hname(name: str, checksum: int, size: int) -> str:
    """Return Cyan's unpadded base32 SHA-1 content name."""

    if not isinstance(name, str):
        raise TypeError("name must be a string")
    if not isinstance(checksum, int) or not -(1 << 63) <= checksum <= UINT64_MAX:
        raise ValueError("checksum must fit in 64 bits")
    if not isinstance(size, int) or not 0 <= size <= UINT64_MAX:
        raise ValueError("size must be an unsigned 64-bit integer")
    digest = hashlib.sha1(
        (checksum & UINT64_MAX).to_bytes(8, "big")
        + size.to_bytes(8, "big")
        + name.encode("utf-8")
    ).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")


def parse_manifest(data: bytes | bytearray | memoryview) -> list[ManifestEntry]:
    """Decode a decompressed Cyan BSV manifest used by the CDN chain."""

    raw = bytes(data)
    reader = _BSVReader(raw)
    if reader.read(2, "magic") != BSV_MAGIC:
        raise ManifestFormatError("manifest does not start with Cyan BSV magic bf11")
    schema_size = int.from_bytes(reader.read(2, "schema length"), "big")
    schema = reader.read(schema_size, "schema")
    if schema in {SIMPLIFIED_SCHEMA, ROOT_SIMPLIFIED_SCHEMA}:
        layout: Literal["simplified", "full"] = "simplified"
    elif schema == FULL_SCHEMA:
        layout = "full"
    else:
        raise ManifestFormatError(f"unsupported Cyan BSV schema: {schema.hex()}")

    entries: list[ManifestEntry] = []
    while reader.remaining:
        row_offset = reader.offset
        encoded_name = reader.read_cstring("name")
        if not encoded_name:
            raise ManifestFormatError(f"empty BSV entry name at byte {row_offset}")

        deps = ""
        group = 0
        priority = 0
        encryption_key = 0
        if layout == "full":
            deps = reader.read_cstring("dependencies")
            group = reader.read_varuint("group")
            priority = reader.read_varuint("priority")

        size = reader.read_varuint("size")
        checksum = reader.read_uint64("checksum")
        if layout == "full":
            encryption_key = reader.read_int64("encryption key")

        display_name = f"//{encoded_name}" if layout == "simplified" else encoded_name
        entries.append(
            ManifestEntry(
                name=display_name,
                size=size,
                checksum=checksum,
                hname=calculate_hname(encoded_name, checksum, size),
                deps=deps,
                group=group,
                priority=priority,
                encryption_key=encryption_key,
            )
        )

    if not entries:
        raise ManifestFormatError("Cyan BSV manifest contains no entries")
    return entries


def connection_info_from_start_session(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Extract ``(resource_server_base, resource_version)`` from a response."""

    response: Mapping[str, Any] = payload
    nested = response.get("response")
    if isinstance(nested, Mapping):
        response = nested

    headers = response.get("data_headers")
    data = response.get("data")
    if not isinstance(headers, Mapping) or not isinstance(data, Mapping):
        raise MasterUpdateError(
            "start_session response must contain data_headers and data objects"
        )
    server_list = headers.get("server_list")
    if not isinstance(server_list, Mapping):
        raise MasterUpdateError(
            "start_session response is missing data_headers.server_list"
        )
    base = server_list.get("resource_server")
    resource_version = data.get("resource_version")
    if not isinstance(base, str) or not base.strip():
        raise MasterUpdateError(
            "start_session response is missing server_list.resource_server"
        )
    if not isinstance(resource_version, (str, int)) or not str(resource_version).strip():
        raise MasterUpdateError("start_session response is missing data.resource_version")
    return base.strip(), str(resource_version).strip()


def _normalize_base(resource_server_base: str) -> str:
    base = resource_server_base.strip()
    if not base:
        raise MasterUpdateError("resource server base must not be empty")
    if "://" not in base:
        base = "https://" + base
    parts = urllib.parse.urlsplit(base)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise MasterUpdateError(f"invalid resource server base: {resource_server_base!r}")
    path = parts.path.rstrip("/") + "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _resolve_root_url(root_url: str | None, base: str, resource_version: str) -> str:
    resolved = (
        root_url.strip()
        if root_url and root_url.strip()
        else DEFAULT_ROOT_URL_TEMPLATE
    )
    resolved = resolved.replace("{base}", base.rstrip("/"))
    resolved = resolved.replace(
        "{res_ver}", urllib.parse.quote(resource_version, safe="")
    )
    resolved = resolved.replace("{timestamp}", str(int(time.time())))
    resolved = urllib.parse.urljoin(base, resolved)
    parts = urllib.parse.urlsplit(resolved)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise MasterUpdateError(f"invalid root manifest URL: {resolved!r}")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, "")
    )


def _content_url(base: str, category: str, hname: str) -> str:
    if len(hname) < 2:
        raise MasterUpdateError(f"invalid {category} hash name: {hname!r}")
    return urllib.parse.urljoin(
        base, f"resources/{category}/{hname[:2]}/{hname}"
    )


def _download(url: str, *, timeout: float, attempts: int, label: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.getcode()
                if status != 200:
                    raise DownloadError(f"{label} returned HTTP {status}: {url}")
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in {408, 425, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise DownloadError(
                    f"failed to fetch {label}: HTTP {exc.code} for {url}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
        if attempt < attempts:
            time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))
    detail = str(last_error) if last_error is not None else "unknown network error"
    raise DownloadError(
        f"failed to fetch {label} after {attempts} attempt(s): {detail} ({url})"
    ) from last_error


def _download_to_path(
    url: str,
    destination: Path,
    *,
    timeout: float,
    attempts: int,
    label: str,
) -> int:
    """Stream a large CDN object to an already-private temporary file."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.getcode()
                if status != 200:
                    raise DownloadError(f"{label} returned HTTP {status}: {url}")
                downloaded = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                return downloaded
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in {408, 425, 429} or 500 <= exc.code < 600
            if not retryable or attempt == attempts:
                raise DownloadError(
                    f"failed to fetch {label}: HTTP {exc.code} for {url}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
        if attempt < attempts:
            time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))
    detail = str(last_error) if last_error is not None else "unknown network error"
    raise DownloadError(
        f"failed to fetch {label} after {attempts} attempt(s): {detail} ({url})"
    ) from last_error


def _decompress_manifest(compressed: bytes, label: str) -> list[ManifestEntry]:
    try:
        raw = lz4.frame.decompress(compressed)
    except Exception as exc:
        raise ManifestFormatError(f"{label} is not a valid LZ4 frame: {exc}") from exc
    try:
        return parse_manifest(raw)
    except ManifestFormatError as exc:
        raise ManifestFormatError(f"invalid {label}: {exc}") from exc


def _find_entry(entries: list[ManifestEntry], name: str, label: str) -> ManifestEntry:
    exact = [entry for entry in entries if entry.name == name]
    if len(exact) == 1:
        return exact[0]
    canonical = name.removeprefix("//")
    compatible = [
        entry for entry in entries if entry.name.removeprefix("//") == canonical
    ]
    if len(compatible) == 1:
        return compatible[0]
    available = ", ".join(entry.name for entry in entries[:12])
    raise ManifestFormatError(
        f"{label} does not contain exactly one {name!r} entry "
        f"(found {len(compatible)}; first entries: {available})"
    )


def _fetch_child_manifest(
    base: str,
    entry: ManifestEntry,
    *,
    timeout: float,
    attempts: int,
) -> list[ManifestEntry]:
    url = _content_url(base, "Manifest", entry.hname)
    compressed = _download(
        url, timeout=timeout, attempts=attempts, label=entry.name
    )
    if entry.size and len(compressed) != entry.size:
        raise ManifestFormatError(
            f"{entry.name} compressed size mismatch: manifest says {entry.size}, "
            f"downloaded {len(compressed)}"
        )
    return _decompress_manifest(compressed, entry.name)


def _write_temp_database(data: bytes, destination: Path, dry_run: bool) -> Path:
    if dry_run:
        fd, temp_name = tempfile.mkstemp(
            prefix="manhattancafe-master-", suffix=".mdb"
        )
    else:
        ensure_private_dir(destination.parent)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _create_temp_path(destination: Path, dry_run: bool, suffix: str) -> Path:
    if dry_run:
        fd, temp_name = tempfile.mkstemp(
            prefix="manhattancafe-master-", suffix=suffix
        )
    else:
        ensure_private_dir(destination.parent)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=suffix, dir=destination.parent
        )
    os.close(fd)
    temp_path = Path(temp_name)
    if os.name != "nt":
        os.chmod(temp_path, 0o600)
    return temp_path


def _decompress_database_to_temp(
    compressed_path: Path,
    destination: Path,
    dry_run: bool,
) -> tuple[Path, int]:
    temp_path = _create_temp_path(destination, dry_run, ".mdb.tmp")
    try:
        try:
            with lz4.frame.open(compressed_path, "rb") as source:
                with temp_path.open("wb") as output:
                    prefix = source.read(len(SQLITE_MAGIC))
                    if prefix != SQLITE_MAGIC:
                        raise MasterUpdateError(
                            "decompressed master does not start with SQLite format 3 magic"
                        )
                    output.write(prefix)
                    decompressed_size = len(prefix)
                    while True:
                        chunk = source.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        decompressed_size += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except MasterUpdateError:
            raise
        except OSError as exc:
            raise MasterUpdateError(
                f"could not stream master.mdb.lz4 to a temporary database: {exc}"
            ) from exc
        except Exception as exc:
            raise MasterUpdateError(
                f"master.mdb.lz4 is not a valid LZ4 frame: {exc}"
            ) from exc
        return temp_path, decompressed_size
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _integrity_check(path: Path) -> str:
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as database:
            rows = database.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise MasterUpdateError(f"SQLite validation failed for temporary file: {exc}") from exc
    results = [str(row[0]) for row in rows]
    if results != ["ok"]:
        detail = "; ".join(results[:10]) or "no result"
        raise MasterUpdateError(f"SQLite integrity_check failed: {detail}")
    return results[0]


def fetch_master_mdb(
    resource_server_base: str,
    res_ver: str | int,
    dest_path: str | os.PathLike[str],
    *,
    root_url: str | None = None,
    dry_run: bool = False,
    timeout: float = 30.0,
    retries: int = 3,
) -> MasterUpdateResult:
    """Walk the CDN manifest chain and safely update ``dest_path``.

    When supplied, ``root_url`` overrides the client-derived default and may
    use ``{base}``, ``{res_ver}``, and ``{timestamp}`` placeholders.  A dry run
    downloads, decompresses, and integrity-checks the database but does not
    replace the destination.
    """

    resource_version = str(res_ver).strip()
    if not resource_version:
        raise MasterUpdateError("resource version must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if retries < 0:
        raise ValueError("retries must not be negative")
    attempts = retries + 1

    base = _normalize_base(resource_server_base)
    resolved_root_url = _resolve_root_url(root_url, base, resource_version)
    destination = Path(dest_path).expanduser().resolve()
    if destination.exists() and not destination.is_file():
        raise MasterUpdateError(f"destination is not a regular file: {destination}")
    old_size = destination.stat().st_size if destination.exists() else None

    root_compressed = _download(
        resolved_root_url,
        timeout=timeout,
        attempts=attempts,
        label="root manifest",
    )
    root_entries = _decompress_manifest(root_compressed, "root manifest")
    windows_entry = _find_entry(root_entries, "//Windows", "root manifest")

    windows_entries = _fetch_child_manifest(
        base, windows_entry, timeout=timeout, attempts=attempts
    )
    master_manifest_entry = _find_entry(
        windows_entries, "//master", "//Windows manifest"
    )

    master_entries = _fetch_child_manifest(
        base, master_manifest_entry, timeout=timeout, attempts=attempts
    )
    master_entry = _find_entry(
        master_entries, "master.mdb.lz4", "//master manifest"
    )
    computed_hname = calculate_hname(
        master_entry.name, master_entry.checksum, master_entry.size
    )
    if computed_hname != master_entry.hname:
        raise ManifestFormatError(
            "master.mdb.lz4 hash-name mismatch: "
            f"parsed {master_entry.hname}, computed {computed_hname}"
        )

    master_url = _content_url(base, "Generic", computed_hname)
    compressed_path = _create_temp_path(
        destination, dry_run, ".download.tmp"
    )
    temp_path: Path | None = None
    try:
        compressed_size = _download_to_path(
            master_url,
            compressed_path,
            timeout=timeout,
            attempts=attempts,
            label="master.mdb.lz4",
        )
        if compressed_size != master_entry.size:
            raise MasterUpdateError(
                "master.mdb.lz4 compressed size mismatch: "
                f"manifest says {master_entry.size}, downloaded {compressed_size}"
            )
        temp_path, database_size = _decompress_database_to_temp(
            compressed_path, destination, dry_run
        )
        integrity_result = _integrity_check(temp_path)
        if not dry_run:
            try:
                os.replace(temp_path, destination)
            except OSError as exc:
                raise MasterUpdateError(
                    f"validated master could not atomically replace {destination}: {exc}"
                ) from exc
            temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        compressed_path.unlink(missing_ok=True)

    return MasterUpdateResult(
        destination=destination,
        old_size=old_size,
        new_size=database_size,
        compressed_size=compressed_size,
        integrity_result=integrity_result,
        resource_version=resource_version,
        root_url=resolved_root_url,
        windows_manifest_hname=windows_entry.hname,
        master_manifest_hname=master_manifest_entry.hname,
        master_hname=computed_hname,
        replaced=not dry_run,
    )


def fetch_version_info_headless(
    base_dir,
    app_ver=None,
    *,
    state_root=None,
) -> tuple[str | None, str | None]:
    """Fetch and persist CDN connection details with an unauthenticated client.

    This is deliberately best-effort: a malformed response, unavailable network,
    or unwritable runtime state must not prevent a headless bot from starting.
    ``UmaClient`` stays a local import because it imports career_bot modules of its
    own during initialization.
    """
    try:
        import uuid

        from uma_api.client import UmaClient

        runtime_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(base_dir).root
        )
        resolved_app_ver = str(app_ver or "").strip()
        if not resolved_app_ver:
            resolved_app_ver = str(
                _client_version.get_app_ver(runtime_root) or "1.32.9"
            ).strip()

        # No explicit fingerprint: let UmaClient resolve one itself. The guest
        # then presents this machine's own identity, exactly as it did before
        # device probing became lazy -- a shared constant here would give every
        # install an identical device_id.
        try:
            client = UmaClient(
                {"udid": str(uuid.uuid4()), "app_ver": resolved_app_ver},
                state_root=runtime_root,
            )
        except TypeError as exc:
            if "state_root" not in str(exc):
                raise
            client = UmaClient(
                {"udid": str(uuid.uuid4()), "app_ver": resolved_app_ver}
            )
        client.regen_sid()
        response = client.call("tool/get_pre_download_resource_version", {})

        if not isinstance(response, Mapping):
            raise ValueError("response is not an object")
        data_headers = response.get("data_headers")
        data = response.get("data")
        if not isinstance(data_headers, Mapping) or not isinstance(data, Mapping):
            raise ValueError("response is missing data_headers or data")
        server_list = data_headers.get("server_list")
        if not isinstance(server_list, Mapping):
            raise ValueError("response is missing data_headers.server_list")

        resource_server = server_list.get("resource_server")
        res_ver = data.get("resource_version")
        if not isinstance(resource_server, str) or not resource_server.strip():
            raise ValueError("response is missing resource_server")
        if not isinstance(res_ver, (str, int)) or not str(res_ver).strip():
            raise ValueError("response is missing resource_version")

        resource_server = resource_server.strip()
        res_ver = str(res_ver).strip()
        stored_server = _client_version.set_resource_server(
            runtime_root, resource_server, source="predownload"
        )
        stored_res_ver = _client_version.set_res_ver(
            runtime_root, res_ver, source="predownload"
        )
        if not stored_server or not stored_res_ver:
            raise OSError("could not persist pre-download resource version state")
        return resource_server, res_ver
    except Exception as exc:
        log.warning(f"headless resource version fetch skipped: {exc}")
        return None, None


def ensure_current_headless(base_dir, app_ver=None, *, state_root=None) -> bool:
    """Best-effort guest version lookup followed by the gated master refresh."""
    try:
        resource_server, res_ver = fetch_version_info_headless(
            base_dir,
            app_ver,
            state_root=state_root,
        )
        if resource_server and res_ver:
            return ensure_current(
                base_dir,
                resource_server,
                res_ver,
                state_root=state_root,
            )
    except Exception as exc:
        log.warning(f"headless master.mdb auto-update skipped ({exc})")
    return False


def ensure_current(
    base_dir,
    resource_server,
    res_ver,
    *,
    force=False,
    state_root=None,
) -> bool:
    """Best-effort, gated master.mdb freshness check for the automatic boot/login
    path (uma_api.game_service.login). Unlike fetch_master_mdb(), this NEVER
    raises -- a CDN failure or offline box must not break login; the bot keeps
    running on whatever master.mdb it already has.

    Gating: a `master_res_ver` marker is recorded in the shared
    state-root/client_version.json (client_version.get/set_master_res_ver) each
    time this function actually refreshes the file. A refresh only happens when
    master.mdb is missing at configured_master_mdb_path, the caller-supplied res_ver
    differs from that marker, or `force=True` -- so on the vast majority of logins
    (unchanged RES-VER) this is a single local stat + JSON read, not a network
    call.

    Returns True iff a refresh was attempted AND succeeded (caller should then
    hot-reload uma_data's JSON caches); False for "nothing to do"
    AND for "tried and failed" alike -- callers that need to distinguish should
    call fetch_master_mdb() directly instead.
    """
    resource_server = str(resource_server or "").strip()
    res_ver = str(res_ver or "").strip()
    if not resource_server or not res_ver:
        return False

    # Target the SAME file master_data reads. configured_master_mdb_path honors a
    # settings.json master_data.master_mdb_path override, so a box that relocated
    # master.mdb still gets the refreshed copy where generate() will read it (not
    # the unconfigured Settings.MASTER_MDB_PATH default). Lazy imports: keep this
    # standalone module's Settings/master_data coupling scoped to this function.
    import uma_data as _master_data

    try:
        runtime_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(base_dir).root
        )
        destination = _master_data.configured_master_mdb_path(
            base_dir, runtime_root,
        )
        missing = not destination.is_file()
        stored_res_ver = _client_version.get_master_res_ver(runtime_root)
        needs_refresh = force or missing or (res_ver != stored_res_ver)
        if not needs_refresh:
            return False

        fetch_master_mdb(resource_server, res_ver, destination)
        _client_version.set_master_res_ver(runtime_root, res_ver)
        return True
    except Exception as exc:
        log.warning(f"master.mdb auto-update skipped ({exc})")
        return False
