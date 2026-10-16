import asyncio
import base64
from types import SimpleNamespace

import pytest

import backend.app.domain.account_status as account_status
import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point
from backend.app.routers.auth.schemas.auth import LoginRequest
from backend.app.routers.auth.services import auth_service
from backend.app.routers.auth.services.auth_service import AuthService
from tests._helpers import make_client
from uma_api import bootstrap
import uma_api.account_link as account_link
from uma_api.account_link import (
    ACCOUNT_LINK_ERROR_CODES,
    LinkInputValidationError,
)
from uma_api.crypto import make_md5_hex
from uma_api.errors import ApiError, SteamAccountRemoveChainedError
from uma_api.session import get_session_manager


REAL_BOOTSTRAP_STEAM_ACCOUNT = bootstrap.bootstrap_steam_account


VALID_AUTH = {
    "viewer_id": 229594617236,
    "udid": "00000000-0000-0000-0000-000000000001",
    "auth_key": "ab" * 48,
    "steam_id": "76561190000000001",
    "steam_session_ticket": "fresh-ticket",
    "device_id": "device-a",
    "device_name": "Desktop",
    "graphics_device_name": "GPU",
    "ip_address": "127.0.0.1",
    "platform_os_version": "Windows 11",
}

STAGED_TRANSITION = {
    **VALID_AUTH,
    "viewer_id": 0,
    "auth_key": "",
    "udid": "00000000-0000-0000-0000-000000000099",
}

STAGED_TRANSITION_WITH_AUTH = {
    **STAGED_TRANSITION,
    "viewer_id": 118765432109,
    "auth_key": "bc" * 48,
}

CHAIN_AUTH_KEY = "cd" * 48
ROTATED_AUTH_KEY = "ef" * 48
VALID_PASSWORD = "LinkPass9"
VALID_TRAINER_ID = "229594617236"


class FakeUmaClient:
    instances: list["FakeUmaClient"] = []
    events: list[str] = []
    login_hook = None
    call_hook = None

    def __init__(self, cfg, trace_enabled=False):
        self.cfg = dict(cfg)
        self.viewer_id = cfg.get("viewer_id", 0)
        self.udid_str = cfg.get("udid", "")
        self.auth_key_hex = cfg.get("auth_key", "")
        self.steam_id = str(cfg.get("steam_id", ""))
        self.steam_ticket = cfg.get("steam_session_ticket", "")
        self.device_id = cfg.get("device_id", "device")
        self.device_name = cfg.get("device_name", "Desktop")
        self.graphics_device = cfg.get("graphics_device_name", "GPU")
        self.ip_address = cfg.get("ip_address", "127.0.0.1")
        self.platform_os = cfg.get("platform_os_version", "Windows 11")
        self.auth_key_rotated = False
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.calls = []
        FakeUmaClient.instances.append(self)

    def bind_api_warehouse(self, base_dir, account):
        self.account = account
        return self

    def auth_config_snapshot(self):
        return {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
        }

    def login(self):
        FakeUmaClient.events.append("start_session")
        FakeUmaClient.events.append("load_index")
        if FakeUmaClient.login_hook is not None:
            return FakeUmaClient.login_hook(self)
        return {"data": {"user_info": {"name": "Linked Trainer"}}}

    def regen_sid(self):
        FakeUmaClient.events.append("regen_sid")

    def call(self, endpoint, args=None, **kwargs):
        self.calls.append((endpoint, args, kwargs))
        FakeUmaClient.events.append(f"wire:{endpoint}")
        if endpoint == "tool/start_session":
            return {"data": {}}
        if FakeUmaClient.call_hook is None:
            raise AssertionError(f"Unexpected game call: {endpoint}")
        return FakeUmaClient.call_hook(self, endpoint, args, kwargs)


