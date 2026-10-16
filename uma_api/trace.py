import gzip
import json
import logging
import os
import shutil
import threading
import time
import uuid
import zlib
from pathlib import Path

import core.operational_time as operational_time
from core.runtime_paths import ensure_private_dir, resolve_state_root, tighten_private_file
from core.settings import Settings
from uma_api.diagnostics import PayloadSerializationFailure


log = logging.getLogger(__name__)

DEFAULT_FLUSH_INTERVAL = 20
_LARGE_RECORD_SPACE_CHECK_BYTES = 1024 * 1024
_TRACE_FILES_LOCK = threading.Lock()
_ACTIVE_TRACE_FILES: set[Path] = set()
_RESERVED_TRACE_FILES: set[Path] = set()


def runtime_output_root():
    return resolve_state_root(Settings.BASE_DIR).root


def _json_default(obj):
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def _json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _trace_files(log_dir):
    return sorted(
        log_dir.glob("*_payloads.jsonl*"),
        key=lambda path: path.stat().st_mtime_ns,
    )


def _prune_trace_files(log_dir, keep, reserve=0):
    """Prune closed traces while leaving in-process active streams untouched."""
    target = max(0, int(keep) - int(reserve))
    try:
        files = _trace_files(log_dir)
        protected = _ACTIVE_TRACE_FILES | _RESERVED_TRACE_FILES
        removable = [path for path in files if path not in protected]
        remove_count = max(0, len(files) - target)
        for path in removable[:remove_count]:
            try:
                path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def release_trace_file(path):
    """Release a closed trace after its notification consumer is finished."""
    if path is None:
        return
    path = Path(path)
    with _TRACE_FILES_LOCK:
        _RESERVED_TRACE_FILES.discard(path)
        _prune_trace_files(path.parent, Settings.UMA_MAX_TRACE_LOGS)


def iter_trace_records(path):
    """Yield complete JSONL records, including the prefix of a truncated gzip."""
    try:
        with gzip.open(Path(path), "rb") as stream:
            while True:
                try:
                    line = stream.readline()
                except Exception:
                    break
                if not line:
                    break
                try:
                    value = json.loads(line)
                except Exception:
                    break
                if isinstance(value, dict):
                    yield value
    except Exception as exc:
        log.warning("Error reading trace log %s: %s", path, exc)


