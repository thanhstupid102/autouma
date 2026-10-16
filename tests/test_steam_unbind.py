import ast

from backend.app.deps import get_session
from backend.app.routers.auth.schemas.auth import SteamUnbindRequest
from backend.app.routers.auth.services import auth_service
from backend.app.routers.auth.services.auth_service import AuthService
from tests._helpers import PROJECT_ROOT, make_client
from uma_api.crypto import make_md5_hex
from uma_api.errors import ApiError


VALID_AUTH = {
    "viewer_id": 123456789,
    "udid": "target-device",
    "auth_key": "ab" * 48,
}
SOURCE_AUTH = {
    "viewer_id": 987654321,
    "udid": "source-device",
    "auth_key": "cd" * 48,
}
REQUEST = {
    "confirm_account_name": "target",
    "link_password": "LinkPass9",
}


class RecordingClient:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "data_headers": {"result_code": 1},
            "data": {},
        }
        self.error = error
        self.calls = []

    def call(self, endpoint, args=None, **kwargs):
        self.calls.append((endpoint, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _setup_endpoint(tmp_path):
    app, client = make_client(tmp_path)
    session = app.state.ctx.session_manager.get("target")
    app.dependency_overrides[get_session] = lambda: session
    return app, client, session


def _save_account(account_store, name, cfg, *, refresh_token=None):
    assert account_store.save_account_config(name, cfg) is True
    if refresh_token:
        assert account_store.save_steam_token(
            name,
            refresh_token,
            f"steam-{name}",
        ) is True


def _install_source_account(account_store):
    _save_account(
        account_store,
        "source",
        SOURCE_AUTH,
        refresh_token="source-refresh",
    )


def _successful_preview():
    return RecordingClient(response={
        "data_headers": {"result_code": 1},
        "data": {
            "name": "Recovery Trainer",
            "request_user_name": "Source Trainer",
        },
    })


def test_wrong_confirmation_returns_400_without_any_wire_call(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    target_client = RecordingClient()
    session.client = target_client
    monkeypatch.setattr(
        auth_service,
        "_login_stored_account",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected login")),
    )

    response = client.post(
        "/api/auth/steam/unbind",
        json={**REQUEST, "confirm_account_name": "Target"},
    )

    assert response.status_code == 400
    assert target_client.calls == []


def test_idle_guard_runs_before_confirmation_and_auth_checks(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, _ = _setup_endpoint(tmp_path)
    monkeypatch.setattr(
        auth_service,
        "require_idle",
        lambda session: {"success": False, "detail": "busy"},
    )
    monkeypatch.setattr(
        tmp_account_store,
        "load_account_config",
        lambda name: (_ for _ in ()).throw(AssertionError("auth loaded")),
    )

    response = client.post(
        "/api/auth/steam/unbind",
        json={**REQUEST, "confirm_account_name": "wrong"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "state": "failed",
        "detail": "busy",
    }


def test_missing_stored_auth_returns_400_without_any_wire_call(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    target_client = RecordingClient()
    session.client = target_client
    monkeypatch.setattr(
        auth_service,
        "_login_stored_account",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected login")),
    )

    response = client.post("/api/auth/steam/unbind", json=REQUEST)

    assert response.status_code == 400
    assert target_client.calls == []


def test_preflight_uses_a_different_account_and_string_target_viewer_id(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    _install_source_account(tmp_account_store)
    source_client = _successful_preview()
    login_calls = []

    def fake_login(account_name, cfg, steam_token):
        login_calls.append((account_name, cfg, steam_token))
        return source_client

    monkeypatch.setattr(auth_service, "_login_stored_account", fake_login)

    response = client.post(
        "/api/auth/steam/unbind/preflight",
        json=REQUEST,
    )

    assert response.status_code == 200
    assert response.json()["state"] == "verified"
    assert login_calls[0][0] == "source"
    assert source_client.calls == [
        (
            "account/get_by_transition_code",
            {
                "password": make_md5_hex(REQUEST["link_password"]),
                "input_viewer_id": "123456789",
            },
            {},
        ),
    ]
    assert REQUEST["link_password"] not in str(source_client.calls[0][1])
    assert isinstance(source_client.calls[0][1]["input_viewer_id"], str)
    assert session.name == "target"


def test_unbind_with_link_password_preflights_then_uses_empty_payload(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    _install_source_account(tmp_account_store)
    source_client = _successful_preview()
    target_client = RecordingClient()
    session.client = target_client
    monkeypatch.setattr(
        auth_service,
        "_login_stored_account",
        lambda account_name, cfg, steam_token: source_client,
    )

    response = client.post("/api/auth/steam/unbind", json=REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "unbound"
    assert body["recovery_verified"] == "verified"
    assert body["name"] == "Recovery Trainer"
    assert target_client.calls == [
        ("account/steam_chain_disconnect", {}, {}),
    ]


def test_preflight_700_refuses_unbind_with_symbolic_error(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    _install_source_account(tmp_account_store)
    target_client = RecordingClient()
    session.client = target_client
    source_client = RecordingClient(error=ApiError(
        700,
        "account/get_by_transition_code",
        "invalid password",
    ))
    monkeypatch.setattr(
        auth_service,
        "_login_stored_account",
        lambda account_name, cfg, steam_token: source_client,
    )

    response = client.post("/api/auth/steam/unbind", json=REQUEST)

    assert response.status_code == 200
    assert response.json()["error_code"] == "TRANSITIONPASSWORD_INVALID"
    assert "could not be proven" in response.json()["detail"]
    assert target_client.calls == []


def test_unbind_without_link_password_skips_preflight_and_proceeds(
    tmp_path, tmp_account_store, monkeypatch,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    target_client = RecordingClient()
    session.client = target_client
    monkeypatch.setattr(
        auth_service,
        "_login_stored_account",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected preflight")),
    )

    response = client.post(
        "/api/auth/steam/unbind",
        json={"confirm_account_name": "target"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "unbound"
    assert response.json()["recovery_verified"] == "not_checked"
    assert "not checked" in response.json()["detail"]
    assert target_client.calls == [("account/steam_chain_disconnect", {}, {})]


def test_force_is_ignored_by_the_unbind_request_schema():
    request = SteamUnbindRequest.model_validate({
        "confirm_account_name": "target",
        "force": True,
    })

    assert request.link_password is None
    assert "force" not in request.model_dump()


def test_unbind_still_enforces_exact_name_confirmation(
    tmp_path, tmp_account_store,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    target_client = RecordingClient()
    session.client = target_client

    response = client.post(
        "/api/auth/steam/unbind",
        json={
            "confirm_account_name": "wrong",
        },
    )

    assert response.status_code == 400
    assert target_client.calls == []


def test_709_is_terminal_and_disconnect_is_not_retried(
    tmp_path, tmp_account_store,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    target_client = RecordingClient(error=ApiError(
        709,
        "account/steam_chain_disconnect",
        "still chained",
    ))
    session.client = target_client

    response = client.post(
        "/api/auth/steam/unbind",
        json={"confirm_account_name": "target"},
    )

    assert response.status_code == 200
    assert response.json()["error_code"] == "STEAM_ACCOUNT_REMOVE_CHAINED"
    assert len(target_client.calls) == 1


def test_success_records_timestamp_without_deleting_stored_auth(
    tmp_path, tmp_account_store,
):
    _, client, session = _setup_endpoint(tmp_path)
    _save_account(tmp_account_store, "target", VALID_AUTH)
    session.client = RecordingClient()

    response = client.post(
        "/api/auth/steam/unbind",
        json={"confirm_account_name": "target"},
    )

    assert response.status_code == 200
    stored = tmp_account_store.load_account_config("target")
    assert stored["viewer_id"] == VALID_AUTH["viewer_id"]
    assert stored["udid"] == VALID_AUTH["udid"]
    assert stored["auth_key"] == VALID_AUTH["auth_key"]
    assert stored["steam_unbound_at"] == response.json()["steam_unbound_at"]

    accounts = client.get("/api/accounts").json()["accounts"]
    target = next(account for account in accounts if account["name"] == "target")
    assert target["steam_unbound_at"] == stored["steam_unbound_at"]


def test_leave_session_clears_pending_transition_config(tmp_path):
    app, _ = make_client(tmp_path)
    session = app.state.ctx.session_manager.get("target")
    session.pending_game_auth_config = {"steam_session_ticket": "staged"}
    session.pending_transition_config = {"udid": "fresh-device"}

    assert AuthService(session).leave_session() == {"success": True}
    assert session.pending_game_auth_config == {}
    assert session.pending_transition_config == {}


def test_disconnect_transport_has_only_the_explicit_unbind_service_caller():
    callers = []
    for path in (PROJECT_ROOT / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "steam_chain_disconnect"
            ):
                callers.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert callers == [
        "backend/app/routers/auth/services/auth_service.py",
    ]