@pytest.fixture
def flow(monkeypatch, drop_sessions):
    import career_bot.delay as delay_module
    import uma_api.client as client_module

    FakeUmaClient.instances = []
    FakeUmaClient.events = []
    FakeUmaClient.login_hook = None
    FakeUmaClient.call_hook = None

    monkeypatch.setattr(client_module, "UmaClient", FakeUmaClient)
    monkeypatch.setattr(delay_module, "GateKeeper", lambda client, *a, **k: client)
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: pytest.fail("bootstrap must not be called in this test"),
    )
    monkeypatch.setattr(account_store, "load_account_config", lambda name: None)
    monkeypatch.setattr(account_store, "save_account_config", lambda name, cfg: True)
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: None)
    monkeypatch.setattr(account_store, "save_steam_token", lambda *args, **kwargs: True)
    monkeypatch.setattr(account_store, "clear_steam_token", lambda name: None)
    monkeypatch.setattr(account_store, "load_selection", lambda name: None)
    monkeypatch.setattr(account_store, "apply_auto_delete_config", lambda session: {})
    monkeypatch.setattr(
        account_status,
        "get_account_status",
        lambda session, data, career: FakeUmaClient.events.append("hydrate") or {
            "viewer_id": session.client.viewer_id,
        },
    )
    monkeypatch.setattr(account_status, "update_start_state", lambda session, data: None)
    monkeypatch.setattr(rank_point, "chara_map", {})
    monkeypatch.setattr(rank_point, "support_map", {})

    names = ["steam-flow", "steam-flow-a", "steam-flow-b"]
    drop_sessions(*names)
    return get_session_manager().get("steam-flow")


def _login(session, **kwargs):
    return asyncio.run(AuthService(session).login(LoginRequest(**kwargs)))


def _bootstrap_result(state, cfg):
    client = FakeUmaClient(cfg)
    return bootstrap.SteamBootstrapResult(
        state=state,
        client=client,
        config=dict(cfg),
        signup_response={"data": {}},
    )


def _install_successful_chain():
    encoded_key = base64.b64encode(bytes.fromhex(CHAIN_AUTH_KEY)).decode("ascii")

    def call_hook(client, endpoint, args, kwargs):
        assert args["password"] == make_md5_hex(VALID_PASSWORD)
        assert VALID_PASSWORD not in str(args)
        if endpoint == "account/get_by_transition_code":
            assert isinstance(args["input_viewer_id"], str)
            return {"data": {"name": "Target", "request_user_name": "Requester"}}
        if endpoint == "account/chain_by_transition_code":
            assert isinstance(args["input_viewer_id"], int)
            return {"data": {
                "chained_viewer_id": int(VALID_TRAINER_ID),
                "chained_user_name": "Target",
                "auth_key": encoded_key,
            }}
        raise AssertionError(endpoint)

    FakeUmaClient.call_hook = call_hook


def test_saved_game_auth_logs_in_without_signup_or_prompt(flow, monkeypatch):
    import uma_api.client as client_module

    monkeypatch.setattr(
        account_store, "load_account_config", lambda name: dict(VALID_AUTH),
    )
    monkeypatch.setattr(
        client_module,
        "get_ticket",
        lambda *args, **kwargs: pytest.fail("Steam prompt must not be used"),
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result["success"] is True
    assert result["state"] == "authenticated"
    assert FakeUmaClient.events.count("start_session") == 1
    assert not any(event.startswith("wire:tool/signup") for event in FakeUmaClient.events)


def test_saved_game_auth_709_stages_existing_device_without_retry_or_mutation(
    flow, monkeypatch,
):
    import uma_api.client as client_module

    stored = dict(VALID_AUTH)
    original = dict(stored)
    saved_configs = []
    monkeypatch.setattr(account_store, "load_account_config", lambda name: stored)
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: saved_configs.append(dict(cfg)) or True,
    )
    monkeypatch.setattr(
        account_store,
        "load_steam_token",
        lambda name: {"refresh_token": "must-not-be-used"},
    )
    monkeypatch.setattr(
        client_module,
        "get_ticket",
        lambda *args, **kwargs: pytest.fail("709 must not retry another ticket source"),
    )

    def reject_removed_link(client):
        raise SteamAccountRemoveChainedError(
            709, "load/index", "link removed",
        )

    FakeUmaClient.login_hook = reject_removed_link

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result == {
        "success": False,
        "state": "needs_transition_link",
        "reason": "steam_link_removed",
        "viewer_id": str(VALID_AUTH["viewer_id"]),
    }
    assert "detail" not in result
    assert FakeUmaClient.events.count("start_session") == 1
    assert flow.pending_transition_config == {
        **stored,
        "steam_session_ticket": "request-ticket",
    }
    assert flow.pending_transition_config["udid"] == stored["udid"]
    assert stored == original
    assert saved_configs == []
    assert not any("tool/signup" in event for event in FakeUmaClient.events)


