"""Typed transport helpers for the verified ``account/`` link routes."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import re
from typing import Any, Protocol

from uma_api.crypto import make_md5_hex
from uma_api.errors import ApiError, SteamAccountRemoveChainedError


USER_ID_MIN = 9
USER_ID_LIMIT = 12
LINK_PASSWORD_MIN = 8
LINK_PASSWORD_LIMIT = 16
_TRAINER_ID_RE = re.compile(r"[0-9]+", re.ASCII)
_LINK_PASSWORD_RE = re.compile(r"[0-9a-zA-Z]+", re.ASCII)

ACCOUNT_INDEX_ENDPOINT = "account/index"
GET_BY_TRANSITION_CODE_ENDPOINT = "account/get_by_transition_code"
CHAIN_BY_TRANSITION_CODE_ENDPOINT = "account/chain_by_transition_code"
PUBLISH_TRANSITION_CODE_ENDPOINT = "account/publish_transition_code"
STEAM_CHAIN_DISCONNECT_ENDPOINT = "account/steam_chain_disconnect"


class GameApiCaller(Protocol):
    def call(
        self,
        endpoint: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class AccountLinkError(ApiError):
    """Base class for typed account-link failures."""


class LinkInputValidationError(ValueError):
    """Local account-link input failed validation before any API call."""

    def __init__(self, endpoint: str = "account/validation") -> None:
        self.endpoint = endpoint
        super().__init__(f"Invalid account-link input for {endpoint}")


class TransitionOldAccessError(AccountLinkError):
    pass


class TransitionCompletedError(AccountLinkError):
    pass


class AccountLinkInvalidParameterError(AccountLinkError):
    pass


class AccountUserNotFoundError(AccountLinkError):
    pass


class TransitionUserNotExistError(AccountLinkError):
    pass


class TransitionPasswordInvalidError(AccountLinkError):
    pass


class TransitionUserIdInvalidError(AccountLinkError):
    pass


class AccountUdidConflictError(AccountLinkError):
    pass


class PcAccountLimitError(AccountLinkError):
    pass


class NoPlatformUserIdError(AccountLinkError):
    pass


class NoChainedUserIdError(AccountLinkError):
    pass


class AccountSignupMaintenanceError(AccountLinkError):
    pass


class DataLinkMaintenanceError(AccountLinkError):
    pass


class AccountChainMaintenanceError(AccountLinkError):
    pass


class AccountLinkResponseError(AccountLinkError):
    """A successful account-link response was incomplete or malformed."""


ACCOUNT_LINK_ERROR_TYPES: dict[int, type[ApiError]] = {
    516: TransitionOldAccessError,
    517: TransitionCompletedError,
    523: AccountLinkInvalidParameterError,
    524: AccountUserNotFoundError,
    526: TransitionUserNotExistError,
    700: TransitionPasswordInvalidError,
    701: TransitionUserIdInvalidError,
    703: AccountUdidConflictError,
    704: PcAccountLimitError,
    705: NoPlatformUserIdError,
    708: NoChainedUserIdError,
    709: SteamAccountRemoveChainedError,
    900: AccountSignupMaintenanceError,
    902: DataLinkMaintenanceError,
    903: AccountChainMaintenanceError,
}

# Symbol names from the client binary's result-code table. Keep this next to the
# typed exceptions so HTTP callers never invent free-text error identifiers.
ACCOUNT_LINK_ERROR_CODES: dict[int, str] = {
    516: "TRANSITION_OLD_ACCESS_ERROR",
    517: "TRANSITION_COMPLETED_ERROR",
    523: "INVALID_PARAMETER_ERROR",
    524: "USER_NOT_FOUND",
    526: "TRANSITION_USER_NOT_EXIST",
    700: "TRANSITIONPASSWORD_INVALID",
    701: "TRANSITION_USERID_INVALID",
    703: "ACCOUNT_UDID_CONFLICT",
    704: "PC_ACCOUNT_LIMIT_ERROR",
    705: "NO_PLATFORM_USER_ID_ERROR",
    708: "NO_CHAINED_USER_ID_ERROR",
    709: "STEAM_ACCOUNT_REMOVE_CHAINED",
    900: "MAINTENANCE_TASK_ACCOUNT_SIGN_UP",
    902: "MAINTENANCE_TASK_DATA_LINKAGE",
    903: "MAINTENANCE_TASK_ACCOUNT_CHAIN",
}


@dataclass(frozen=True)
class ChainResult:
    chained_viewer_id: int
    chained_user_name: str
    auth_key_hex: str
    response: dict[str, Any]


def _invalid_input(endpoint: str) -> LinkInputValidationError:
    return LinkInputValidationError(endpoint)


def validate_trainer_id(value: Any) -> str:
    """Validate a Trainer ID using the game's 9-12 ASCII-digit rule."""
    if (
        not isinstance(value, str)
        or not USER_ID_MIN <= len(value) <= USER_ID_LIMIT
        or _TRAINER_ID_RE.fullmatch(value) is None
    ):
        raise _invalid_input("account/validation")
    return value


