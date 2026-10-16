import asyncio

import pytest

from backend.app.routers.auth.services.auth_service import AuthService
from uma_api.session import get_session_manager
import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point
from backend.app.routers.auth.schemas.auth import LoginRequest


VALID_CFG = {
    "app_ver": "1.0.0",
    "res_ver": "1",
    "auth_key_len": 48,
    "viewer_id": 12345,
    "udid": "00000000-0000-0000-0000-000000000000",
    "auth_key": "ab" * 48,
    "steam_id": "steamid-1",
    "steam_session_ticket": "stale-captured-ticket",
}


class FakeUmaClient:
    instances: list["FakeUmaClient"] = []

    def __init__(self, cfg, trace_enabled=False):
        self.cfg = dict(cfg)
        self.viewer_id = cfg.get("viewer_id", 1)
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        FakeUmaClient.instances.append(self)

    def login(self):
        # The freshly minted ticket works; the stale captured ticket is rejected.
        if self.cfg.get("steam_session_ticket") == "fresh-from-refresh":
            return {"data": {}}
        raise Exception("login rejected: stale steam ticket")

    def load_career(self):
        return {"data": {}}

    def call(self, *args, **kwargs):
        return {}

    def bind_api_warehouse(self, base_dir, account):
        # Mirror UmaClient.bind_api_warehouse: chained in login()'s make_client().
        return self

    def auth_config_snapshot(self):
        return dict(self.cfg)


@pytest.fixture
def m(monkeypatch):
    import uma_api.client as client_module
    import career_bot.delay as delay_module

    FakeUmaClient.instances = []
    monkeypatch.setattr(client_module, "UmaClient", FakeUmaClient)
    # GateKeeper passthrough: keep timing wrapper out of the auth-recovery test.
    monkeypatch.setattr(delay_module, "GateKeeper", lambda client, *a, **k: client)
    monkeypatch.setattr(rank_point, "chara_map", {})
    monkeypatch.setattr(rank_point, "support_map", {})
    # Keep the tests hermetic: a successful login persists the account config
    # (save_account_config) -- stub it so no uma_runtime/accounts/tester.json is
    # written. Individual tests override this when they assert on it.
    monkeypatch.setattr(account_store, "save_account_config", lambda name, cfg: None)
    monkeypatch.setenv("SWEEPY_ACCOUNT", "tester")
    return account_store


def run_login(session=None, **kwargs):
    req = LoginRequest(**kwargs)
    if session is None:
        session = get_session_manager().get("tester")
    return asyncio.run(AuthService(session).login(req))


def test_silent_login_without_saved_refresh_token_needs_steam_login(m, monkeypatch):
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = {}
    monkeypatch.setattr(m, "load_steam_token", lambda name: None)

    result = run_login(session=session)

    assert result == {"success": False, "state": "needs_steam_login"}
    assert FakeUmaClient.instances == []


def test_rejected_saved_refresh_token_is_cleared_then_needs_steam_login(
    m, monkeypatch,
):
    import uma_api.client as client_module

    session = get_session_manager().get("tester")
    session.pending_game_auth_config = {}
    cleared_tokens = []

    monkeypatch.setattr(m, "load_steam_token", lambda name: {
        "refresh_token": "rejected-refresh-token",
    })
    monkeypatch.setattr(
        m, "clear_steam_token", lambda name: cleared_tokens.append(name),
    )
    monkeypatch.setattr(
        client_module, "get_ticket",
        lambda **kwargs: (_ for _ in ()).throw(Exception("TOKEN_INVALID")),
    )

    result = run_login(session=session)

    assert result == {"success": False, "state": "needs_steam_login"}
    assert cleared_tokens == ["tester"]
    assert FakeUmaClient.instances == []


