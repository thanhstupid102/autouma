"""FastAPI TestClient characterization -- /api/master-data (Phase 0 safety net).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
master-data status/config/generate routes so the strangle-the-monolith refactor
can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
  * `_repo_master_data_tree_state()` snapshots the tracked data/ + assets/ trees
    before and after: a route that fails must not rewrite the repo's JSON.
"""

import uma_data

from tests._helpers import _repo_master_data_tree_state, make_client


class TestMasterDataStatus:
    def test_status_shape(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/master-data/status")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("success", "master_mdb_path", "exists", "access_error", "requires_user_action"):
            assert key in body
        assert isinstance(body["success"], bool)
        assert isinstance(body["master_mdb_path"], str)
        assert isinstance(body["exists"], bool)
        assert isinstance(body["requires_user_action"], bool)

    def test_config_missing_mdb_returns_400(self, tmp_path):
        repo_state = _repo_master_data_tree_state()
        _, client = make_client(tmp_path)

        resp = client.post(
            "/api/master-data/config",
            json={"master_mdb_path": str(tmp_path / "nope.mdb")},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["exists"] is False
        assert body["requires_user_action"] is True
        assert "generated" not in body
        assert _repo_master_data_tree_state() == repo_state

    def test_generate_missing_mdb_returns_400(self, tmp_path):
        repo_state = _repo_master_data_tree_state()
        state_root = tmp_path / "uma_runtime"
        uma_data.set_master_mdb_path(
            tmp_path, tmp_path / "nope.mdb", state_root,
        )
        _, client = make_client(tmp_path)

        resp = client.post("/api/master-data/generate")

        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "detail" in body
        assert _repo_master_data_tree_state() == repo_state
