"""Shared-token authentication for the HTTP API boundary."""
from __future__ import annotations

import hmac
import ipaddress
import os
import re
from pathlib import Path
from typing import Awaitable, Callable, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


API_TOKEN_ENV = "UMA_API_TOKEN"
API_TOKEN_FILE_ENV = "UMA_API_TOKEN_FILE"
AUTH_GATE_STATUS_PATH = "/api/auth-gate"
_API_PREFIX = "/api"

# Card/character artwork, requested by <img src> tags which cannot carry an
# Authorization header. Gating these produced 401s and a dashboard full of blank
# tiles. The artwork is shipped game data, not account data, and the sibling
# asset routes (/assets/data/..., /races/..., /broom.png) have always been
# ungated -- so this restores parity rather than opening something new.
#
# Matched as one strict path segment: anything with a separator or a dot-segment
# is NOT ungated, so this cannot be widened into a traversal or used to reach
# another /api route.
_UNGATED_API_PATH = re.compile(r"^/api/images/[A-Za-z0-9][A-Za-z0-9._-]*$")
_CallNext = Callable[[Request], Awaitable[Response]]


class ApiTokenConfigError(RuntimeError):
    """The configured API token source cannot be used safely."""


def _normalize_api_token(value: str) -> str:
    return value.lstrip("\ufeff").strip()


def resolve_api_token() -> str | None:
    """Resolve the API token, preferring the direct environment value.

    Tokens are trimmed like the frontend input. Whitespace-only values are absent,
    and a UTF-8 BOM from Windows-created token files is ignored.
    """
    direct = os.environ.get(API_TOKEN_ENV)
    if direct is not None:
        direct = _normalize_api_token(direct)
        if direct:
            return direct

    file_name = os.environ.get(API_TOKEN_FILE_ENV)
    if file_name is None or not file_name.strip():
        return None
    path = Path(file_name)
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiTokenConfigError(
            f"Cannot read {API_TOKEN_FILE_ENV} '{path}': {exc}. "
            f"Fix the path or permissions, or set {API_TOKEN_ENV}.",
        ) from exc
    except UnicodeError as exc:
        raise ApiTokenConfigError(
            f"{API_TOKEN_FILE_ENV} '{path}' must contain valid UTF-8 text.",
        ) from exc
    value = _normalize_api_token(value)
    return value or None


def resolve_api_token_or_exit() -> str | None:
    """Resolve the token with the one-line startup failure contract."""
    try:
        return resolve_api_token()
    except ApiTokenConfigError as exc:
        raise SystemExit(str(exc)) from None


def is_loopback_host(host: str) -> bool:
    """Classify literal loopback addresses without trusting DNS.

    ``localhost`` is the one allowed hostname. Every other hostname, including
    one that is unresolvable or currently resolves to loopback, is non-loopback
    so a DNS change cannot weaken the startup interlock.
    """
    value = host.strip()
    if value.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_token_for_bind(host: str, token: str | None) -> None:
    if is_loopback_host(host) or token is not None:
        return
    raise SystemExit(
        f"Cannot bind API to non-loopback host '{host}' without authentication; "
        f"set {API_TOKEN_ENV} or {API_TOKEN_FILE_ENV}, or bind to 127.0.0.1.",
    )


def _is_gated_api_path(path: str) -> bool:
    if path == AUTH_GATE_STATUS_PATH or _UNGATED_API_PATH.match(path):
        return False
    return path == _API_PREFIX or path.startswith(f"{_API_PREFIX}/")


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and token:
            return token
        return None
    return request.headers.get("x-api-token")


def _is_local_peer(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        peer = ipaddress.ip_address(client.host)
    except ValueError:
        return False
    return peer.is_loopback


def _request_path(request: Request) -> str:
    path = request.url.path
    root_path = str(request.scope.get("root_path") or "").rstrip("/")
    if root_path and (path == root_path or path.startswith(f"{root_path}/")):
        return path[len(root_path):] or "/"
    return path


def install_api_auth(app: FastAPI, token: str | None) -> None:
    """Install one path-prefix gate that covers current and future API routers."""
    app.state.api_token = token

    @app.middleware("http")
    async def require_api_token(
        request: Request,
        call_next: _CallNext,
    ) -> Response:
        configured = cast(str | None, request.app.state.api_token)
        if _is_gated_api_path(_request_path(request)):
            if configured is None and not _is_local_peer(request):
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "detail": (
                            "This server is unauthenticated because no API token "
                            "is configured; it serves API requests from loopback "
                            "clients only. Set "
                            f"{API_TOKEN_ENV} or {API_TOKEN_FILE_ENV} to enable "
                            "remote access."
                        ),
                    },
                )
            if configured is not None:
                presented = _request_token(request)
                if presented is None or not hmac.compare_digest(
                    presented.encode("utf-8"),
                    configured.encode("utf-8"),
                ):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "success": False,
                            "detail": "A valid API token is required.",
                        },
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return await call_next(request)

    @app.get(AUTH_GATE_STATUS_PATH)
    async def api_auth_gate_status(request: Request) -> dict[str, bool]:
        configured = cast(str | None, request.app.state.api_token)
        return {"gate_required": configured is not None}
