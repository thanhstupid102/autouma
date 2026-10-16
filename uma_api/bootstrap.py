"""Explicit Steam account bootstrap, separate from authenticated login."""
from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import uuid

from uma_api.client import UmaClient


class BootstrapState(str, Enum):
    AUTHENTICATED = "authenticated"
    NEEDS_TRANSITION_LINK = "needs_transition_link"
    PRE_SIGNUP_COMPLETE = "pre_signup_complete"
    STEAM_SIGNUP_DISABLED = "steam_signup_disabled"


@dataclass(frozen=True)
class SteamBootstrapResult:
    state: BootstrapState
    client: UmaClient
    config: dict[str, Any]
    signup_response: dict[str, Any] | None
    pre_signup_response: dict[str, Any] = field(default_factory=dict)
    enable_steam_account: bool | None = None
    attest: bool | None = None
    nonce: str | None = None


def has_game_auth_config(cfg: Mapping[str, Any]) -> bool:
    viewer_id = cfg.get("viewer_id")
    if isinstance(viewer_id, bool):
        return False
    if isinstance(viewer_id, int):
        valid_viewer_id = viewer_id > 0
    elif isinstance(viewer_id, str) and viewer_id.isascii() and viewer_id.isdigit():
        valid_viewer_id = int(viewer_id) > 0
    else:
        valid_viewer_id = False
    if not valid_viewer_id:
        return False

    udid = cfg.get("udid")
    if not isinstance(udid, str) or not udid.strip():
        return False

    auth_key = cfg.get("auth_key")
    if not isinstance(auth_key, str) or auth_key == "YOUR_AUTH_KEY_HERE":
        return False
    try:
        return len(bytes.fromhex(auth_key)) == 48
    except ValueError:
        return False


def _fresh_steam_client(
    *,
    steam_id: str,
    steam_session_ticket: str,
    trace_enabled: bool,
    state_root=None,
    udid: str | None = None,
    client_factory: Callable[..., UmaClient] | None = None,
) -> UmaClient:
    cfg: dict[str, Any] = {
        "viewer_id": 0,
        "udid": udid if udid is not None else str(uuid.uuid4()).lower(),
        "auth_key": "",
        "steam_id": steam_id,
        "steam_session_ticket": steam_session_ticket,
    }
    factory = client_factory or UmaClient
    kwargs = {"trace_enabled": trace_enabled}
    if state_root is not None:
        kwargs["state_root"] = state_root
    try:
        return factory(cfg, **kwargs)
    except TypeError as exc:
        if state_root is None or "state_root" not in str(exc):
            raise
        return factory(cfg, trace_enabled=trace_enabled)


def fresh_steam_transition_config(
    *,
    steam_id: str,
    steam_session_ticket: str,
    trace_enabled: bool = True,
    state_root=None,
    client_factory: Callable[..., UmaClient] | None = None,
) -> dict[str, Any]:
    """Build bootstrap-shaped transition auth without making a wire call."""
    client = _fresh_steam_client(
        steam_id=steam_id,
        steam_session_ticket=steam_session_ticket,
        trace_enabled=trace_enabled,
        state_root=state_root,
        client_factory=client_factory,
    )
    return client.auth_config_snapshot()


def bootstrap_steam_account(
    *,
    steam_id: str,
    steam_session_ticket: str,
    trace_enabled: bool = True,
    state_root=None,
    udid: str | None = None,
    client_factory: Callable[..., UmaClient] | None = None,
    perform_signup: bool = True,
) -> SteamBootstrapResult:
    client = _fresh_steam_client(
        steam_id=steam_id,
        steam_session_ticket=steam_session_ticket,
        trace_enabled=trace_enabled,
        state_root=state_root,
        udid=udid,
        client_factory=client_factory,
    )

    client.regen_sid()
    pre_signup_response = client.call("tool/pre_signup")
    pre_signup_data = pre_signup_response.get("data")
    if not isinstance(pre_signup_data, dict):
        pre_signup_data = {}
    enable_steam_account = pre_signup_data.get("enable_steam_account")
    enable_steam_account = (
        enable_steam_account if isinstance(enable_steam_account, bool) else None
    )
    attest = pre_signup_data.get("attest")
    attest = attest if isinstance(attest, bool) else None
    nonce = pre_signup_data.get("nonce")
    nonce = nonce if isinstance(nonce, str) else None

    if enable_steam_account is False:
        return SteamBootstrapResult(
            state=BootstrapState.STEAM_SIGNUP_DISABLED,
            client=client,
            config=client.auth_config_snapshot(),
            signup_response=None,
            pre_signup_response=pre_signup_response,
            enable_steam_account=enable_steam_account,
            attest=attest,
            nonce=nonce,
        )

    if not perform_signup:
        return SteamBootstrapResult(
            state=BootstrapState.PRE_SIGNUP_COMPLETE,
            client=client,
            config=client.auth_config_snapshot(),
            signup_response=None,
            pre_signup_response=pre_signup_response,
            enable_steam_account=enable_steam_account,
            attest=attest,
            nonce=nonce,
        )

    client.pacing_policy.jittered_sleep(0.83)
    client.regen_sid()
    signup_response = client.call("tool/signup", {
        "error_code": 0,
        "error_message": "",
        "attestation_type": 0,
        "optin_user_birth": 199801,
        "dma_state": 0,
        "country": "Canada",
        "credential": "",
    })

    data = signup_response.get("data")
    data_headers = signup_response.get("data_headers")
    viewer_id_adopted = False
    auth_key_adopted = False
    viewer_id = None
    if isinstance(data_headers, dict):
        header_viewer_id = data_headers.get("viewer_id")
        if isinstance(header_viewer_id, int) and not isinstance(header_viewer_id, bool):
            if header_viewer_id > 0:
                viewer_id = header_viewer_id
    if isinstance(data, dict):
        if viewer_id is None:
            data_viewer_id = data.get("viewer_id")
            if isinstance(data_viewer_id, int) and not isinstance(data_viewer_id, bool):
                if data_viewer_id > 0:
                    viewer_id = data_viewer_id

        encoded_auth_key = data.get("auth_key")
        if isinstance(encoded_auth_key, str) and encoded_auth_key:
            try:
                decoded_auth_key = base64.b64decode(encoded_auth_key, validate=True)
            except (binascii.Error, ValueError):
                decoded_auth_key = b""
            if decoded_auth_key:
                client.auth_key_hex = decoded_auth_key.hex()
            auth_key_adopted = len(decoded_auth_key) == 48

    if viewer_id is not None:
        client.viewer_id = viewer_id
        viewer_id_adopted = True

    config = client.auth_config_snapshot()
    authenticated = (
        viewer_id_adopted
        and auth_key_adopted
        and has_game_auth_config(config)
    )
    state = (
        BootstrapState.AUTHENTICATED
        if authenticated
        else BootstrapState.NEEDS_TRANSITION_LINK
    )
    return SteamBootstrapResult(
        state=state,
        client=client,
        config=config,
        signup_response=signup_response,
        pre_signup_response=pre_signup_response,
        enable_steam_account=enable_steam_account,
        attest=attest,
        nonce=nonce,
    )
