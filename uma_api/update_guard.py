"""Classify game result codes and surface actionable update/auth alerts."""

import json
import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from core.runtime_paths import atomic_write_private_text
from uma_api.errors import ApiError, UnsupportedScenarioError


log = logging.getLogger(__name__)


class Diagnosis(str, Enum):
    OK = "OK"
    VERSION_STALE = "VERSION_STALE"
    RESOURCE_STALE = "RESOURCE_STALE"
    SESSION = "SESSION"
    AUTH_INVALIDATED = "AUTH_INVALIDATED"
    ACCOUNT_UDID_CONFLICT = "ACCOUNT_UDID_CONFLICT"
    PC_ACCOUNT_LIMIT_ERROR = "PC_ACCOUNT_LIMIT_ERROR"
    NO_PLATFORM_USER_ID_ERROR = "NO_PLATFORM_USER_ID_ERROR"
    NO_CHAINED_USER_ID_ERROR = "NO_CHAINED_USER_ID_ERROR"
    STEAM_ACCOUNT_REMOVE_CHAINED = "STEAM_ACCOUNT_REMOVE_CHAINED"
    OBSERVED_STEAM_IDENTITY_REQUIRED = "OBSERVED_STEAM_IDENTITY_REQUIRED"
    UNSUPPORTED_SCENARIO = "UNSUPPORTED_SCENARIO"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"


class GuardError(ApiError):
    """Base for the guard's protocol errors: an :class:`ApiError` built message-first.

    These two are raised from ``UmaClient._call_locked`` for a non-success
    ``result_code`` exactly like a plain ``ApiError``, but their message is
    assembled by the caller (``f'{err_msg} {remedy}'``) rather than by
    ``ApiError``'s default format. The constructor therefore keeps the
    historical single-positional-``message`` signature and takes the structured
    ``result_code``/``endpoint`` as keyword-only extras, so every existing
    ``GuardError("some message")`` call site keeps working unchanged.

    When ``result_code`` is omitted it stays ``None``, and
    :func:`uma_api.errors.api_error_result_code` falls back to regex-parsing the
    message exactly as it did before these classes were typed.
    """

    def __init__(self, message, *, result_code=None, endpoint=None):
        super().__init__(result_code, endpoint, message=message)


class ClientVersionError(GuardError):
    """The server rejected APP-VER and no newer shared value was available."""


class AuthInvalidatedError(GuardError):
    """Saved account auth was invalidated and requires a fresh Steam login."""


_VERSION_REMEDY = (
    "app_ver rejected by server. On a machine WITH the game installed run "
    "`python scripts/publish_client_version.py` (or edit "
    "the selected state root's client_version.json), then restart the bot."
)
_RESOURCE_REMEDY = "res_ver rejected; auto-refreshing from server on next login."
_AUTH_REMEDY = (
    "Account '{account}' auth is invalid (re-registered). Sign in again from "
    "the web UI with Steam; the bot will bootstrap a fresh UDID and save the "
    "returned game auth. If no game account is bound, complete the Trainer-ID "
    "link flow."
)
_AUTH_TRANSIENT_REMEDY = (
    "Overloaded auth/session response; preserve existing retry/recovery behavior."
)
_ACCOUNT_UDID_CONFLICT_REMEDY = (
    "Account/UDID conflict (703). Complete the Steam login / Trainer-ID link flow "
    "with a fresh UDID, then retry."
)
_PC_ACCOUNT_LIMIT_REMEDY = (
    "PC account limit reached (704). Resolve an existing PC account link before "
    "retrying the Steam login / Trainer-ID link flow."
)
_NO_PLATFORM_USER_ID_REMEDY = (
    "No platform user ID is linked (705). Sign in with Steam and complete the "
    "Trainer-ID link flow before retrying."
)
_NO_CHAINED_USER_ID_REMEDY = (
    "No chained user ID is available (708). Restore or create the Steam / "
    "Trainer-ID link before retrying the transition."
)
_STEAM_ACCOUNT_REMOVE_CHAINED_REMEDY = (
    "Steam account remains chained (709). Resolve the existing Steam / Trainer-ID "
    "link before retrying."
)
_OBSERVED_STEAM_IDENTITY_REQUIRED_REMEDY = (
    "Observed result code 390 (symbolic name unconfirmed): the Steam build rejected "
    "load/index when common omitted steam_id and steam_session_ticket. Supply both "
    "fields through Steam login; do not retry with an empty platform identity."
)
_MAINTENANCE_REMEDY = "Server maintenance (101). Bot will wait and retry."