def test_steam_unbound_marker_is_advisory_and_cleared_after_successful_login(
    flow, monkeypatch,
):
    stored = {**VALID_AUTH, "steam_unbound_at": 1234567890}
    saved_configs = []
    monkeypatch.setattr(account_store, "load_account_config", lambda name: stored)
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: saved_configs.append(dict(cfg)) or True,
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result["success"] is True
    assert FakeUmaClient.events.count("start_session") == 1
    assert len(saved_configs) == 1
    assert "steam_unbound_at" not in saved_configs[0]


def test_stored_auth_login_decision_does_not_read_unbind_marker(flow, monkeypatch):
    class MarkerReadForbidden(dict):
        def get(self, key, default=None):
            if key == "steam_unbound_at":
                raise AssertionError("login decision read the advisory marker")
            return super().get(key, default)

    stored = MarkerReadForbidden({
        **VALID_AUTH,
        "steam_unbound_at": 1234567890,
    })
    monkeypatch.setattr(account_store, "load_account_config", lambda name: stored)

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result["success"] is True
    assert FakeUmaClient.events.count("start_session") == 1


def test_steam_unbound_marker_709_attempts_login_once_and_preserves_auth(
    flow, monkeypatch,
):
    import uma_api.client as client_module

    stored = {**VALID_AUTH, "steam_unbound_at": 1234567890}
    original = dict(stored)
    saved_configs = []
    monkeypatch.setattr(account_store, "load_account_config", lambda name: stored)
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: saved_configs.append(dict(cfg)) or True,
    )
    monkeypatch.setattr(
        account_store,
        "load_steam_token",
        lambda name: {"refresh_token": "must-not-be-used"},
    )
    monkeypatch.setattr(
        client_module,
        "get_ticket",
        lambda *args, **kwargs: pytest.fail("709 must not retry another ticket source"),
    )

    def reject_removed_link(client):
        raise SteamAccountRemoveChainedError(
            709, "load/index", "link removed",
        )

    FakeUmaClient.login_hook = reject_removed_link

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result == {
        "success": False,
        "state": "needs_transition_link",
        "reason": "steam_link_removed",
        "viewer_id": str(VALID_AUTH["viewer_id"]),
    }
    assert FakeUmaClient.events.count("start_session") == 1
    assert flow.pending_transition_config == {
        **stored,
        "steam_session_ticket": "request-ticket",
    }
    assert flow.pending_transition_config["udid"] == stored["udid"]
    assert stored == original
    assert saved_configs == []


def test_successful_login_without_unbind_marker_does_not_persist(flow, monkeypatch):
    saved_configs = []
    monkeypatch.setattr(
        account_store, "load_account_config", lambda name: dict(VALID_AUTH),
    )
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: saved_configs.append(dict(cfg)) or True,
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result["success"] is True
    assert saved_configs == []


def test_first_steam_login_without_saved_auth_bootstraps_once(flow, monkeypatch):
    calls = []

    def fake_bootstrap(**kwargs):
        calls.append(kwargs)
        return _bootstrap_result(
            bootstrap.BootstrapState.NEEDS_TRANSITION_LINK,
            STAGED_TRANSITION,
        )

    monkeypatch.setattr(bootstrap, "bootstrap_steam_account", fake_bootstrap)

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result == {"success": False, "state": "needs_transition_link"}
    assert len(calls) == 1


