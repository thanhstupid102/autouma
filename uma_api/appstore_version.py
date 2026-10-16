"""Best-effort APP-VER discovery through Apple's public iTunes lookup API."""

from __future__ import annotations

import logging
import re
import urllib.parse

from curl_cffi import requests

from uma_api import client_version as _client_version


log = logging.getLogger(__name__)

APP_STORE_ID = "6480433538"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
DEFAULT_TIMEOUT = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _print_line(message: str) -> None:
    try:
        log.info(message)
    except Exception:
        pass


def _http_get_json(url, timeout=DEFAULT_TIMEOUT) -> dict | None:
    """Return a decoded JSON object, or ``None`` for any request failure."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def fetch_app_ver_from_store(
    app_id=APP_STORE_ID,
    country="us",
    timeout=DEFAULT_TIMEOUT,
) -> str | None:
    """Fetch and validate an App Store bundle version without authentication."""
    try:
        query = urllib.parse.urlencode(
            (("id", str(app_id)), ("country", str(country)))
        )
        payload = _http_get_json(
            f"{ITUNES_LOOKUP_URL}?{query}", timeout=timeout
        )
        if not isinstance(payload, dict):
            return None

        result_count = payload.get("resultCount")
        results = payload.get("results")
        if (
            not isinstance(result_count, int)
            or result_count < 1
            or not isinstance(results, list)
            or not results
            or not isinstance(results[0], dict)
        ):
            return None

        version = str(results[0].get("version") or "").strip()
        if (
            not _client_version.APP_VERSION_RE.fullmatch(version)
            or _client_version.ENGINE_VERSION_RE.fullmatch(version)
        ):
            return None
        return version
    except Exception:
        return None


def parse_app_id_from_store_url(store_url) -> str | None:
    """Extract ``id<digits>`` from an Apple App Store URL, if present."""
    try:
        if not isinstance(store_url, str):
            return None
        value = store_url.strip()
        lowered = value.lower()
        if not any(
            marker in lowered
            for marker in ("apple.com", "apps.apple.com", "itunes")
        ):
            return None
        match = re.search(r"id(\d+)", value, flags=re.IGNORECASE)
        return match.group(1) if match else None
    except Exception:
        return None


def ensure_app_ver_headless(base_dir, store_url=None) -> str | None:
    """Refresh shared APP-VER state from the App Store without blocking callers."""
    try:
        app_id = (
            parse_app_id_from_store_url(store_url)
            if store_url
            else APP_STORE_ID
        )
        app_id = app_id or APP_STORE_ID
        version = fetch_app_ver_from_store(app_id)
    except Exception as exc:
        _print_line(f"headless app_ver fetch skipped: {exc}")
        return None

    if not version:
        _print_line(
            "headless app_ver fetch skipped: "
            "App Store lookup returned no valid version"
        )
        return None

    try:
        old_version = _client_version.get_app_ver(base_dir)
        if version != old_version:
            if _client_version.set_app_ver(
                base_dir, version, source="appstore"
            ):
                _print_line(
                    f"APP-VER refreshed from App Store: {old_version} -> {version}"
                )
            else:
                _print_line(
                    "headless app_ver refresh skipped: "
                    "could not persist client_version.json"
                )
    except Exception as exc:
        _print_line(f"headless app_ver refresh skipped: {exc}")
    return version
