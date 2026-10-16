"""Probe read-only Data Link routes without changing account state.

The recovered DTOs establish the Data Link request family but not its HTTP route
strings.  The normal mode logs in, verifies the session with a known read-only
endpoint, then compares candidate ``*/index`` spellings with an intentionally
bad payload to distinguish these questions:

* H1: ``102`` identifies an unknown route, so every candidate spelling is wrong.
* H2: ``102`` is the generic invalid-request response, so it gives no route data.
* H3: a route must be called after ``tool/start_session`` but before ``load/index``.

``--pre-index`` tests H3 by making the candidate calls immediately after
``tool/start_session``.  It never calls transfer, chain, disconnect, signup, or
pre-signup endpoints; does not persist account or client state; and redacts
credentials from stdout and optional reports.  Every ``chain_*`` endpoint is
deliberately absent from this script.

``--transition-preview UID`` performs the single read-only transition preview
after a normal login.  Its link password is read only from ``UMA_LINK_PASSWORD``
and is never accepted as an argument, printed, or written to a report.  The
data-transfer commit endpoint is deliberately absent from this script.

``--social-preview`` performs one read-only Steam social-account lookup after a
normal login.  It compares the returned account identifier only in memory and
reports whether it matches the logged-in account, never the identifier itself.

Usage:
    python scripts/probe_data_link.py --account yuko
    python scripts/probe_data_link.py --account yuko --pre-index
    python scripts/probe_data_link.py --account yuko --social-preview
    python scripts/probe_data_link.py --account yuko --dry-run
    python scripts/probe_data_link.py --account yuko --report uma_runtime/data_link_probe.json
"""
import argparse
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "uma_runtime"
sys.path.insert(0, str(ROOT))

from backend.app.domain.account_store import (  # noqa: E402
    load_account_config,
    load_steam_token,
)
from uma_api import client as client_module  # noqa: E402
from uma_api import update_guard  # noqa: E402
from uma_api.client import UmaClient  # noqa: E402
from uma_api.errors import api_error_result_code  # noqa: E402
from uma_api.steam_auth import get_ticket  # noqa: E402


SDK_VERSION = "v2"
USER_ID_MIN = 9
USER_ID_LIMIT = 12
LOGIN_ENDPOINTS = frozenset({"tool/start_session", "load/index"})
# `account/index` is the real route for DataLinkIndexRequest, recovered as a
# literal from the game's own global-metadata.dat (the il2cpp type dump carries
# no string literals, which is why every name-derived guess below returned the
# generic 102). The server controller is `account`, not `data_link` -- the same
# class-name/route mismatch as RecoveryTrainerPointRequest -> user/...
# The remaining entries are kept as controls: they must all still return 102.
# Only read-only routes are listed so this script stays incapable of mutating
# the account.
CANDIDATE_ROUTES = (
    "account/index",
    "data_link/index",
    "tool/data_link_index",
    "data_link/publish_index",
)
EXPECTED_NONSENSE_ROUTES = frozenset({
    "tool/data_link_index",
    "data_link/publish_index",
})
CONTROL_ENDPOINTS = frozenset({
    "mission/index",
    "present/index",
    "note/index",
    "pre_single_mode/index",
})
TRANSITION_PREVIEW_ENDPOINT = "account/get_by_transition_code"
TRANSITION_PREVIEW_RESULT_NAMES = {
    1: "SUCCESS",
    102: "102_GUEST",
    516: "TRANSITION_OLD_ACCESS_ERROR",
    517: "TRANSITION_COMPLETED_ERROR",
    526: "TRANSITION_USER_NOT_EXIST",
    700: "TRANSITIONPASSWORD_INVALID",
    701: "TRANSITION_USERID_INVALID",
    703: "ACCOUNT_UDID_CONFLICT",
    902: "MAINTENANCE_TASK_DATA_LINKAGE",
}
SOCIAL_PREVIEW_ENDPOINT = "account/get_by_social_account"
SOCIAL_PREVIEW_RESULT_NAMES = {
    **TRANSITION_PREVIEW_RESULT_NAMES,
    1055: "STEAM_ACCOUNT_MISMATCH_SUSPECTED",
}
TRANSITION_PREVIEW_REJECTION_CODES = frozenset(
    TRANSITION_PREVIEW_RESULT_NAMES
) - frozenset({1, 102})
DISPATCH_CONFIRMED_RESULT_CODES = frozenset({101, 204, 214, 902})
ALLOWED_ENDPOINTS = (
    LOGIN_ENDPOINTS
    | CONTROL_ENDPOINTS
    | frozenset(CANDIDATE_ROUTES)
    | frozenset({TRANSITION_PREVIEW_ENDPOINT, SOCIAL_PREVIEW_ENDPOINT})
)
SENSITIVE_KEYS = frozenset({
    "authkey",
    "udid",
    "sid",
    "viewerid",
    "steamsessionticket",
    "ticket",
    "refreshtoken",
    "steamid",
    "clientid",
    "userpoolid",
    "password",
    "inputviewerid",
    "targetviewerid",
    "openid",
    "authenticationtoken",
})
PRINTABLE_CONFIG_KEYS = frozenset({
    "opendate",
    "appid",
    "lastaccounttype",
    "languagecode",
    "cygamesidclientsdkversion",
    "name",
    "requestusername",
})
HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