def test_authenticated_bootstrap_persists_before_start_session(flow, monkeypatch):
    events = []
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: _bootstrap_result(
            bootstrap.BootstrapState.AUTHENTICATED,
            VALID_AUTH,
        ),
    )
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: events.append("persist") or True,
    )
    FakeUmaClient.login_hook = (
        lambda client: events.append("start_session")
        or {"data": {"user_info": {"name": "Trainer"}}}
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result["success"] is True
    assert events == ["persist", "start_session"]


def test_needs_transition_link_stages_config_without_error_detail(flow, monkeypatch):
    staged = dict(STAGED_TRANSITION)
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: _bootstrap_result(
            bootstrap.BootstrapState.NEEDS_TRANSITION_LINK,
            staged,
        ),
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result == {"success": False, "state": "needs_transition_link"}
    assert "detail" not in result
    assert flow.pending_transition_config == staged


def test_disabled_steam_signup_returns_typed_state_without_staging(flow, monkeypatch):
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: _bootstrap_result(
            bootstrap.BootstrapState.STEAM_SIGNUP_DISABLED,
            STAGED_TRANSITION,
        ),
    )

    result = _login(
        flow,
        steam_id="76561190000000001",
        steam_session_ticket="request-ticket",
    )

    assert result == {"success": False, "state": "steam_signup_disabled"}
    assert flow.pending_transition_config == {}


def test_chain_without_staged_config_returns_409(tmp_path):
    _, client = make_client(tmp_path)

    response = client.post(
        "/api/auth/transition-code/chain",
        json={"input_viewer_id": VALID_TRAINER_ID, "password": VALID_PASSWORD},
        headers={"X-Account": "steam-flow"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "No staged Steam transition is available"}


@pytest.mark.parametrize(
    "input_viewer_id,password",
    [
        ("123", VALID_PASSWORD),
        (VALID_TRAINER_ID, "LeakySecret"),
    ],
)
def test_invalid_transition_input_is_rejected_before_wire(
    flow, input_viewer_id, password,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)

    with pytest.raises(LinkInputValidationError) as exc_info:
        asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
            input_viewer_id=input_viewer_id,
            password=password,
        )))

    assert password not in str(exc_info.value)
    assert FakeUmaClient.instances == []
    assert flow.pending_transition_config == STAGED_TRANSITION


def test_local_transition_validation_maps_to_secret_free_400(
    flow, tmp_path, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)

    def reject_locally(value):
        raise LinkInputValidationError()

    monkeypatch.setattr(account_link, "validate_link_password", reject_locally)
    _, client = make_client(tmp_path)

    response = client.post(
        "/api/auth/transition-code/chain",
        json={"input_viewer_id": VALID_TRAINER_ID, "password": VALID_PASSWORD},
        headers={"X-Account": "steam-flow"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid Trainer ID or link password",
    }
    assert VALID_PASSWORD not in response.text
    assert "INVALID_PARAMETER_ERROR" not in response.text
    assert FakeUmaClient.instances == []
    assert flow.pending_transition_config == STAGED_TRANSITION


def test_schema_validation_never_echoes_link_password(flow, tmp_path):
    flow.pending_transition_config = dict(STAGED_TRANSITION)
    _, client = make_client(tmp_path)
    password = "LeakySecret"

    response = client.post(
        "/api/auth/transition-code/chain",
        json={"input_viewer_id": VALID_TRAINER_ID, "password": password},
        headers={"X-Account": "steam-flow"},
    )

    assert response.status_code == 422
    assert password not in response.text
    assert FakeUmaClient.instances == []
    assert flow.pending_transition_config == STAGED_TRANSITION


def test_bare_stage_bootstraps_same_udid_then_starts_session_before_chain(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)
    events = FakeUmaClient.events
    bootstrap_calls = []

    def fake_bootstrap(**kwargs):
        events.append("bootstrap")
        bootstrap_calls.append(kwargs)
        return _bootstrap_result(
            bootstrap.BootstrapState.NEEDS_TRANSITION_LINK,
            STAGED_TRANSITION_WITH_AUTH,
        )

    monkeypatch.setattr(bootstrap, "bootstrap_steam_account", fake_bootstrap)
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: events.append("persist") or True,
    )
    _install_successful_chain()

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert bootstrap_calls[0]["udid"] == STAGED_TRANSITION["udid"]
    expected_order = [
        "bootstrap",
        "wire:tool/start_session",
        "wire:account/get_by_transition_code",
        "wire:account/chain_by_transition_code",
        "persist",
        "start_session",
        "load_index",
    ]
    assert [event for event in events if event in expected_order] == expected_order
    assert events.index("wire:account/chain_by_transition_code") < events.index(
        "load_index",
    )
    assert len({id(client) for client in FakeUmaClient.instances}) == 1