def validate_link_password(value: Any) -> str:
    """Validate a link password without including its value in any error."""
    if (
        not isinstance(value, str)
        or not LINK_PASSWORD_MIN <= len(value) <= LINK_PASSWORD_LIMIT
        or _LINK_PASSWORD_RE.fullmatch(value) is None
        or re.search(r"[0-9]", value) is None
        or re.search(r"[a-z]", value) is None
        or re.search(r"[A-Z]", value) is None
    ):
        raise _invalid_input("account/validation")
    return value


def _call(client: GameApiCaller, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return client.call(endpoint, payload)
    except ApiError as exc:
        error_type = ACCOUNT_LINK_ERROR_TYPES.get(exc.result_code)
        if error_type is None:
            raise
        raise error_type(
            exc.result_code,
            exc.endpoint,
            exc.detail,
            message=str(exc),
        ) from exc


def account_index(client: GameApiCaller) -> dict[str, Any]:
    return _call(
        client,
        ACCOUNT_INDEX_ENDPOINT,
        {"cygames_id_client_sdk_version": "v2"},
    )


def get_by_transition_code(
    client: GameApiCaller,
    *,
    password: str,
    input_viewer_id: str,
) -> dict[str, Any]:
    raw_password = validate_link_password(password)
    if not isinstance(input_viewer_id, str):
        raise _invalid_input(GET_BY_TRANSITION_CODE_ENDPOINT)
    validate_trainer_id(input_viewer_id)
    return _call(
        client,
        GET_BY_TRANSITION_CODE_ENDPOINT,
        {
            "password": make_md5_hex(raw_password),
            "input_viewer_id": input_viewer_id,
        },
    )


def publish_transition_code(
    client: GameApiCaller,
    *,
    password: str,
) -> dict[str, Any]:
    raw_password = validate_link_password(password)
    return _call(
        client,
        PUBLISH_TRANSITION_CODE_ENDPOINT,
        {"password": make_md5_hex(raw_password)},
    )


def steam_chain_disconnect(client: GameApiCaller) -> dict[str, Any]:
    """Remove the Steam binding using identity from the common request block."""
    return _call(client, STEAM_CHAIN_DISCONNECT_ENDPOINT, {})


def chain_by_transition_code(
    client: GameApiCaller,
    *,
    password: str,
    input_viewer_id: int,
) -> ChainResult:
    raw_password = validate_link_password(password)
    if isinstance(input_viewer_id, bool) or not isinstance(input_viewer_id, int):
        raise _invalid_input(CHAIN_BY_TRANSITION_CODE_ENDPOINT)
    validate_trainer_id(str(input_viewer_id))
    response = _call(
        client,
        CHAIN_BY_TRANSITION_CODE_ENDPOINT,
        {
            "password": make_md5_hex(raw_password),
            "input_viewer_id": input_viewer_id,
        },
    )
    data = response.get("data")
    if not isinstance(data, dict):
        raise _response_error()

    chained_viewer_id = data.get("chained_viewer_id")
    chained_user_name = data.get("chained_user_name")
    encoded_auth_key = data.get("auth_key")
    if (
        isinstance(chained_viewer_id, bool)
        or not isinstance(chained_viewer_id, int)
        or not isinstance(chained_user_name, str)
        or not chained_user_name
        or not isinstance(encoded_auth_key, str)
        or not encoded_auth_key
    ):
        raise _response_error()
    try:
        auth_key_hex = base64.b64decode(encoded_auth_key, validate=True).hex()
    except (binascii.Error, ValueError) as exc:
        raise _response_error() from exc
    return ChainResult(
        chained_viewer_id=chained_viewer_id,
        chained_user_name=chained_user_name,
        auth_key_hex=auth_key_hex,
        response=response,
    )


def _response_error() -> AccountLinkResponseError:
    return AccountLinkResponseError(
        1,
        CHAIN_BY_TRANSITION_CODE_ENDPOINT,
        "incomplete account-link response",
        message=(
            f"API error 1 on {CHAIN_BY_TRANSITION_CODE_ENDPOINT}: "
            "incomplete account-link response"
        ),
    )