class RequestLimitExceeded(RuntimeError):
    """Prevent a client-internal retry from sending a second wire request."""


class _NoWaitRetryPolicy:
    """Retried client control flow must not sleep after the wire cap rejects it."""

    def backoff_sleep(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def server_sleep(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _SingleAttemptSession:
    """Proxy a session with fixed per-endpoint wire-request budgets."""

    def __init__(self, session: Any, calls_by_route: dict[str, int],
                 request_caps: dict[str, int]) -> None:
        self._session = session
        self._calls_by_route = calls_by_route
        self._request_caps = request_caps

    @property
    def headers(self) -> Any:
        return self._session.headers

    def close(self) -> None:
        self._session.close()

    def post(self, url: str, *args: Any, **kwargs: Any) -> Any:
        # Longest match preserves nested routes such as tool/data_link/index.
        matches = [route for route in ALLOWED_ENDPOINTS if url.endswith("/" + route)]
        if not matches:
            raise RuntimeError("refusing transport endpoint outside the read-only allowlist")
        route = max(matches, key=len)
        count = self._calls_by_route.get(route, 0)
        request_cap = self._request_caps.get(route, 1)
        if count >= request_cap:
            raise RequestLimitExceeded("request limit reached for " + route)
        self._calls_by_route[route] = count + 1
        return self._session.post(url, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe read-only Data Link routes, a transition preview, or a social preview.",
    )
    parser.add_argument("--account", default="yuko", help="Account name (default: yuko).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log in and show the resolved request envelope without probing routes.",
    )
    parser.add_argument(
        "--control",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the known-real control before candidates or the transition preview.",
    )
    parser.add_argument(
        "--control-endpoint",
        default="mission/index",
        metavar="NAME",
        help="Known-real read-only endpoint for the controls (default: mission/index).",
    )
    parser.add_argument(
        "--bad-payload-control",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Call the control endpoint with one invalid extra field (default: enabled).",
    )
    parser.add_argument(
        "--pre-index",
        action="store_true",
        help="Probe after tool/start_session and before load/index.",
    )
    parser.add_argument(
        "--transition-preview",
        metavar="UID",
        help="Preview a transition link for the Trainer ID without transferring data.",
    )
    parser.add_argument(
        "--social-preview",
        action="store_true",
        help="Look up the logged-in Steam identity without changing account links.",
    )
    parser.add_argument(
        "--openid-type",
        type=int,
        default=5,
        metavar="TYPE",
        help="Social ACCOUNT_TYPE for --social-preview: 0-7 (default: 5, STEAM).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON report path under uma_runtime/ (never accounts/).",
    )
    args = parser.parse_args()
    args.account = args.account.strip()
    if not args.account:
        parser.error("--account must not be empty")
    if not 0 <= args.openid_type <= 7:
        parser.error("--openid-type must be an integer from 0 through 7")
    if args.social_preview:
        if args.transition_preview is not None:
            parser.error("--social-preview cannot be used with --transition-preview")
        if args.pre_index:
            parser.error("--social-preview cannot be used with --pre-index")
        if args.dry_run:
            parser.error("--dry-run cannot be used with --social-preview")
    if args.transition_preview is not None:
        if (
            re.fullmatch(r"[0-9]+", args.transition_preview) is None
            or not USER_ID_MIN <= len(args.transition_preview) <= USER_ID_LIMIT
        ):
            parser.error(
                "--transition-preview UID must contain only digits and be "
                f"{USER_ID_MIN}-{USER_ID_LIMIT} digits long"
            )
        if args.dry_run:
            parser.error("--dry-run cannot be used with --transition-preview")
        if args.pre_index:
            parser.error("--pre-index cannot be used with --transition-preview")
    args.control_endpoint = args.control_endpoint.strip()
    if args.control_endpoint not in CONTROL_ENDPOINTS:
        choices = ", ".join(sorted(CONTROL_ENDPOINTS))
        parser.error(f"--control-endpoint must be one of: {choices}")
    if args.report is not None:
        args.report = _safe_report_path(args.report, parser)
    return args


def _transition_preview_password() -> str | None:
    """Read and validate the preview password without ever exposing its value."""
    password = os.environ.get("UMA_LINK_PASSWORD")
    if not password:
        print(
            "UMA_LINK_PASSWORD is missing or empty. Set it for one command before "
            "using --transition-preview.",
            flush=True,
        )
        return None

    failures: list[str] = []
    if not re.fullmatch(r"[0-9a-zA-Z]+", password):
        failures.append("must contain only ASCII letters and digits")
    if not 8 <= len(password) <= 16:
        failures.append("must be 8-16 characters long")
    if re.search(r"[0-9]", password) is None:
        failures.append("must contain at least one digit")
    if re.search(r"[a-z]", password) is None:
        failures.append("must contain at least one lowercase letter")
    if re.search(r"[A-Z]", password) is None:
        failures.append("must contain at least one uppercase letter")
    if failures:
        print(
            "UMA_LINK_PASSWORD is invalid: " + "; ".join(failures) + ".",
            flush=True,
        )
        return None
    return password


def _safe_report_path(value: Path, parser: argparse.ArgumentParser) -> Path:
    path = value if value.is_absolute() else ROOT / value
    path = path.resolve()
    try:
        relative = path.relative_to(RUNTIME_DIR.resolve())
    except ValueError:
        parser.error("--report must be under uma_runtime/")
    if relative.parts and relative.parts[0].casefold() == "accounts":
        parser.error("--report may not write under uma_runtime/accounts/")
    return path


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def _value_length(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return len(str(value))


def _type_name(value: Any) -> str:
    if value is None:
        return "NoneType"
    return type(value).__name__


def _redacted_shapes(value: Any, key: Any = "") -> Any:
    """Describe a response without exposing values outside the approved config set."""
    normalized = _normalized_key(key)
    if normalized in SENSITIVE_KEYS:
        return f"<redacted: {_type_name(value)}, len={_value_length(value)}>"
    if normalized in PRINTABLE_CONFIG_KEYS:
        return {"type": _type_name(value), "value": value}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "keys": sorted(str(item) for item in value),
            "fields": {str(item): _redacted_shapes(item_value, item)
                       for item, item_value in value.items()},
        }
    if isinstance(value, list):
        item_shapes = [_redacted_shapes(item) for item in value[:3]]
        return {"type": "list", "len": len(value), "item_shapes": item_shapes}
    if isinstance(value, tuple):
        return {"type": "tuple", "len": len(value)}
    if isinstance(value, str):
        return {"type": "str", "len": len(value)}
    if isinstance(value, bytes):
        return {"type": "bytes", "len": len(value)}
    return {"type": _type_name(value)}


def _response_keys(response: Any) -> list[str]:
    return sorted(str(key) for key in response) if isinstance(response, dict) else []


def _result_code(response: Any) -> int | None:
    headers = _data_headers(response)
    if headers is None:
        return None
    try:
        return int(headers.get("result_code"))
    except (TypeError, ValueError):
        return None


def _data_headers(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    headers = response.get("data_headers")
    if not isinstance(headers, dict):
        return None
    return headers


def _has_empty_sid(response: Any) -> bool:
    headers = _data_headers(response)
    if headers is None or "sid" not in headers:
        return False
    sid = headers["sid"]
    return isinstance(sid, (str, bytes, bytearray)) and len(sid) == 0


def _classify_probe_result(expected_viewer_id: Any, response: Any,
                           result_code: int | None, error: BaseException | None,
                           http_status: int | None) -> tuple[str, str]:
    """Classify a result without treating generic API errors as route evidence."""
    if result_code == 1:
        return "ACCEPTED", "result_code=1; request accepted"

    headers = _data_headers(response)
    if (
        result_code in (102, 202)
        and update_guard.is_reregistration_signature(expected_viewer_id, headers)
        and _has_empty_sid(response)
    ):
        return (
            "INCONCLUSIVE_GUEST",
            "no route information - this is the generic guest/invalid response",
        )

    if result_code in DISPATCH_CONFIRMED_RESULT_CODES:
        return (
            "ROUTE_OK_BUT_REJECTED",
            f"result_code={result_code}; response proves route dispatch",
        )

    if result_code is not None:
        return (
            "INCONCLUSIVE_RESULT_CODE",
            f"result_code={result_code}; response does not prove route dispatch",
        )

    if error is not None and _is_route_not_found(error, http_status):
        return "ROUTE_BAD", _safe_error_message(error, http_status)
    if error is not None:
        return "ERROR", _safe_error_message(error, http_status)
    return "ERROR", "response did not include a result_code"


def _response_record(endpoint: str, expected_viewer_id: Any, response: Any,
                     error: BaseException | None, http_status: int | None) -> dict[str, Any]:
    result_code = _result_code(response)
    if response is not None and http_status is None:
        # UmaClient only emits a decoded response after a successful HTTP response.
        http_status = 200
    classification, message = _classify_probe_result(
        expected_viewer_id, response, result_code, error, http_status,
    )
    return {
        "endpoint": endpoint,
        "classification": classification,
        "message": message,
        "http_status": http_status,
        "result_code": result_code,
        "response_keys": _response_keys(response),
        "redacted_shapes": _redacted_shapes(response),
        "safe_config": _safe_config_values(response),
    }


def _find_field_shapes(value: Any, wanted_key: str, path: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if _normalized_key(key) == _normalized_key(wanted_key):
                findings.append({"path": item_path, "shape": _redacted_shapes(item, key)})
            findings.extend(_find_field_shapes(item, wanted_key, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_field_shapes(item, wanted_key, f"{path}[{index}]"))
    return findings


def _start_session_findings(response: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {"response_captured": isinstance(response, dict)}
    for name in ("auth_key", "attest", "nonce"):
        locations = _find_field_shapes(response, name) if isinstance(response, dict) else []
        fields[name] = {"present": bool(locations), "locations": locations}
    return fields


def _print_start_session_findings(findings: dict[str, Any]) -> None:
    print("tool/start_session field findings:", flush=True)
    if not findings["response_captured"]:
        print("  response: unavailable", flush=True)
        return
    for name in ("auth_key", "attest", "nonce"):
        field = findings[name]
        if not field["present"]:
            print(f"  {name}: absent", flush=True)
            continue
        shapes = ", ".join(
            f"{entry['path']}={json.dumps(entry['shape'], ensure_ascii=True)}"
            for entry in field["locations"]
        )
        print(f"  {name}: present ({shapes})", flush=True)


def _extract_http_status(error: BaseException, observed_status: int | None) -> int | None:
    if observed_status is not None:
        return observed_status
    match = HTTP_STATUS_RE.search(str(error))
    return int(match.group(1)) if match else None


def _safe_error_message(error: BaseException, http_status: int | None) -> str:
    """Keep required error messages useful without exposing an HTTP response body."""
    if http_status is not None:
        return f"HTTP {http_status}"
    if isinstance(error, RequestLimitExceeded):
        return str(error)
    return "details suppressed to avoid printing possible credential data"


def _is_route_not_found(error: BaseException, http_status: int | None) -> bool:
    if http_status in (403, 404):
        return True
    message = str(error).casefold()
    return "route not found" in message or "no route" in message


def _safe_config_values(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value for key, value in data.items()
        if _normalized_key(key) in PRINTABLE_CONFIG_KEYS
    }


def _print_response_shape(record: dict[str, Any]) -> None:
    print(f"  response keys: {record['response_keys']}", flush=True)
    print(
        "  redacted shapes: "
        + json.dumps(record["redacted_shapes"], ensure_ascii=True, sort_keys=True),
        flush=True,
    )
    config = record.get("safe_config", {})
    if config:
        print("  non-sensitive config: " + json.dumps(config, ensure_ascii=True), flush=True)


def _print_endpoint_result(label: str, record: dict[str, Any],
                           response_captured: bool) -> None:
    result_code = record["result_code"]
    result_text = f"result_code={result_code}" if result_code is not None else "result_code=unavailable"
    http_status = record["http_status"]
    http_text = f", HTTP {http_status}" if http_status is not None else ""
    print(
        f"{label}: {record['endpoint']} ({result_text}{http_text}; "
        f"{record['classification']}: {record['message']})",
        flush=True,
    )
    if response_captured:
        _print_response_shape(record)


def _transition_preview_result_text(result_code: int | None) -> str:
    if result_code is None:
        return "result_code=unavailable"
    name = TRANSITION_PREVIEW_RESULT_NAMES.get(result_code, "UNKNOWN_RESULT_CODE")
    return f"result_code={result_code} ({name})"


def _transition_preview_message(result_code: int | None) -> str:
    if result_code == 1:
        return "preview accepted"
    if result_code == 700:
        return "server rejected the link password"
    if result_code == 701:
        return "server rejected the Trainer ID"
    if result_code == 102:
        return "generic guest/invalid response; preview is inconclusive"
    if result_code in TRANSITION_PREVIEW_REJECTION_CODES:
        return "server rejected the transition preview"
    return "preview response could not be interpreted"


def _print_transition_preview_result(record: dict[str, Any], response: Any) -> None:
    result_text = _transition_preview_result_text(record["result_code"])
    http_status = record["http_status"]
    http_text = f", HTTP {http_status}" if http_status is not None else ""
    print(
        f"TRANSITION PREVIEW: {record['endpoint']} ({result_text}{http_text}; "
        + _transition_preview_message(record["result_code"])
        + ")",
        flush=True,
    )
    if response is not None:
        _print_response_shape(record)
    if record["result_code"] != 1:
        return
    data = response.get("data") if isinstance(response, dict) else None
    for field in ("name", "request_user_name"):
        if isinstance(data, dict) and field in data:
            print(f"  {field}: {data[field]}", flush=True)
        else:
            print(f"  {field}: unavailable", flush=True)


def _transition_preview_verdict(result_code: int | None) -> tuple[str, int]:
    if result_code == 1:
        return "PREVIEW_OK", 0
    if result_code in TRANSITION_PREVIEW_REJECTION_CODES:
        return f"PREVIEW_REJECTED | {TRANSITION_PREVIEW_RESULT_NAMES[result_code]}", 1
    if result_code == 102:
        return "PREVIEW_INCONCLUSIVE | 102_GUEST", 1
    if result_code is None:
        return "PREVIEW_INCONCLUSIVE | RESULT_CODE_UNAVAILABLE", 1
    return f"PREVIEW_INCONCLUSIVE | RESULT_CODE_{result_code}", 1


def _social_preview_result_text(result_code: int | None) -> str:
    if result_code is None:
        return "result_code=unavailable"
    name = SOCIAL_PREVIEW_RESULT_NAMES.get(result_code)
    if name is None:
        return f"result_code={result_code} (unmapped)"
    return f"result_code={result_code} ({name})"


def _is_social_preview_guest_response(expected_viewer_id: Any, response: Any,
                                      result_code: int | None) -> bool:
    return (
        result_code == 102
        and update_guard.is_reregistration_signature(
            expected_viewer_id, _data_headers(response),
        )
        and _has_empty_sid(response)
    )


def _social_preview_message(expected_viewer_id: Any, response: Any,
                            result_code: int | None) -> str:
    if result_code == 1:
        return "social-account lookup accepted"
    if _is_social_preview_guest_response(expected_viewer_id, response, result_code):
        return (
            "generic invalid/unknown-route response; the empty sid plus guest "
            "viewer_id signature means route dispatch is inconclusive"
        )
    if result_code == 102:
        return "generic invalid/unknown-route code without the verified empty-sid guest signature"
    if result_code == 1055:
        return "STEAM_ACCOUNT_MISMATCH_SUSPECTED is inferred from this code, not confirmed"
    if result_code is None:
        return "response did not include a result code"
    if result_code not in SOCIAL_PREVIEW_RESULT_NAMES:
        return "unmapped result code"
    return "server rejected the social-account lookup"


def _decimal_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value)
    return text if re.fullmatch(r"[0-9]+", text) else None


def _social_preview_summary(expected_viewer_id: Any, response: Any) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        data = {}
    returned_viewer_id = _decimal_text(data.get("viewer_id"))
    own_viewer_id = _decimal_text(expected_viewer_id)
    return {
        "matches_this_account": (
            returned_viewer_id is not None
            and own_viewer_id is not None
            and returned_viewer_id == own_viewer_id
        ),
        "viewer_id_digit_length": len(returned_viewer_id) if returned_viewer_id else 0,
        "is_chained": data.get("is_chained"),
        "is_chained_meaning": "non-zero = this social identity is already bound to a game account",
        "name": data.get("name"),
        "request_user_name": data.get("request_user_name"),
    }


def _print_social_preview_result(expected_viewer_id: Any, record: dict[str, Any],
                                 response: Any, summary: dict[str, Any]) -> None:
    result_text = _social_preview_result_text(record["result_code"])
    http_status = record["http_status"]
    http_text = f", HTTP {http_status}" if http_status is not None else ""
    print(
        f"SOCIAL PREVIEW: {record['endpoint']} ({result_text}{http_text}; "
        + _social_preview_message(expected_viewer_id, response, record["result_code"])
        + ")",
        flush=True,
    )
    if response is not None:
        _print_response_shape(record)
    if record["result_code"] != 1:
        return
    matches = "true" if summary["matches_this_account"] else "false"
    print(f"  matches_this_account: {matches}", flush=True)
    print(f"  viewer_id_digit_length: {summary['viewer_id_digit_length']}", flush=True)
    print(
        f"  is_chained: {summary['is_chained'] if summary['is_chained'] is not None else 'unavailable'} "
        f"({summary['is_chained_meaning']})",
        flush=True,
    )
    for field in ("name", "request_user_name"):
        value = summary[field]
        print(f"  {field}: {value if value is not None else 'unavailable'}", flush=True)


def _social_preview_verdict(expected_viewer_id: Any, record: dict[str, Any],
                            response: Any, summary: dict[str, Any]) -> tuple[str, int]:
    result_code = record["result_code"]
    if result_code == 1:
        account_result = "MATCHES_THIS_ACCOUNT" if summary["matches_this_account"] else "DIFFERENT_ACCOUNT"
        return f"SOCIAL_PREVIEW_OK | {account_result}", 0
    if _is_social_preview_guest_response(expected_viewer_id, response, result_code):
        return "SOCIAL_PREVIEW_INCONCLUSIVE | 102_GUEST", 1
    if result_code is None:
        return "SOCIAL_PREVIEW_REJECTED | RESULT_CODE_UNAVAILABLE", 1
    return (
        "SOCIAL_PREVIEW_REJECTED | "
        + SOCIAL_PREVIEW_RESULT_NAMES.get(result_code, str(result_code)),
        1,
    )


def _silence_sensitive_dependency_logs() -> None:
    """The transport may log raw HTTP bodies; this probe reports safe summaries."""
    for logger_name in ("uma_api.client", "uma_api.steam_auth", "uma_api.update_guard"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False
        logger.addHandler(logging.NullHandler())


def _write_report(path: Path | None, report: dict[str, Any]) -> bool:
    if path is None:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        print("REPORT ERROR: could not write the requested report path", flush=True)
        return False
    print(f"Report written: {path}", flush=True)
    return True


def _finish(path: Path | None, report: dict[str, Any], status: int) -> int:
    if not _write_report(path, report):
        status = 1
    print(f"VERDICT: {report['verdict']}", flush=True)
    return status


def _ticket_or_exit(account: str) -> tuple[str, str] | None:
    token_data = load_steam_token(account)
    refresh_token = token_data.get("refresh_token") if isinstance(token_data, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        print("Steam ticket unavailable: no stored refresh_token for this account.", flush=True)
        return None
    if shutil.which("node") is None or not (ROOT / "node_modules").is_dir():
        print("Steam ticket unavailable: node and installed project dependencies are required.", flush=True)
        return None
    try:
        steam_id, ticket, _unused_refresh_token = get_ticket(refresh_token=refresh_token)
        return str(steam_id), str(ticket)
    except Exception as error:
        message = str(error)
        if "TOKEN_INVALID" in message:
            print("Steam ticket unavailable: TOKEN_INVALID. Refresh the Steam login, then rerun.", flush=True)
        elif "STEAM_GUARD_REQUIRED" in message:
            print("Steam ticket unavailable: STEAM_GUARD_REQUIRED. Complete Steam Guard, then rerun.", flush=True)
        else:
            print(
                "Steam ticket unavailable: " + type(error).__name__
                + "; details suppressed to protect credentials.",
                flush=True,
            )
        return None


def _close_client(client: UmaClient | None) -> None:
    if client is None:
        return
    try:
        client.session.close()
    except Exception:
        pass


def _observe_allowed_api_log(
    direction: str,
    endpoint: str,
    data: Any,
    captured_responses: dict[str, list[Any]],
    observed_http_status: dict[str, list[int]],
) -> None:
    if endpoint not in ALLOWED_ENDPOINTS:
        return
    if direction == "RES" and isinstance(data, dict):
        captured_responses.setdefault(endpoint, []).append(data)
    elif direction == "ERR" and isinstance(data, dict):
        try:
            observed_http_status.setdefault(endpoint, []).append(int(data["http_status"]))
        except (KeyError, TypeError, ValueError):
            pass


def main() -> int:
    args = _parse_args()
    transition_password = _transition_preview_password() if args.transition_preview else None
    if args.transition_preview and transition_password is None:
        return 2
    _silence_sensitive_dependency_logs()
    control_timing = (
        "after_login_before_social_preview"
        if args.social_preview
        else "after_login_before_preview"
        if args.transition_preview
        else "after_candidates" if args.pre_index else "after_login_before_candidates"
    )
    report: dict[str, Any] = {
        "account": args.account,
        "dry_run": args.dry_run,
        "pre_index": args.pre_index,
        "start_session": _start_session_findings(None),
        "control": {
            "enabled": args.control,
            "bad_payload_enabled": args.bad_payload_control,
            "endpoint": args.control_endpoint,
            "timing": control_timing,
            "normal": None,
            "bad_payload": None,
        },
        "candidates": [],
        "verdict": "NO_ROUTE_FOUND",
    }
    if args.transition_preview:
        # The report deliberately retains only request field names, never values.
        report["transition_preview"] = {
            "endpoint": TRANSITION_PREVIEW_ENDPOINT,
            "request_fields": ["input_viewer_id", "password"],
            "response": None,
        }
    if args.social_preview:
        # The report deliberately retains only request field names, never credentials.
        report["social_preview"] = {
            "endpoint": SOCIAL_PREVIEW_ENDPOINT,
            "request_fields": [
                "openid",
                "openid_type",
                "authentication_token",
                "not_return_error",
            ],
            "openid_type": str(args.openid_type),
            "not_return_error": True,
            "response": None,
            "result": None,
        }

    stored_cfg = load_account_config(args.account)
    if not isinstance(stored_cfg, dict):
        print(f"Account config not found or invalid for: {args.account}", flush=True)
        return _finish(args.report, report, 1)

    steam_credentials = _ticket_or_exit(args.account)
    if steam_credentials is None:
        return _finish(args.report, report, 1)
    steam_id, steam_ticket = steam_credentials
    cfg = dict(stored_cfg)
    cfg["account_name"] = args.account
    cfg["steam_id"] = steam_id
    cfg["steam_session_ticket"] = steam_ticket

    calls_by_route: dict[str, int] = {}
    request_caps = {args.control_endpoint: 2} if args.control and args.bad_payload_control else {}
    captured_responses: dict[str, list[Any]] = {}
    observed_http_status: dict[str, list[int]] = {}
    original_session_factory = client_module.requests.Session
    original_alert_once = update_guard.alert_once

    def make_single_attempt_session(*session_args: Any, **session_kwargs: Any) -> _SingleAttemptSession:
        return _SingleAttemptSession(
            original_session_factory(*session_args, **session_kwargs), calls_by_route, request_caps,
        )

    def observe_api_log(direction: str, endpoint: str, data: Any, _request_id: Any) -> None:
        _observe_allowed_api_log(
            direction,
            endpoint,
            data,
            captured_responses,
            observed_http_status,
        )

    client: UmaClient | None = None
    try:
        # login() replaces its Session, so patch the factory before constructing it.
        client_module.requests.Session = make_single_attempt_session
        # alert_once writes update_status.json and can notify Discord; neither is part
        # of a read-only probe. The script prints classify_result_code() itself.
        update_guard.alert_once = lambda *_args, **_kwargs: False
        client = UmaClient(cfg, trace_enabled=False)
        client.retry_policy = _NoWaitRetryPolicy()
        client.on_api_log = observe_api_log

        def refresh_resource_version_in_memory(data_headers: Any) -> bool:
            previous = client.res_ver
            value = data_headers.get("resource_version") if isinstance(data_headers, dict) else None
            if isinstance(value, str) and value.strip():
                client.res_ver = value.strip()
            return client.res_ver != previous

        # The normal hook persists tool/start_session version headers. Keep the
        # useful in-memory update while preserving this script's no-write guarantee.
        client._refresh_resource_version = refresh_resource_version_in_memory
        original_call = client.call

        def call_only_allowed_once(endpoint: str, payload: dict[str, Any] | None = None,
                                   **_ignored: Any) -> dict[str, Any]:
            if endpoint not in ALLOWED_ENDPOINTS:
                raise RuntimeError("refusing endpoint outside the read-only allowlist")
            return original_call(
                endpoint,
                payload,
                retry_208=0,
                retry_205=0,
                retry_500=0,
                _ver_retry=True,
            )

        # This makes signup/pre_signup and every other non-allowlisted call fail
        # before transport, including any future change to UmaClient.login().
        client.call = call_only_allowed_once
        if not client.has_game_auth():
            print("LOGIN FAILED: account lacks complete captured game auth; refusing signup.", flush=True)
            return _finish(args.report, report, 1)

        def response_after(endpoint: str, previous_count: int) -> Any:
            responses = captured_responses.get(endpoint, [])
            return responses[previous_count] if len(responses) > previous_count else None

        def http_status_after(endpoint: str, previous_count: int) -> int | None:
            statuses = observed_http_status.get(endpoint, [])
            return statuses[previous_count] if len(statuses) > previous_count else None

        def call_and_record(endpoint: str, payload: dict[str, Any] | None) -> tuple[dict[str, Any], Any]:
            response_count = len(captured_responses.get(endpoint, []))
            status_count = len(observed_http_status.get(endpoint, []))
            response: Any = None
            error: BaseException | None = None
            try:
                response = client.call(endpoint, payload)
            except Exception as caught:
                error = caught
                response = response_after(endpoint, response_count)
            http_status = http_status_after(endpoint, status_count)
            record = _response_record(
                endpoint, client.viewer_id, response, error, http_status,
            )
            if record["result_code"] is None and error is not None:
                result_code = api_error_result_code(error)
                if result_code is not None:
                    record["result_code"] = result_code
                    classification, message = _classify_probe_result(
                        client.viewer_id, response, result_code, error, http_status,
                    )
                    record["classification"] = classification
                    record["message"] = message
            return record, response

        def record_start_session() -> None:
            report["start_session"] = _start_session_findings(
                response_after("tool/start_session", 0),
            )
            _print_start_session_findings(report["start_session"])

        def print_login_failure(error: BaseException) -> int:
            record_start_session()
            response = response_after("load/index", 0)
            result_code = _result_code(response)
            if result_code is None:
                result_code = api_error_result_code(error)
            diagnosis, remedy = update_guard.classify_result_code(result_code)
            try:
                remedy = remedy.format(account=args.account)
            except (KeyError, ValueError):
                pass
            print(
                f"LOGIN FAILED: {diagnosis.value}"
                + (f" (result_code={result_code})" if result_code is not None else "")
                + f". {remedy}",
                flush=True,
            )
            return _finish(args.report, report, 1)

        try:
            if args.pre_index:
                # Mirror UmaClient.login() exactly through start_session, then leave
                # load/index until after the candidate probe.
                old_headers = dict(client.session.headers)
                client.session.close()
                client.session = client_module.requests.Session()
                client.session.headers.update(old_headers)
                client.regen_sid()
                client.call("tool/start_session", {"attestation_type": 0, "device_token": None})
            else:
                client.login(max_retries=0)
        except Exception as error:
            return print_login_failure(error)

        record_start_session()
        envelope_shape = _redacted_shapes(client.common())
        report["resolved_envelope_shape"] = envelope_shape
        print("Resolved request envelope shape: " + json.dumps(envelope_shape, ensure_ascii=True), flush=True)

        if args.dry_run:
            print("DRY RUN: no control or candidate routes were requested.", flush=True)
            return _finish(args.report, report, 0)

        def run_controls(session_bad_verdict: str = "NO_ROUTE_FOUND | SESSION_BAD") -> bool:
            control = report["control"]
            if not args.control:
                control["normal"] = {"skipped": "--no-control"}
                control["bad_payload"] = {"skipped": "--no-control"}
                print("CONTROL: skipped by --no-control; session is unverified.", flush=True)
                return True

            normal, normal_response = call_and_record(args.control_endpoint, {})
            control["normal"] = normal
            _print_endpoint_result("CONTROL", normal, normal_response is not None)
            if normal["result_code"] != 1:
                report["verdict"] = session_bad_verdict
                return False

            if not args.bad_payload_control:
                control["bad_payload"] = {"skipped": "--no-bad-payload-control"}
                print("BAD PAYLOAD CONTROL: skipped; H1/H2 cannot be distinguished.", flush=True)
                return True

            invalid_payload = {"__probe_invalid_field__": 1}
            bad_payload, bad_response = call_and_record(args.control_endpoint, invalid_payload)
            control["bad_payload"] = bad_payload
            _print_endpoint_result("BAD PAYLOAD CONTROL", bad_payload, bad_response is not None)
            return True

        def probe_candidates() -> str | None:
            for route in CANDIDATE_ROUTES:
                record, response = call_and_record(
                    route, {"cygames_id_client_sdk_version": SDK_VERSION},
                )
                record["route"] = route
                record["expected_nonsense"] = route in EXPECTED_NONSENSE_ROUTES
                report["candidates"].append(record)
                nonsense = "true" if record["expected_nonsense"] else "false"
                print(f"CANDIDATE: {route} (expected_nonsense: {nonsense})", flush=True)
                _print_endpoint_result("  RESULT", record, response is not None)
                if record["result_code"] == 1:
                    return route
            return None

        def load_after_accepted_candidate() -> None:
            record, response = call_and_record("load/index", {"adid": ""})
            report["post_candidate_load"] = record
            _print_endpoint_result("POST-CANDIDATE LOAD", record, response is not None)
            if record["result_code"] == 1 and isinstance(response, dict):
                # This duplicates login()'s post-load cache refresh without another call.
                client.refresh_cached_account_state(response.get("data", {}))

        if args.transition_preview:
            if not run_controls("SESSION_BAD"):
                return _finish(args.report, report, 1)
            preview, preview_response = call_and_record(
                TRANSITION_PREVIEW_ENDPOINT,
                {
                    "password": transition_password,
                    "input_viewer_id": args.transition_preview,
                },
            )
            report["transition_preview"]["response"] = preview
            _print_transition_preview_result(preview, preview_response)
            report["verdict"], status = _transition_preview_verdict(preview["result_code"])
            return _finish(args.report, report, status)

        if args.social_preview:
            if not run_controls("SESSION_BAD"):
                return _finish(args.report, report, 1)
            preview, preview_response = call_and_record(
                SOCIAL_PREVIEW_ENDPOINT,
                {
                    "openid": steam_id,
                    "openid_type": str(args.openid_type),
                    "authentication_token": steam_ticket,
                    "not_return_error": True,
                },
            )
            summary = _social_preview_summary(client.viewer_id, preview_response)
            summary["interpretation"] = _social_preview_message(
                client.viewer_id, preview_response, preview["result_code"],
            )
            report["social_preview"]["response"] = preview
            report["social_preview"]["result"] = summary
            _print_social_preview_result(client.viewer_id, preview, preview_response, summary)
            report["verdict"], status = _social_preview_verdict(
                client.viewer_id, preview, preview_response, summary,
            )
            return _finish(args.report, report, status)

        accepted_route: str | None
        if args.pre_index:
            # Keep H3 exact: nothing may run between start_session and candidates.
            accepted_route = probe_candidates()
            if accepted_route is not None:
                load_after_accepted_candidate()
            if not run_controls() and accepted_route is None:
                return _finish(args.report, report, 1)
        else:
            if not run_controls():
                return _finish(args.report, report, 1)
            accepted_route = probe_candidates()

        if accepted_route is not None:
            report["verdict"] = accepted_route
            return _finish(args.report, report, 0)

        if not args.control:
            report["verdict"] = "NO_ROUTE_FOUND | SESSION_BAD"
        elif not args.bad_payload_control:
            report["verdict"] = "NO_ROUTE_FOUND | SESSION_BAD"
        else:
            bad_payload = report["control"]["bad_payload"]
            if isinstance(bad_payload, dict) and bad_payload.get("result_code") == 102:
                report["verdict"] = "NO_ROUTE_FOUND | 102_IS_GENERIC"
            elif isinstance(bad_payload, dict) and bad_payload.get("result_code") is not None:
                report["verdict"] = "NO_ROUTE_FOUND | ALL_SPELLINGS_WRONG"
            else:
                report["verdict"] = "NO_ROUTE_FOUND | SESSION_BAD"
        return _finish(args.report, report, 1)
    finally:
        client_module.requests.Session = original_session_factory
        update_guard.alert_once = original_alert_once
        _close_client(client)


if __name__ == "__main__":
    raise SystemExit(main())