def test_bare_stage_signup_disabled_stops_after_pre_signup_with_relink_guidance(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        REAL_BOOTSTRAP_STEAM_ACCOUNT,
    )
    monkeypatch.setattr(bootstrap, "UmaClient", FakeUmaClient)

    def pre_signup_disabled(client, endpoint, args, kwargs):
        if endpoint == "tool/pre_signup":
            return {"data": {"enable_steam_account": False}}
        if endpoint == "tool/signup":
            pytest.fail("signup must not run when Steam account signup is disabled")
        raise AssertionError(endpoint)

    FakeUmaClient.call_hook = pre_signup_disabled

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result == {
        "success": False,
        "state": "failed",
        "error_code": "STEAM_SIGNUP_DISABLED",
        "detail": (
            "This Steam account's Uma link was removed, so the server will not "
            "let it register a new game account. Re-link it from the game "
            "client and then press Re-establish."
        ),
    }
    assert FakeUmaClient.events == ["regen_sid", "wire:tool/pre_signup"]
    assert FakeUmaClient.instances[0].udid_str == STAGED_TRANSITION["udid"]
    assert flow.pending_transition_config == STAGED_TRANSITION


def test_bare_stage_authenticated_bootstrap_skips_trainer_id_calls(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)
    events = FakeUmaClient.events
    bootstrap_calls = []
    saved = []

    def fake_bootstrap(**kwargs):
        events.append("bootstrap")
        bootstrap_calls.append(kwargs)
        return _bootstrap_result(
            bootstrap.BootstrapState.AUTHENTICATED,
            VALID_AUTH,
        )

    monkeypatch.setattr(bootstrap, "bootstrap_steam_account", fake_bootstrap)
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: events.append("persist") or saved.append(dict(cfg)) or True,
    )

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert result["state"] == "authenticated"
    assert "Trainer ID linking was not needed" in result["detail"]
    assert bootstrap_calls[0]["udid"] == STAGED_TRANSITION["udid"]
    assert not any("account/" in event for event in events)
    assert events.index("persist") < events.index("start_session")
    assert saved[0]["viewer_id"] == VALID_AUTH["viewer_id"]
    assert flow.client is not None
    assert flow.pending_transition_config == {}


def test_get_201_restarts_session_once_then_retries_and_chains(flow):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    encoded_key = base64.b64encode(bytes.fromhex(CHAIN_AUTH_KEY)).decode("ascii")
    get_attempts = 0

    def expire_once(client, endpoint, args, kwargs):
        nonlocal get_attempts
        if endpoint == "account/get_by_transition_code":
            get_attempts += 1
            if get_attempts == 1:
                raise ApiError(201, endpoint, "expired")
            return {"data": {"name": "Target", "request_user_name": "Requester"}}
        if endpoint == "tool/start_session":
            return {"data": {}}
        if endpoint == "account/chain_by_transition_code":
            return {"data": {
                "chained_viewer_id": int(VALID_TRAINER_ID),
                "chained_user_name": "Target",
                "auth_key": encoded_key,
            }}
        raise AssertionError(endpoint)

    FakeUmaClient.call_hook = expire_once

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert get_attempts == 2
    assert FakeUmaClient.events.count("wire:tool/start_session") == 2
    assert FakeUmaClient.events.count("regen_sid") == 2
    session_starts = [
        index for index, event in enumerate(FakeUmaClient.events)
        if event == "wire:tool/start_session"
    ]
    get_events = [
        index for index, event in enumerate(FakeUmaClient.events)
        if event == "wire:account/get_by_transition_code"
    ]
    assert session_starts[0] < get_events[0] < session_starts[1] < get_events[1]


