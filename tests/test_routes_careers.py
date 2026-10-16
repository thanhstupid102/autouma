"""FastAPI TestClient characterization -- /api/career + /api/selection (Phase 0).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
account-scoped career routes when there is NO logged-in client (the "Not logged
in" envelopes, the default runner snapshot, the safe stop/pause/resume no-ops)
plus the selection route, so the strangle-the-monolith refactor can be verified
byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
  * No route here may reach a live game client: the session has none, and the
    envelopes below are exactly what pins that.
"""

from tests._helpers import make_client


class TestNoClientCareerRoutes:
    def test_career_start_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post(
            "/api/career/start",
            json={
                "card_id": 0,
                "support_card_ids": [],
                "friend_viewer_id": 0,
                "friend_card_id": 0,
                "parent_id_1": 0,
                "parent_id_2": 0,
            },
            headers={"X-Account": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_career_run_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post(
            "/api/career/run", json={}, headers={"X-Account": "tester"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_career_runner_status_default_shape(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/career/runner", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["runner"]["running"] is False
        assert isinstance(body["runner"]["loop_active"], bool)

    def test_career_event_info_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/career/event-info", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_career_runner_stop_pause_resume_burn_clocks_are_safe_no_ops(self, tmp_path):
        _, client = make_client(tmp_path)
        headers = {"X-Account": "tester"}

        for path, payload in (
            ("/api/career/runner/stop", None),
            ("/api/career/runner/pause", None),
            ("/api/career/runner/resume", None),
        ):
            resp = client.post(path, json=payload, headers=headers)
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert "runner" in body

        resp = client.patch(
            "/api/career/runner", json={"burn_clocks": True}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "runner" in body

    def test_career_friends_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get(
            "/api/career/friends", headers={"X-Account": "tester"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_career_action_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post(
            "/api/career/action",
            json={"command_type": 0, "command_id": 0, "current_turn": 0, "current_vital": 0},
            headers={"X-Account": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_career_delete_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post(
            "/api/career/delete", json={}, headers={"X-Account": "tester"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_parents_delete_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.request(
            "DELETE",
            "/api/parents",
            json={"instance_ids": []},
            headers={"X-Account": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}

    def test_parents_refresh_not_logged_in(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post(
            "/api/parents/refresh",
            headers={"X-Account": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "Not logged in"}


class TestSelectionRoute:
    def test_update_selection_persists_on_session(self, tmp_path):
        _, client = make_client(tmp_path)
        selection = {"deck": 1, "friend": 111, "trainee": 222, "veterans": [1, 2]}
        resp = client.post(
            "/api/selection",
            json={"selection": selection},
            headers={"X-Account": "tester"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