class TraceLog:

    def __init__(self, trace_dir=None, flush_interval=DEFAULT_FLUSH_INTERVAL):
        self.trace_dir = Path(
            trace_dir if trace_dir is not None
            else runtime_output_root() / "trace_logs"
        )
        self.flush_interval = max(1, int(flush_interval))
        self.trace_file = None
        self._raw_file = None
        self._gzip_file = None
        self._records_since_flush = 0
        self._records_since_space_check = 0
        self._write_disabled = False
        self._guard_warning_emitted = False
        self._lock = threading.Lock()

    def initialize(self):
        try:
            log_dir = self.trace_dir / "api_payloads"
            ensure_private_dir(log_dir)
            with _TRACE_FILES_LOCK:
                _prune_trace_files(log_dir, Settings.UMA_MAX_TRACE_LOGS, reserve=1)
                ts = operational_time.utc_filename_stamp()
                suffix = uuid.uuid4().hex[:6]
                path = log_dir / f"{ts}_{suffix}_payloads.jsonl.gz"
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                raw_file = os.fdopen(fd, "wb")
                try:
                    gzip_file = gzip.GzipFile(
                        filename="",
                        mode="wb",
                        compresslevel=6,
                        fileobj=raw_file,
                        mtime=0,
                    )
                except BaseException:
                    raw_file.close()
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    raise
                tighten_private_file(path)
                _ACTIVE_TRACE_FILES.add(path)
                self.trace_file = path
                self._raw_file = raw_file
                self._gzip_file = gzip_file
                self._records_since_flush = 0
                self._records_since_space_check = 0
                self._write_disabled = False
                self._guard_warning_emitted = False
                self._check_storage_limits_locked(check_free_space=True)
            return self.trace_file
        except Exception as exc:
            log.warning("Error initializing trace log: %s", exc)
            self.trace_file = None
            self._raw_file = None
            self._gzip_file = None
            return None

    @staticmethod
    def _record_bytes(direction, ep, data, req_id, data_bytes=None, ts=None):
        if isinstance(data_bytes, PayloadSerializationFailure):
            data_bytes = _json_bytes(data_bytes.marker)
        elif data_bytes is None:
            data_bytes = _json_bytes(data)
        metadata = {
            "ts": time.time() if ts is None else ts,
            "direction": direction,
            "endpoint": ep,
        }
        prefix = _json_bytes(metadata)[:-1] + b',"data":'
        suffix = b""
        if req_id:
            suffix = b',"req_id":' + _json_bytes(req_id)
        return prefix + data_bytes + suffix + b"}\n"

    def _flush_locked(self):
        if self._gzip_file is None or self._raw_file is None:
            return
        self._gzip_file.flush(zlib.Z_SYNC_FLUSH)
        self._raw_file.flush()
        self._records_since_flush = 0

    def _disable_writes_locked(self, reason):
        self._write_disabled = True
        if self._guard_warning_emitted:
            return
        self._guard_warning_emitted = True
        log.warning(
            "trace circuit breaker stopped writes to %s: %s",
            self.trace_file,
            reason,
        )

    def _check_storage_limits_locked(self, check_free_space=False):
        if self._write_disabled or self._raw_file is None:
            return not self._write_disabled
        max_bytes = max(
            0,
            int(getattr(Settings, "UMA_CAREER_API_TRACE_MAX_BYTES", 0)),
        )
        if max_bytes > 0:
            try:
                current_bytes = self._raw_file.tell()
            except (OSError, ValueError):
                current_bytes = 0
            if current_bytes >= max_bytes:
                self._disable_writes_locked(
                    f"active file reached {current_bytes} bytes "
                    f"(limit {max_bytes})",
                )
                return False
        if check_free_space:
            minimum_free = max(
                0,
                int(getattr(
                    Settings,
                    "UMA_CAREER_API_TRACE_MIN_FREE_BYTES",
                    0,
                )),
            )
            self._records_since_space_check = 0
            if minimum_free > 0 and self.trace_file is not None:
                try:
                    free_bytes = shutil.disk_usage(self.trace_file.parent).free
                except OSError:
                    free_bytes = None
                if free_bytes is not None and free_bytes < minimum_free:
                    self._disable_writes_locked(
                        f"only {free_bytes} free bytes remain "
                        f"(floor {minimum_free})",
                    )
                    return False
        return True

    def flush(self):
        with self._lock:
            try:
                self._flush_locked()
            except Exception as exc:
                log.warning("Error flushing trace log: %s", exc)

    def write(self, direction, ep, data, req_id=None, data_bytes=None):
        with self._lock:
            if self._gzip_file is None or self._write_disabled:
                return
            try:
                record_bytes = self._record_bytes(
                    direction,
                    ep,
                    data,
                    req_id,
                    data_bytes,
                    ts=time.time(),
                )
                if not self._check_storage_limits_locked(
                    check_free_space=(
                        len(record_bytes) >= _LARGE_RECORD_SPACE_CHECK_BYTES
                    ),
                ):
                    return
                self._gzip_file.write(record_bytes)
                self._records_since_flush += 1
                self._records_since_space_check += 1
                if self._records_since_flush >= self.flush_interval:
                    self._flush_locked()
                self._check_storage_limits_locked(
                    check_free_space=(
                        self._records_since_space_check >= self.flush_interval
                    ),
                )
            except Exception as exc:
                log.warning("Error writing to trace log: %s", exc)

    def close(self, reserve=False):
        with self._lock:
            path = self.trace_file
            gzip_file = self._gzip_file
            raw_file = self._raw_file
            self._gzip_file = None
            self._raw_file = None
            self._records_since_flush = 0
            self._records_since_space_check = 0
            try:
                if gzip_file is not None:
                    gzip_file.close()
                if raw_file is not None:
                    raw_file.flush()
            except Exception as exc:
                log.warning("Error closing trace log: %s", exc)
            finally:
                if raw_file is not None:
                    try:
                        raw_file.close()
                    except Exception:
                        pass
                if path is not None:
                    with _TRACE_FILES_LOCK:
                        _ACTIVE_TRACE_FILES.discard(path)
                        if reserve:
                            _RESERVED_TRACE_FILES.add(path)
                        _prune_trace_files(
                            path.parent,
                            Settings.UMA_MAX_TRACE_LOGS,
                        )
            return path