def test_chain_201_restarts_session_once_then_retries_same_call(flow):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    encoded_key = base64.b64encode(bytes.fromhex(CHAIN_AUTH_KEY)).decode("ascii")
    chain_attempts = 0

    def expire_chain_once(client, endpoint, args, kwargs):
        nonlocal chain_attempts
        if endpoint == "account/get_by_transition_code":
            return {"data": {"name": "Target", "request_user_name": "Requester"}}
        if endpoint == "account/chain_by_transition_code":
            chain_attempts += 1
            if chain_attempts == 1:
                raise ApiError(201, endpoint, "expired")
            return {"data": {
                "chained_viewer_id": int(VALID_TRAINER_ID),
                "chained_user_name": "Target",
                "auth_key": encoded_key,
            }}
        if endpoint == "tool/start_session":
            return {"data": {}}
        raise AssertionError(endpoint)

    FakeUmaClient.call_hook = expire_chain_once

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert chain_attempts == 2
    assert FakeUmaClient.events.count("wire:tool/start_session") == 2


def test_get_201_twice_returns_typed_failure_without_third_attempt(
    flow, caplog,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    get_attempts = 0

    def always_expired(client, endpoint, args, kwargs):
        nonlocal get_attempts
        if endpoint == "account/get_by_transition_code":
            get_attempts += 1
            raise ApiError(201, endpoint, "expired")
        if endpoint == "tool/start_session":
            return {"data": {}}
        raise AssertionError(endpoint)

    FakeUmaClient.call_hook = always_expired

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
        verify_only=True,
    )))

    assert result == {
        "success": False,
        "state": "failed",
        "error_code": "SESSION",
        "detail": (
            "The transition session expired or could not be re-established; "
            "account-link state was preserved."
        ),
    }
    assert get_attempts == 2
    assert FakeUmaClient.events.count("wire:tool/start_session") == 2
    assert "Traceback" not in caplog.text
    assert flow.pending_transition_config == STAGED_TRANSITION_WITH_AUTH


def test_transition_auth_failure_returns_symbolic_code_without_retry(flow):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)

    def auth_rejected(client, endpoint, args, kwargs):
        assert endpoint == "account/get_by_transition_code"
        raise ApiError(203, endpoint, "rejected")

    FakeUmaClient.call_hook = auth_rejected

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
        verify_only=True,
    )))

    assert result == {
        "success": False,
        "state": "failed",
        "error_code": "AUTH_INVALIDATED",
        "detail": (
            "The game rejected the transition authentication; account-link "
            "state was preserved."
        ),
    }
    assert FakeUmaClient.events.count("wire:account/get_by_transition_code") == 1
    assert FakeUmaClient.events.count("wire:tool/start_session") == 1
    assert flow.pending_transition_config == STAGED_TRANSITION_WITH_AUTH


def test_staged_game_auth_starts_only_session_without_bootstrap(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    bootstrap_calls = []
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: bootstrap_calls.append(kwargs),
    )

    def preview(client, endpoint, args, kwargs):
        assert endpoint == "account/get_by_transition_code"
        return {"data": {"name": "Target", "request_user_name": "Requester"}}

    FakeUmaClient.call_hook = preview

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
        verify_only=True,
    )))

    assert result["state"] == "verified"
    assert FakeUmaClient.events == [
        "regen_sid",
        "wire:tool/start_session",
        "wire:account/get_by_transition_code",
    ]
    assert bootstrap_calls == []
    assert not any("tool/signup" in event for event in FakeUmaClient.events)


def test_transition_password_700_returns_symbolic_code_and_preserves_stage(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION)

    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: _bootstrap_result(
            bootstrap.BootstrapState.NEEDS_TRANSITION_LINK,
            STAGED_TRANSITION_WITH_AUTH,
        ),
    )

    def rejected(client, endpoint, args, kwargs):
        raise ApiError(700, endpoint, "rejected")

    FakeUmaClient.call_hook = rejected

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is False
    assert result["state"] == "failed"
    assert result["error_code"] == "TRANSITIONPASSWORD_INVALID"
    assert FakeUmaClient.events.count("wire:account/get_by_transition_code") == 1
    assert FakeUmaClient.events.count("wire:tool/start_session") == 1
    assert flow.pending_transition_config == STAGED_TRANSITION_WITH_AUTH


