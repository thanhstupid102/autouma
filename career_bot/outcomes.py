"""Shared classification for terminal career outcomes."""

from collections.abc import Mapping
from typing import Any


def career_failed(summary: Mapping[str, Any]) -> bool:
    """Whether a terminal summary represents a failed, not operator-ended, career."""
    status = str(summary.get("status") or "")
    return status == "error" or (
        status == "stopped" and bool(summary.get("circuit_tripped"))
    )


def career_retry_block_reason(summary: Mapping[str, Any]) -> str | None:
    """Why an otherwise failed career cannot benefit from session recovery."""
    error = summary.get("error")
    error_type = str(summary.get("error_type") or "")
    error_message = str(summary.get("last_error") or "")
    if isinstance(error, Mapping):
        error_type = error_type or str(error.get("type") or "")
        error_message = error_message or str(error.get("message") or "")

    if error_type == "UnsupportedScenarioError":
        return "unsupported scenario cannot be driven by this bot"
    if error_type == "AuthInvalidatedError" or (
        "auth is invalid (re-registered)" in error_message
        and "Sign in again" in error_message
    ):
        return "saved authentication is invalid and requires a new Steam login"
    if error_type == "RunFatalError":
        if "race_out rejected by the server" in error_message:
            return "server-side race_out 201 lock survives session restarts"
        return "fatal run failure requires operator resolution"
    return None