def test_silent_login_with_saved_refresh_token_reaches_stored_auth(m, monkeypatch):
    import uma_api.client as client_module
    from uma_api import bootstrap

    session = get_session_manager().get("tester")
    session.pending_game_auth_config = {}
    ticket_calls = []

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        ticket_calls.append(refresh_token)
        assert not (u or p or c)
        return "steamid-1", "fresh-from-refresh", "rotated-refresh-token"

    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(m, "load_steam_token", lambda name: {
        "refresh_token": "saved-refresh-token",
    })
    monkeypatch.setattr(m, "load_account_config", lambda name: dict(VALID_CFG))
    monkeypatch.setattr(
        bootstrap, "bootstrap_steam_account",
        lambda **kwargs: pytest.fail("stored game auth must be used"),
    )

    result = run_login(session=session)

    assert result["state"] == "authenticated"
    assert ticket_calls == ["saved-refresh-token"]
    assert FakeUmaClient.instances[0].cfg["steam_session_ticket"] == "fresh-from-refresh"


def test_captured_ticket_failure_recovers_via_saved_refresh_token(m, monkeypatch):
    import backend.app.domain.account_store as account_store

    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)

    ticket_calls = []

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        ticket_calls.append({"refresh_token": refresh_token, "username": u})
        if refresh_token:
            return "steamid-1", "fresh-from-refresh", "rotated-refresh-token"
        raise AssertionError("manual Steam login should not be needed when a refresh token works")

    saved_tokens = []
    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: {
        "refresh_token": "saved-refresh-token",
        "steam_id": "steamid-1",
    })
    monkeypatch.setattr(account_store, "save_steam_token", lambda name, tok, sid="": saved_tokens.append((name, tok, sid)) or True)
    monkeypatch.setattr(account_store, "clear_steam_token", lambda name: None)

    result = run_login(session=session, username="", password="")

    assert result.get("success") is True
    assert any(call["refresh_token"] == "saved-refresh-token" for call in ticket_calls)
    # The rotated refresh token from the successful retry is persisted for next time.
    assert saved_tokens and saved_tokens[-1][1] == "rotated-refresh-token"


def test_typed_credentials_override_staged_ticket(m, monkeypatch):
    # Typed credentials now precede the ticket staged by capture.
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)  # carries the stale captured ticket

    ticket_calls = []

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        ticket_calls.append({"username": u, "password": p, "refresh_token": refresh_token})
        if u and p:
            return "steamid-typed", "fresh-from-refresh", "typed-refresh-token"
        raise AssertionError("typed credentials must be used, not a captured/refresh path")

    saved = []
    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(m, "load_steam_token", lambda name: None)
    monkeypatch.setattr(m, "save_steam_token", lambda name, tok, sid="": saved.append((name, tok, sid)) or True)
    monkeypatch.setattr(m, "save_account_config", lambda name, cfg: None)

    result = run_login(session=session, username="trainer", password="pw")

    assert result.get("success") is True
    # The form-creds branch fired (get_ticket called with the typed username/password).
    assert ticket_calls and ticket_calls[0]["username"] == "trainer"
    # PRIMARY login attempt used the freshly minted ticket, NOT the stale captured one,
    # and the chosen ticket was written into cfg (unconditional bind).
    assert FakeUmaClient.instances[0].cfg["steam_session_ticket"] == "fresh-from-refresh"
    assert FakeUmaClient.instances[0].cfg["steam_id"] == "steamid-typed"
    assert "steam_password_seed" not in FakeUmaClient.instances[0].cfg


def test_login_restores_saved_team_selection(m, monkeypatch):
    import backend.app.domain.account_store as account_store

    # The remembered per-account team must be restored into session.selection on login
    # (reset_runtime clears it first; the UI then hydrates from /api/auth/session).
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        return "sid", "fresh-from-refresh", "tok"

    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(m, "load_steam_token", lambda name: None)
    monkeypatch.setattr(m, "save_steam_token", lambda *a, **k: True)
    monkeypatch.setattr(m, "save_account_config", lambda name, cfg: None)
    saved_sel = {
        "deck": {"name": "X"}, "friend": None, "trainee": {"id": 1},
        "veterans": [], "event": {"enabled": False, "level": 1, "boost": False},
    }
    monkeypatch.setattr(account_store, "load_selection", lambda name: saved_sel)

    result = run_login(session=session, username="u", password="p")

    assert result.get("success") is True
    assert session.selection == saved_sel