def test_verify_only_previews_once_without_chaining_and_preserves_stage(
    flow, tmp_path,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)

    def preview_only(client, endpoint, args, kwargs):
        assert endpoint == "account/get_by_transition_code"
        return {"data": {
            "name": "Target Trainer",
            "request_user_name": "Steam Requester",
            "target_viewer_id": 999999999999,
        }}

    FakeUmaClient.call_hook = preview_only
    _, client = make_client(tmp_path)

    response = client.post(
        "/api/auth/transition-code/chain",
        json={
            "input_viewer_id": VALID_TRAINER_ID,
            "password": VALID_PASSWORD,
            "verify_only": True,
        },
        headers={"X-Account": "steam-flow"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "state": "verified",
        "name": "Target Trainer",
        "request_user_name": "Steam Requester",
    }
    assert FakeUmaClient.events == [
        "regen_sid",
        "wire:tool/start_session",
        "wire:account/get_by_transition_code",
    ]
    assert all(
        endpoint != "account/chain_by_transition_code"
        for instance in FakeUmaClient.instances
        for endpoint, _, _ in instance.calls
    )
    assert flow.pending_transition_config == STAGED_TRANSITION_WITH_AUTH


def test_verify_only_failure_uses_same_error_code_table_and_preserves_stage(flow):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)

    def rejected(client, endpoint, args, kwargs):
        assert endpoint == "account/get_by_transition_code"
        raise ApiError(701, endpoint, "rejected")

    FakeUmaClient.call_hook = rejected

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
        verify_only=True,
    )))

    assert result["success"] is False
    assert result["state"] == "failed"
    assert result["error_code"] == "TRANSITION_USERID_INVALID"
    assert FakeUmaClient.events == [
        "regen_sid",
        "wire:tool/start_session",
        "wire:account/get_by_transition_code",
    ]
    assert flow.pending_transition_config == STAGED_TRANSITION_WITH_AUTH


def test_successful_chain_persists_then_logs_in_hydrates_and_clears(
    flow, monkeypatch, caplog,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    _install_successful_chain()
    events = FakeUmaClient.events
    saved = []
    staged_during_persist = []
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: (
            events.append("persist")
            or staged_during_persist.append(bool(flow.pending_transition_config))
            or saved.append(dict(cfg))
            or True
        ),
    )
    original_complete = auth_service._complete_login
    staged_during_complete = []

    def recording_complete(*args):
        events.append("complete")
        staged_during_complete.append(bool(flow.pending_transition_config))
        result = original_complete(*args)
        staged_during_complete.append(bool(flow.pending_transition_config))
        return result

    monkeypatch.setattr(auth_service, "_complete_login", recording_complete)

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert result["state"] == "authenticated"
    assert result["name"] == "Target"
    assert result["request_user_name"] == "Requester"
    assert result["chained_user_name"] == "Target"
    transition_order = [
        "wire:tool/start_session",
        "wire:account/get_by_transition_code",
        "wire:account/chain_by_transition_code",
        "persist",
        "start_session",
        "load_index",
    ]
    assert [event for event in events if event in transition_order] == transition_order
    assert events.index("wire:account/chain_by_transition_code") < events.index(
        "load_index",
    )
    assert events.index("load_index") < events.index("complete")
    assert saved[0]["viewer_id"] == int(VALID_TRAINER_ID)
    assert saved[0]["auth_key"] == CHAIN_AUTH_KEY
    assert staged_during_persist == [True]
    assert staged_during_complete == [True, True]
    assert VALID_PASSWORD not in str(saved)
    assert make_md5_hex(VALID_PASSWORD) not in str(saved)
    assert VALID_PASSWORD not in caplog.text
    assert make_md5_hex(VALID_PASSWORD) not in caplog.text
    assert len({id(client) for client in FakeUmaClient.instances}) == 1
    assert flow.pending_transition_config == {}