def classify_result_code(rc):
    try:
        code = int(rc)
    except (TypeError, ValueError):
        code = None

    if code == 1:
        return Diagnosis.OK, "Request accepted."
    if code == 204:
        return Diagnosis.VERSION_STALE, _VERSION_REMEDY
    if code == 214:
        return Diagnosis.RESOURCE_STALE, _RESOURCE_REMEDY
    if code in (201, 217):
        return Diagnosis.SESSION, "Session expired; relogin and retry."
    if code == 203:
        return Diagnosis.AUTH_INVALIDATED, _AUTH_REMEDY
    if code == 703:
        return Diagnosis.ACCOUNT_UDID_CONFLICT, _ACCOUNT_UDID_CONFLICT_REMEDY
    if code == 704:
        return Diagnosis.PC_ACCOUNT_LIMIT_ERROR, _PC_ACCOUNT_LIMIT_REMEDY
    if code == 705:
        return Diagnosis.NO_PLATFORM_USER_ID_ERROR, _NO_PLATFORM_USER_ID_REMEDY
    if code == 708:
        return Diagnosis.NO_CHAINED_USER_ID_ERROR, _NO_CHAINED_USER_ID_REMEDY
    if code == 709:
        return Diagnosis.STEAM_ACCOUNT_REMOVE_CHAINED, _STEAM_ACCOUNT_REMOVE_CHAINED_REMEDY
    if code == 390:
        return Diagnosis.OBSERVED_STEAM_IDENTITY_REQUIRED, _OBSERVED_STEAM_IDENTITY_REQUIRED_REMEDY
    if code in (102, 202):
        return Diagnosis.OTHER, _AUTH_TRANSIENT_REMEDY
    if code == 101:
        return Diagnosis.MAINTENANCE, _MAINTENANCE_REMEDY
    return Diagnosis.OTHER, f"Unhandled server result code ({rc})."


def alert_unsupported_scenario(base_dir, account, scenario_id):
    """Surface an unroutable career through the standard terminal-alert path."""
    error = UnsupportedScenarioError(scenario_id)
    return alert_once(
        base_dir,
        account,
        Diagnosis.UNSUPPORTED_SCENARIO,
        str(error),
        extra=f"scenario_id={scenario_id}",
    )


def is_reregistration_signature(expected_viewer_id, data_headers):
    """Return whether headers identify a non-zero guest/mismatched viewer."""
    if not isinstance(data_headers, dict) or "viewer_id" not in data_headers:
        return False

    try:
        response_viewer_id = int(data_headers["viewer_id"])
    except (TypeError, ValueError, OverflowError):
        return False
    if response_viewer_id == 0:
        return False

    try:
        expected = int(expected_viewer_id or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return expected == 0 or response_viewer_id != expected


_ALERTED: set[tuple[str, str]] = set()
_ALERT_LOCK = threading.Lock()


def _diagnosis_name(diagnosis):
    return diagnosis.value if isinstance(diagnosis, Diagnosis) else str(diagnosis)


def _merge_status(base_dir, record):
    """Best-effort durable last-alert state; never interfere with API handling."""
    try:
        path = Path(base_dir) / "update_status.json"
        records = []
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(current, list):
                records = [item for item in current if isinstance(item, dict)]
            elif isinstance(current, dict):
                records = [item for item in current.values() if isinstance(item, dict)]

        records = [
            item for item in records
            if not (
                str(item.get("account") or "") == record["account"]
                and str(item.get("diagnosis") or "") == record["diagnosis"]
            )
        ]
        records.append(record)
        atomic_write_private_text(
            path,
            json.dumps(records, indent=2, ensure_ascii=False, default=str) + "\n",
        )
    # Path(base_dir) (TypeError), exists/read_text/mkdir/write_text (OSError,
    # UnicodeDecodeError/UnicodeEncodeError) and json.loads/json.dumps
    # (JSONDecodeError, circular reference) -- Unicode/JSON errors are ValueError.
    except (OSError, TypeError, ValueError):
        pass


def _default_alert_sink(base_dir, title, message):
    """Post through integrations.discord.notify (the app's Discord channel).

    Imported at CALL time, not module level: notify sits above this transport
    module, so a top-level import would invert the layering (and cycle through
    the API modules). Callers that already own a notifier should pass their own
    `alert_sink` to `alert_once` instead of relying on this fallback.
    """
    from integrations.discord import notify

    notify.send_alert(base_dir, title, message)


def alert_once(base_dir, account, diagnosis, remedy, extra=None, alert_sink=None):
    """Print, persist, and Discord-post one alert per account/diagnosis/process.

    `alert_sink(base_dir, title, message)` overrides where the alert is posted;
    it defaults to `_default_alert_sink` (integrations.discord.notify), preserving the
    historical behavior for the existing callers."""
    account = str(account or "").strip()
    diagnosis_name = _diagnosis_name(diagnosis)
    key = (account, diagnosis_name)
    with _ALERT_LOCK:
        if key in _ALERTED:
            return False
        _ALERTED.add(key)

    record = {
        "account": account,
        "diagnosis": diagnosis_name,
        "remedy": str(remedy or ""),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if extra is not None:
        record["extra"] = extra
    _merge_status(base_dir, record)

    account_text = account or "<unknown>"
    suffix = f" Extra: {extra}" if extra is not None else ""
    log.warning(
        f"UPDATE GUARD [{diagnosis_name}] account={account_text}: {remedy}{suffix}"
    )

    try:
        message = f"Account: {account_text}\n{remedy}"
        if extra is not None:
            message += f"\nDetails: {extra}"
        sink = alert_sink or _default_alert_sink
        sink(base_dir, f"Uma update guard: {diagnosis_name}", message)
    except Exception:
        pass
    return True
