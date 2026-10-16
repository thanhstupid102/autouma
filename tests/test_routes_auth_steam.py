"""FastAPI TestClient characterization -- /api/auth + Steam QR (Phase 0).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
auth/session routes with no logged-in client, plus the Steam QR start/poll flow
and its process-wide `add_lock` handling on every early-return and failure path.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline; saved Steam tokens land under tmp_path.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
  * The route that would reach Steam is exercised through an offline
    QrLoginSession fake patched in at the service import site.
"""

from tests._helpers import make_client


class TestNoClientLoginSessionSteamAuth:
    def test_login_without_any_credentials_or_saved_account(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post("/api/auth/login", json={}, headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {
            "success": False,
            "state": "needs_steam_login",
        }

    def test_login_returns_steam_signup_disabled_from_bootstrap(
            self, tmp_path, monkeypatch, drop_sessions):
        from types import SimpleNamespace

        from uma_api import bootstrap

        monkeypatch.setattr(
            bootstrap,
            "bootstrap_steam_account",
            lambda **_kwargs: SimpleNamespace(
                state=bootstrap.BootstrapState.STEAM_SIGNUP_DISABLED,
                config={},
            ),
        )
        _, client = make_client(tmp_path)
        try:
            response = client.post(
                "/api/auth/login",
                json={
                    "steam_id": "76561190000000001",
                    "steam_session_ticket": "session-ticket",
                },
                headers={"X-Account": "tester"},
            )
            assert response.status_code == 200
            assert response.json() == {
                "success": False,
                "state": "steam_signup_disabled",
            }
        finally:
            drop_sessions("tester")

    def test_session_status_without_login(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/auth/session", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {"success": False}

    def test_session_refresh_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post("/api/auth/session/refresh", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_steam_qr_poll_idle_without_a_started_session(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/auth/steam/qr/poll", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "idle"}

    # QR start/poll: the real QrLoginSession spawns a 'node qr_login.js'
    # subprocess that talks to Steam's network, so every test below patches a
    # fake in at the steam_service import site and characterizes the service's
    # own logic: lock handling, error mapping, and the poll->token handoff.

    class _FakeQr:
        def __init__(self, snap, refresh_token=""):
            self._snap = dict(snap)
            self._token = refresh_token
            self.started = 0

        def start(self):
            self.started += 1

        def snapshot(self):
            return dict(self._snap)

        def take_refresh_token(self):
            return self._token

    def _patch_qr(self, monkeypatch, fake):
        from backend.app.routers.steam.services import steam_service as steam_svc

        monkeypatch.setattr(steam_svc, "QrLoginSession", lambda: fake)

    def test_steam_qr_start_pending_returns_challenge_url_and_frees_lock(
            self, tmp_path, monkeypatch, drop_sessions):
        from uma_api.session import get_session_manager

        fake = self._FakeQr({"challenge_url": "https://s.team/q/1/2", "status": "pending"})
        self._patch_qr(monkeypatch, fake)
        _, client = make_client(tmp_path)
        try:
            resp = client.post("/api/auth/steam/qr/start", headers={"X-Account": "tester"})
            assert resp.status_code == 200
            assert resp.json() == {
                "status": "pending",
                "challenge_url": "https://s.team/q/1/2",
            }
            assert fake.started == 1
            # qr_start releases add_lock in its finally -- polling is lock-free.
            manager = get_session_manager()
            assert manager.add_lock.acquire(blocking=False) is True
            manager.add_lock.release()
        finally:
            drop_sessions("tester")

    def test_steam_qr_start_error_maps_to_500_and_frees_lock(
            self, tmp_path, monkeypatch, drop_sessions):
        from uma_api.session import get_session_manager

        fake = self._FakeQr({"challenge_url": "", "status": "error", "error": "node exploded"})
        self._patch_qr(monkeypatch, fake)
        _, client = make_client(tmp_path)
        try:
            resp = client.post("/api/auth/steam/qr/start", headers={"X-Account": "tester"})
            assert resp.status_code == 500
            assert resp.json() == {"detail": "node exploded"}
            manager = get_session_manager()
            assert manager.add_lock.acquire(blocking=False) is True
            manager.add_lock.release()
        finally:
            drop_sessions("tester")
    def test_steam_qr_start_409_while_another_add_holds_the_lock(
            self, tmp_path, monkeypatch, drop_sessions):
        from uma_api.session import get_session_manager

        fake = self._FakeQr({"challenge_url": "https://s.team/q/1/2", "status": "pending"})
        self._patch_qr(monkeypatch, fake)
        _, client = make_client(tmp_path)
        manager = get_session_manager()
        assert manager.add_lock.acquire(blocking=False) is True
        try:
            resp = client.post("/api/auth/steam/qr/start", headers={"X-Account": "tester"})
            assert resp.status_code == 409
            assert resp.json() == {"detail": "Another account add is in progress"}
            # The 409 path must NOT release the holder's lock.
            assert manager.add_lock.acquire(blocking=False) is False
            assert fake.started == 0
        finally:
            manager.add_lock.release()
            drop_sessions("tester")

    def test_steam_qr_poll_confirmed_saves_refresh_token(
            self, tmp_path, monkeypatch, drop_sessions):
        import backend.app.domain.account_store as account_store
        from uma_api.session import get_session_manager

        saved = []
        monkeypatch.setattr(
            account_store,
            "save_steam_token",
            lambda *args: saved.append(args) or True,
        )
        _, client = make_client(tmp_path)
        try:
            fake = self._FakeQr(
                {"status": "confirmed", "steam_id": "76561190000000001"},
                refresh_token="rtok-abc",
            )
            # get_session() keys the singleton manager by the sanitized name, so
            # priming the session here is exactly what the route will see.
            session = get_session_manager().get("tester")
            session._qr = fake

            resp = client.get("/api/auth/steam/qr/poll", headers={"X-Account": "tester"})
            assert resp.status_code == 200
            assert resp.json() == {"status": "confirmed", "steam_id": "76561190000000001"}
            assert saved == [("tester", "rtok-abc", "76561190000000001")]
        finally:
            drop_sessions("tester")

    def test_steam_qr_poll_secret_store_failure_is_terminal(
            self, tmp_path, monkeypatch, drop_sessions):
        import backend.app.domain.account_store as account_store
        from uma_api.secret_store import SecretStoreUnavailableError
        from uma_api.session import get_session_manager

        def fail_save(*_args):
            raise SecretStoreUnavailableError("passphrase-must-not-leak")

        monkeypatch.setattr(account_store, "save_steam_token", fail_save)
        _, client = make_client(tmp_path)
        try:
            fake = self._FakeQr(
                {"status": "confirmed", "steam_id": "76561190000000001"},
                refresh_token="token-must-not-leak",
            )
            get_session_manager().get("tester")._qr = fake

            resp = client.get("/api/auth/steam/qr/poll", headers={"X-Account": "tester"})

            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "error"
            assert body["error"] == (
                "Steam QR was confirmed, but the refresh token could not be saved because "
                "secure storage is unavailable or the state directory is not writable. "
                "Configure UMA_SECRET_PASSPHRASE or UMA_SECRET_PASSPHRASE_FILE, verify the "
                "state directory, then request a new QR code."
            )
            assert "token-must-not-leak" not in body["error"]
            assert "passphrase-must-not-leak" not in body["error"]
        finally:
            drop_sessions("tester")

    def test_steam_qr_poll_false_save_is_terminal(
            self, tmp_path, monkeypatch, drop_sessions):
        import backend.app.domain.account_store as account_store
        from uma_api.session import get_session_manager

        monkeypatch.setattr(account_store, "save_steam_token", lambda *_args: False)
        _, client = make_client(tmp_path)
        try:
            fake = self._FakeQr(
                {"status": "confirmed", "steam_id": "76561190000000001"},
                refresh_token="rtok-abc",
            )
            get_session_manager().get("tester")._qr = fake

            resp = client.get("/api/auth/steam/qr/poll", headers={"X-Account": "tester"})

            assert resp.status_code == 200
            assert resp.json()["status"] == "error"
            assert "UMA_SECRET_PASSPHRASE" in resp.json()["error"]
            assert "UMA_SECRET_PASSPHRASE_FILE" in resp.json()["error"]
        finally:
            drop_sessions("tester")


def test_recapture_routes_are_removed(tmp_path):
    app, _ = make_client(tmp_path)
    paths = {route.path for route in app.routes}

    assert "/api/auth/recapture" not in paths
    assert "/api/auth/recapture/status" not in paths