def test_successful_chain_clears_steam_unbound_marker_after_login(flow, monkeypatch):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    _install_successful_chain()
    stored = {**VALID_AUTH, "steam_unbound_at": 1234567890}
    saved = []

    def save_config(name, cfg):
        saved.append(dict(cfg))
        stored.clear()
        stored.update(cfg)
        return True

    monkeypatch.setattr(account_store, "load_account_config", lambda name: dict(stored))
    monkeypatch.setattr(account_store, "save_account_config", save_config)

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert saved[0]["steam_unbound_at"] == 1234567890
    assert "steam_unbound_at" not in saved[-1]
    assert "steam_unbound_at" not in stored


def test_start_session_auth_key_rotation_triggers_second_persist(flow, monkeypatch):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    _install_successful_chain()
    saved_auth_keys = []
    monkeypatch.setattr(
        account_store,
        "save_account_config",
        lambda name, cfg: saved_auth_keys.append(cfg["auth_key"]) or True,
    )

    def rotate_auth_key(client):
        client.auth_key_hex = ROTATED_AUTH_KEY
        client.auth_key_rotated = True
        return {"data": {"user_info": {"name": "Trainer"}}}

    FakeUmaClient.login_hook = rotate_auth_key

    result = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))

    assert result["success"] is True
    assert saved_auth_keys == [CHAIN_AUTH_KEY, ROTATED_AUTH_KEY]


def test_staged_transition_config_is_isolated_by_x_account(
    flow, tmp_path, monkeypatch, drop_sessions,
):
    manager = get_session_manager()
    session_a = manager.get("steam-flow-a")
    session_b = manager.get("steam-flow-b")
    staged_a = {**STAGED_TRANSITION_WITH_AUTH, "udid": "device-a"}
    staged_b = {**STAGED_TRANSITION_WITH_AUTH, "udid": "device-b"}
    session_a.pending_transition_config = dict(staged_a)
    session_b.pending_transition_config = dict(staged_b)
    _install_successful_chain()
    monkeypatch.setattr(account_store, "save_account_config", lambda name, cfg: True)
    _, client = make_client(tmp_path)

    response = client.post(
        "/api/auth/transition-code/chain",
        json={"input_viewer_id": VALID_TRAINER_ID, "password": VALID_PASSWORD},
        headers={"X-Account": "steam-flow-a"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert FakeUmaClient.instances[0].udid_str == "device-a"
    assert session_a.pending_transition_config == {}
    assert session_b.pending_transition_config == staged_b
    drop_sessions("steam-flow-a", "steam-flow-b")


def test_second_login_after_chain_uses_stored_auth_without_bootstrap(
    flow, monkeypatch,
):
    flow.pending_transition_config = dict(STAGED_TRANSITION_WITH_AUTH)
    _install_successful_chain()
    stored = {}
    bootstrap_calls = []

    def save_config(name, cfg):
        stored.clear()
        stored.update(cfg)
        return True

    monkeypatch.setattr(account_store, "save_account_config", save_config)
    monkeypatch.setattr(
        account_store,
        "load_account_config",
        lambda name: dict(stored) if stored else None,
    )
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_steam_account",
        lambda **kwargs: bootstrap_calls.append(kwargs),
    )

    chained = asyncio.run(AuthService(flow).chain_transition_code(SimpleNamespace(
        input_viewer_id=VALID_TRAINER_ID,
        password=VALID_PASSWORD,
    )))
    logged_in = _login(
        flow,
        steam_id=STAGED_TRANSITION["steam_id"],
        steam_session_ticket="second-ticket",
    )

    assert chained["success"] is True
    assert logged_in["success"] is True
    assert logged_in["state"] == "authenticated"
    assert bootstrap_calls == []
    assert FakeUmaClient.events.count("wire:tool/start_session") == 1
    assert FakeUmaClient.events.count("start_session") == 2


def test_account_link_error_codes_match_client_binary_symbols():
    assert ACCOUNT_LINK_ERROR_CODES == {
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