def test_typed_credentials_precede_staged_ticket(m, monkeypatch):
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)  # captured ticket present

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        if u and p:
            return "steamid-typed", "fresh-from-refresh", "typed-refresh-token"
        raise AssertionError("no refresh path expected in this scenario")

    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(m, "load_steam_token", lambda name: None)
    monkeypatch.setattr(m, "save_steam_token", lambda name, tok, sid="": True)
    monkeypatch.setattr(m, "save_account_config", lambda name, cfg: None)

    result = run_login(session=session, username="trainer", password="pw")

    assert result.get("success") is True
    assert FakeUmaClient.instances[0].cfg["steam_session_ticket"] == "fresh-from-refresh"


def test_manual_fallback_unpacks_three_tuple_and_persists_token(m, monkeypatch):
    import backend.app.domain.account_store as account_store

    # No saved refresh token: the only recovery path is a manual Steam login.
    # get_ticket returns a 3-tuple (steam_id, ticket, refresh_token); the fallback
    # must unpack all three without a ValueError and persist the new refresh token.
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        assert not refresh_token, "no saved refresh token in this scenario"
        return "steamid-1", "fresh-from-refresh", "minted-refresh-token"

    saved_tokens = []
    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: None)
    monkeypatch.setattr(account_store, "save_steam_token", lambda name, tok, sid="": saved_tokens.append((name, tok, sid)) or True)

    result = run_login(session=session, username="trainer", password="pw")

    assert result.get("success") is True
    assert saved_tokens and saved_tokens[-1][1] == "minted-refresh-token"


def test_recovery_minted_ticket_reaches_save_account_config(m, monkeypatch):
    import backend.app.domain.account_store as account_store

    # _LoginAttempts.run() re-binds steam_id/steam_session_ticket on the CALLER's cfg
    # dict (in place, not on a copy), so the config persisted after a successful login
    # describes the ticket that ACTUALLY worked. Hand it a copy and the account file
    # would keep pointing at the dead captured ticket's Steam id.
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)  # steamid-1 / stale-captured-ticket

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        if refresh_token:
            # Deliberately a DIFFERENT steam_id than the stale captured one.
            return "steamid-recovered", "fresh-from-refresh", "rotated-refresh-token"
        raise AssertionError("manual Steam login should not be needed here")

    saved_configs = []
    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: {
        "refresh_token": "saved-refresh-token",
    })
    monkeypatch.setattr(account_store, "save_steam_token", lambda name, tok, sid="": True)
    monkeypatch.setattr(account_store, "clear_steam_token", lambda name: None)
    monkeypatch.setattr(
        account_store, "save_account_config",
        lambda name, cfg: saved_configs.append((name, dict(cfg))) or True,
    )

    result = run_login(session=session, username="", password="")

    assert result.get("success") is True
    assert saved_configs, "a fresh auth config must be persisted after login"
    _name, persisted = saved_configs[-1]
    assert persisted["steam_id"] == "steamid-recovered"
    assert persisted["steam_session_ticket"] == "fresh-from-refresh"


def test_2fa_restash_preserves_the_staged_game_auth(m, monkeypatch):
    import backend.app.domain.account_store as account_store

    # Steam Guard is raised while resolving typed credentials, before any game call.
    # The staged game auth must remain available for the code retry.
    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)

    def fake_get_ticket(u="", p="", c="", refresh_token=""):
        if refresh_token:
            # Mints a ticket the game still rejects -> cfg is re-bound, login fails again.
            return "steamid-refreshed", "refresh-minted-ticket", ""
        raise Exception("STEAM_GUARD_REQUIRED")

    import uma_api.client as client_module
    monkeypatch.setattr(client_module, "get_ticket", fake_get_ticket)
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: {
        "refresh_token": "saved-refresh-token",
    })
    monkeypatch.setattr(account_store, "save_steam_token", lambda *a, **k: True)
    monkeypatch.setattr(account_store, "clear_steam_token", lambda name: None)

    result = run_login(session=session, username="trainer", password="pw")

    assert result == {
        "success": False,
        "state": "needs_steam_guard",
        "needs_2fa": True,
    }
    stashed = session.pending_game_auth_config
    assert stashed["steam_id"] == "steamid-1"
    assert stashed["steam_session_ticket"] == "stale-captured-ticket"
