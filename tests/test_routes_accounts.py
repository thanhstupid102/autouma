"""FastAPI TestClient characterization -- /api/accounts + isolation (Phase 0).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
account list/import/export/delete round trip and of per-account isolation
(the process-wide SessionManager singleton must not leak state between
accounts), so the strangle-the-monolith refactor can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline; account files land under tmp_path, never the repo.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
"""

import base64

from uma_api import account_io

from tests._helpers import make_client


class TestAccountsCrud:
    def test_list_export_import_delete_round_trip(self, tmp_path):
        _, client = make_client(tmp_path)

        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "accounts": []}

        bundle_payload = {"acct1": {"game": {"foo": "bar"}, "steam": None}}
        blob = account_io.encrypt_bundle(bundle_payload, "pw123")
        b64 = base64.b64encode(blob).decode()

        resp = client.post(
            "/api/accounts/import",
            json={"bundle_b64": b64, "passphrase": "pw123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"success": True, "imported": ["acct1"], "skipped": []}
        stored = (tmp_path / "uma_runtime" / "accounts" / "acct1.json").read_bytes()
        assert stored.startswith(b"UMAENC1")
        assert b"foo" not in stored
        assert b"bar" not in stored

        resp = client.get("/api/accounts")
        names = {a["name"] for a in resp.json()["accounts"]}
        assert names == {"acct1"}
        entry = resp.json()["accounts"][0]
        assert entry["logged_in"] is False
        assert entry["running"] is False

        # Re-import without overwrite: existing account is skipped, not clobbered.
        resp = client.post(
            "/api/accounts/import",
            json={"bundle_b64": b64, "passphrase": "pw123"},
        )
        assert resp.json() == {"success": True, "imported": [], "skipped": ["acct1"]}

        # Export round-trips through the same encryption scheme.
        resp = client.post(
            "/api/accounts/export",
            json={"names": ["acct1"], "passphrase": "pw123"},
        )
        assert resp.status_code == 200
        assert "application/octet-stream" in resp.headers["content-type"]
        decrypted = account_io.decrypt_bundle(resp.content, "pw123")
        assert decrypted["acct1"]["game"] == {"foo": "bar"}

        # Export of an unknown account -> 404.
        resp = client.post(
            "/api/accounts/export",
            json={"names": ["ghost"], "passphrase": "pw123"},
        )
        assert resp.status_code == 404

        # Export with no passphrase -> 400.
        resp = client.post(
            "/api/accounts/export",
            json={"names": ["acct1"], "passphrase": ""},
        )
        assert resp.status_code == 400

        # Import of a garbage bundle -> 400.
        resp = client.post(
            "/api/accounts/import",
            json={"bundle_b64": "not-valid-base64!!!", "passphrase": "x"},
        )
        assert resp.status_code == 400

        # Import with the right encoding but wrong passphrase -> 400.
        resp = client.post(
            "/api/accounts/import",
            json={"bundle_b64": b64, "passphrase": "wrong-pw"},
        )
        assert resp.status_code == 400

        resp = client.delete("/api/accounts/acct1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "acct1.json" in body["deleted"]

        resp = client.get("/api/accounts")
        assert resp.json() == {"success": True, "accounts": []}

    def test_delete_unknown_account_is_a_no_op_success(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.delete("/api/accounts/never-existed")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "deleted": []}


class TestAccountIsolation:
    def test_turn_delay_is_not_shared_across_accounts(self, tmp_path, drop_sessions):
        """POST /api/settings/turn-delay is served via backend.app.deps.get_session,
        which resolves through the process-wide SessionManager singleton. A
        tmp_path app still shares that singleton for this dependency. Account isolation must
        still hold: a write for tester_a must not leak into tester_b."""
        _, client = make_client(tmp_path)
        try:
            baseline = client.get(
                "/api/settings/turn-delay", headers={"X-Account": "tester_b"}
            ).json()

            resp = client.post(
                "/api/settings/turn-delay",
                json={"min": 9.0, "max": 9.5, "disabled": False},
                headers={"X-Account": "tester_a"},
            )
            assert resp.status_code == 200
            assert resp.json()["min"] == 9.0

            after_a = client.get(
                "/api/settings/turn-delay", headers={"X-Account": "tester_a"}
            ).json()
            assert after_a["min"] == 9.0
            assert after_a["max"] == 9.5

            after_b = client.get(
                "/api/settings/turn-delay", headers={"X-Account": "tester_b"}
            ).json()
            assert after_b == baseline
            assert after_b["min"] != 9.0
        finally:
            drop_sessions("tester_a", "tester_b")

    def test_auto_delete_config_is_per_account_file(self, tmp_path):
        """/api/parents/auto-delete-config is a legacy.py route: it is scoped by
        account name directly to a per-account JSON file under base_dir (tmp_path
        here), independent of any session-manager instance identity."""
        _, client = make_client(tmp_path)

        resp = client.post(
            "/api/parents/auto-delete-config",
            json={"enabled": True, "min_blue": 3},
            headers={"X-Account": "iso_a"},
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["enabled"] is True
        assert resp.json()["config"]["min_blue"] == 3

        resp_b = client.get(
            "/api/parents/auto-delete-config", headers={"X-Account": "iso_b"}
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["config"]["enabled"] is False
        assert resp_b.json()["config"]["min_blue"] == 0

        resp_a = client.get(
            "/api/parents/auto-delete-config", headers={"X-Account": "iso_a"}
        )
        assert resp_a.json()["config"]["enabled"] is True
        assert resp_a.json()["config"]["min_blue"] == 3
