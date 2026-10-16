import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from uma_api import account_io
from core.runtime_paths import atomic_write_private_text_nondurable


SCHEMA_VERSION = 1


def _safe_account(account: str) -> str:
    if not str(account or "").strip():
        return "default"
    return account_io.safe_account_name(account)


def endpoint_slug(endpoint: str) -> str:
    slug = str(endpoint or "").strip().replace("/", "__")
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", slug).strip(".")
    return slug or "endpoint"


def account_dir(state_root: str | Path, account: str) -> Path:
    return Path(state_root) / "api_warehouse" / _safe_account(account)


def response_path(state_root: str | Path, account: str, endpoint: str) -> Path:
    return account_dir(state_root, account) / f"{endpoint_slug(endpoint)}.json"


def write_latest(state_root: str | Path, account: str, endpoint: str, response: dict) -> Path | None:
    if not str(endpoint or "").strip():
        return None
    try:
        response_dict = response if isinstance(response, dict) else {"data": response}
        headers = response_dict.get("data_headers") or {}
        if not isinstance(headers, dict):
            headers = {}
        safe_account = _safe_account(account)
        slug = endpoint_slug(endpoint)
        record = {
            "schema_version": SCHEMA_VERSION,
            "account": safe_account,
            "endpoint": str(endpoint),
            "endpoint_slug": slug,
            "updated_at": time.time(),
            "response_code": response_dict.get("response_code"),
            "result_code": headers.get("result_code"),
            "data_headers": headers,
            "data": response_dict.get("data"),
        }
        path = response_path(state_root, safe_account, endpoint)
        atomic_write_private_text_nondurable(
            path,
            json.dumps(record, ensure_ascii=False, default=str),
        )
        return path
    # Path building (TypeError on a bad base_dir), mkdir/mkstemp/fdopen/replace
    # (OSError) and json.dump (TypeError on non-str mapping keys, ValueError on a
    # circular reference) are the complete failure set of this body.
    except (OSError, TypeError, ValueError):
        return None


def store_success_response(base_dir, account: str, endpoint: str, response) -> Path | None:
    """Warehouse a response, but only a successful one from a bound client.

    Best-effort by contract: an unbound client (no base dir), a non-dict body, a
    non-`result_code == 1` response or any failure at all is silently skipped --
    warehousing must never affect the call it observed.
    """
    try:
        if not base_dir or not isinstance(response, dict):
            return None
        headers = response.get('data_headers') or {}
        if headers.get('result_code') != 1:
            return None
        return write_latest(base_dir, account, endpoint, response)
    except Exception:
        return None


def read_latest(state_root: str | Path, account: str, endpoint: str, default=None) -> dict | None:
    try:
        path = response_path(state_root, account, endpoint)
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    # Path building (TypeError), open/read (OSError) and json.load (ValueError,
    # which JSONDecodeError and UnicodeDecodeError both subclass).
    except (OSError, TypeError, ValueError):
        return default


def read_latest_data(state_root: str | Path, account: str, endpoint: str, default=None) -> Any:
    record = read_latest(state_root, account, endpoint)
    if not isinstance(record, dict):
        return default
    return record.get("data", default)


def clear_account(state_root: str | Path, account: str) -> bool:
    try:
        path = account_dir(state_root, account)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    # Path building (TypeError) plus exists()/rmtree (OSError); rmtree already
    # runs with ignore_errors=True.
    except (OSError, TypeError):
        return False
