"""Probe Steam bootstrap without exposing credentials.

Without ``--i-understand-this-may-create-or-rebind-an-account`` this performs
only the read-only ``tool/pre_signup`` request. With that flag it also calls
``tool/signup``, which may create a new game account or rebind the Steam
identity. The Trainer-ID + link-password recovery path has NOT been verified
working on this install: ``700 TRANSITIONPASSWORD_INVALID`` was observed for
three accounts from cross-account sessions.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.runtime_paths import resolve_state_root  # noqa: E402

RUNTIME_DIR = resolve_state_root(ROOT).root

from backend.app.domain.account_store import (  # noqa: E402
    load_account_config,
    load_steam_token,
)
from uma_api import bootstrap, secret_store, steam_auth  # noqa: E402
from uma_api.errors import ApiError  # noqa: E402


SIGNUP_RESULT_CODES = {
    704: "PC_ACCOUNT_LIMIT_ERROR",
    705: "NO_PLATFORM_USER_ID_ERROR",
    708: "NO_CHAINED_USER_ID_ERROR",
    709: "STEAM_ACCOUNT_REMOVE_CHAINED",
    900: "MAINTENANCE_TASK_ACCOUNT_SIGN_UP",
}
SIGNUP_CONFIRMATION_FLAG = "--i-understand-this-may-create-or-rebind-an-account"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Steam pre-signup; signup requires an explicit acknowledgement.",
    )
    parser.add_argument("--account", required=True, help="Stored account name.")
    parser.add_argument(
        SIGNUP_CONFIRMATION_FLAG,
        action="store_true",
        dest="allow_signup",
        help="Allow tool/signup, which may create or rebind a game account.",
    )
    parser.add_argument(
        "--save-to",
        type=Path,
        help="Write the resulting config as encrypted JSON under the state root.",
    )
    return parser.parse_args(argv)


def _safe_save_path(value: Path) -> Path:
    path = value if value.is_absolute() else ROOT / value
    path = path.resolve()
    try:
        path.relative_to(RUNTIME_DIR.resolve())
    except ValueError as exc:
        raise ValueError("--save-to must be under the selected state root") from exc
    return path


def _positive_viewer_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _digit_length(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    text = str(value)
    return len(text) if text.isascii() and text.isdigit() else 0


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return str(value).lower()


def _response_data(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _response_headers(response: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    headers = response.get("data_headers")
    return headers if isinstance(headers, dict) else {}


def _result_code(response: dict[str, Any] | None) -> int | None:
    result_code = _response_headers(response).get("result_code")
    if isinstance(result_code, int) and not isinstance(result_code, bool):
        return result_code
    return None


def _decoded_auth_key_length(response: dict[str, Any] | None) -> int | None:
    auth_key = _response_data(response).get("auth_key")
    if not isinstance(auth_key, str):
        return None
    try:
        return len(base64.b64decode(auth_key, validate=True))
    except (binascii.Error, ValueError):
        return None


def _load_refresh_token(account: str) -> str:
    token_data = load_steam_token(account)
    refresh_token = token_data.get("refresh_token") if isinstance(token_data, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("No stored Steam refresh token is available for this account.")
    return refresh_token


def _stored_viewer_id(account: str) -> int | None:
    config = load_account_config(account)
    if not isinstance(config, dict):
        return None
    return _positive_viewer_id(config.get("viewer_id"))


def _print_pre_signup(result: bootstrap.SteamBootstrapResult) -> None:
    response = result.pre_signup_response
    country_list = _response_data(response).get("country_list")
    country_list_length = len(country_list) if isinstance(country_list, list) else 0
    print(f"pre_signup.result_code: {_result_code(response)}", flush=True)
    print(f"pre_signup.enable_steam_account: {_bool_text(result.enable_steam_account)}", flush=True)
    print(f"pre_signup.attest: {_bool_text(result.attest)}", flush=True)
    print(f"pre_signup.nonce_length: {len(result.nonce) if result.nonce is not None else 0}", flush=True)
    print(f"pre_signup.country_list_length: {country_list_length}", flush=True)
    print(
        "pre_signup.data_headers.viewer_id_digit_length: "
        f"{_digit_length(_response_headers(response).get('viewer_id'))}",
        flush=True,
    )


def _print_signup(
    response: dict[str, Any] | None,
    existing_viewer_id: int | None,
    result_code_override: int | None = None,
) -> None:
    result_code = result_code_override if result_code_override is not None else _result_code(response)
    symbolic_name = SIGNUP_RESULT_CODES.get(result_code)
    result_text = str(result_code)
    if symbolic_name is not None:
        result_text += f" ({symbolic_name})"
    data = _response_data(response)
    returned_viewer_id = _positive_viewer_id(_response_headers(response).get("viewer_id"))
    decoded_auth_key_length = _decoded_auth_key_length(response)
    print(f"signup.result_code: {result_text}", flush=True)
    print(f"signup.data.auth_key_present: {'auth_key' in data}", flush=True)
    print(
        "signup.data.auth_key_decoded_byte_length: "
        f"{decoded_auth_key_length if decoded_auth_key_length is not None else 'unavailable'}",
        flush=True,
    )
    print(
        "signup.data_headers.viewer_id_digit_length: "
        f"{_digit_length(_response_headers(response).get('viewer_id'))}",
        flush=True,
    )
    matches_existing_account = (
        returned_viewer_id is not None
        and existing_viewer_id is not None
        and returned_viewer_id == existing_viewer_id
    )
    print(
        f"matches_existing_account: {_bool_text(matches_existing_account)}",
        flush=True,
    )


def _close_client(client: Any) -> None:
    try:
        client.session.close()
    except (AttributeError, OSError):
        pass


def run_probe(
    *,
    account: str,
    allow_signup: bool,
    save_to: Path | None = None,
) -> int:
    """Run the selected probe mode; tests replace its credential and API helpers."""
    if save_to is not None:
        save_to = _safe_save_path(save_to)
    refresh_token = _load_refresh_token(account)
    steam_id, steam_ticket, _unused_refresh_token = steam_auth.get_ticket(
        refresh_token=refresh_token,
    )
    result: bootstrap.SteamBootstrapResult | None = None
    try:
        try:
            result = bootstrap.bootstrap_steam_account(
                steam_id=str(steam_id),
                steam_session_ticket=str(steam_ticket),
                trace_enabled=False,
                state_root=RUNTIME_DIR,
                perform_signup=allow_signup,
            )
        except ApiError as error:
            if allow_signup and error.endpoint == "tool/signup":
                _print_signup(
                    None,
                    _stored_viewer_id(account),
                    result_code_override=error.result_code,
                )
                print("No config was saved because tool/signup returned an API error.", flush=True)
                return 0
            raise
        _print_pre_signup(result)
        if not allow_signup:
            print(
                "tool/signup NOT CALLED: refusing without "
                f"{SIGNUP_CONFIRMATION_FLAG}; pre_signup is read-only.",
                flush=True,
            )
        elif result.state is bootstrap.BootstrapState.STEAM_SIGNUP_DISABLED:
            print(
                "tool/signup NOT CALLED: server reported enable_steam_account=false.",
                flush=True,
            )
        else:
            _print_signup(result.signup_response, _stored_viewer_id(account))

        if save_to is not None:
            secret_store.save_json(save_to, result.config, RUNTIME_DIR)
            print("Resulting config saved as encrypted JSON.", flush=True)
        return 0
    finally:
        if result is not None:
            _close_client(result.client)


def main(argv: Sequence[str] | None = None) -> int:
    parser_args = _parse_args(argv)
    try:
        save_to = _safe_save_path(parser_args.save_to) if parser_args.save_to else None
    except ValueError as error:
        print(str(error), flush=True)
        return 2
    try:
        return run_probe(
            account=parser_args.account,
            allow_signup=parser_args.allow_signup,
            save_to=save_to,
        )
    except Exception as error:
        print(f"Probe failed: {type(error).__name__}; details suppressed.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
