from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiResponse(BaseModel):
    """Canonical JSON envelope for every API route that returns a plain dict.

    Applied as `response_model=ApiResponse, response_model_exclude_unset=True`,
    it documents/validates the `success` (+ optional `detail`/`error_code`)
    envelope in OpenAPI WITHOUT filtering the route's domain payload:
    `extra="allow"` passes every other key through, and `exclude_unset` re-emits
    exactly the keys the handler set -- so the response JSON is byte-identical to
    the hand-built dict. Validation fails (and FastAPI returns 500) if
    `success` is missing or a supplied `state` is outside its `Literal`; both
    are intentional contract guards. Auth routes use `state` and `error_code`
    as machine-checkable discriminators while older clients can continue
    reading only `success`.
    """

    model_config = ConfigDict(extra="allow")

    success: bool
    state: Literal[
        "authenticated",
        "needs_steam_login",
        "needs_steam_guard",
        "needs_transition_link",
        "pre_signup_complete",
        "steam_signup_disabled",
        "verified",
        "unbound",
        "failed",
    ] | None = None
    detail: str | None = None
    error_code: str | None = None
