"""FastAPI TestClient characterization -- /api/settings (Phase 0 safety net).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
settings routes (turn-delay + discord-webhook) so the strangle-the-monolith
refactor can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
  * Anything that would reach the network (the discord webhook send) is
    exercised through an offline fake patched in at the service import site.
"""

import json

from tests._helpers import make_client
from backend.app.routers.settings.services.discord import redact_webhook_url


TOKEN_MASK = "••••••••"


def test_redact_webhook_url_edge_cases():
    assert redact_webhook_url("") is None
    assert redact_webhook_url(
        "https://discord.com/api/webhooks/123456"
    ) == TOKEN_MASK
    assert redact_webhook_url(
        "https://discord.com/api/webhooks/123456/x"
    ) == f"https://discord.com/api/webhooks/123456/{TOKEN_MASK}"
    assert redact_webhook_url("operator-custom-webhook") == TOKEN_MASK


class TestSettingsTurnDelay:
    def test_get_returns_defaults_shape(self, tmp_path, drop_sessions):
        _, client = make_client(tmp_path)
        try:
            resp = client.get("/api/settings/turn-delay", headers={"X-Account": "tester"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            for key in ("min", "max", "restore_min", "restore_max", "disabled"):
                assert key in body
            assert isinstance(body["disabled"], bool)
        finally:
            drop_sessions("tester")

    def test_post_sets_value_and_get_reflects_it(self, tmp_path, drop_sessions):
        _, client = make_client(tmp_path)
        try:
            resp = client.post(
                "/api/settings/turn-delay",
                json={"min": 2.5, "max": 6.0, "disabled": False},
                headers={"X-Account": "tester"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body == {
                "success": True,
                "min": 2.5,
                "max": 6.0,
                "restore_min": 2.5,
                "restore_max": 6.0,
                "disabled": False,
            }

            resp2 = client.get("/api/settings/turn-delay", headers={"X-Account": "tester"})
            assert resp2.json()["min"] == 2.5
            assert resp2.json()["max"] == 6.0
        finally:
            drop_sessions("tester")


class TestSettingsDiscordWebhook:
    def test_get_shape(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/settings/discord-webhook")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["configured"] is False
        assert body["webhook_preview"] is None
        assert body["error_mention"] is None
        assert "webhook_url" not in body

    def test_get_redacts_discord_webhook_token(self, tmp_path):
        _, client = make_client(tmp_path)
        token = "abcdefTOKEN-unique-secret"
        webhook_url = f"https://discord.com/api/webhooks/123456/{token}"

        resp = client.post(
            "/api/settings/discord-webhook",
            json={"webhook_url": webhook_url},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "configured": True,
            "error_mention": None,
        }

        resp2 = client.get("/api/settings/discord-webhook")
        body = resp2.json()
        assert body == {
            "success": True,
            "configured": True,
            "webhook_preview": (
                f"https://discord.com/api/webhooks/123456/{TOKEN_MASK}"
            ),
            "error_mention": None,
        }
        assert token not in resp2.text
        assert "webhook_url" not in body
        assert (tmp_path / "uma_runtime" / "discord.json").exists()

    def test_get_hides_unparseable_stored_webhook(self, tmp_path):
        _, client = make_client(tmp_path)
        stored_value = "operator-custom-secret-9f42d6"
        client.post(
            "/api/settings/discord-webhook",
            json={"webhook_url": stored_value},
        )

        resp = client.get("/api/settings/discord-webhook")
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "configured": True,
            "webhook_preview": TOKEN_MASK,
            "error_mention": None,
        }
        assert stored_value not in resp.text

    def test_error_mention_round_trips_without_overwriting_other_config(
        self, tmp_path,
    ):
        _, client = make_client(tmp_path)
        discord_path = tmp_path / "uma_runtime" / "discord.json"
        discord_path.parent.mkdir(exist_ok=True)
        original = {
            "webhook_url": "https://discord.test/webhooks/1/abc",
            "account_name": "Operator Account",
        }
        discord_path.write_text(json.dumps(original), encoding="utf-8")

        resp = client.post(
            "/api/settings/discord-webhook",
            json={"error_mention": "  <@!12345678901234567>  "},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "configured": True,
            "error_mention": "<@12345678901234567>",
        }
        assert json.loads(discord_path.read_text(encoding="utf-8")) == {
            **original,
            "error_mention": {"kind": "user", "id": "12345678901234567"},
        }

        read = client.get("/api/settings/discord-webhook")
        assert read.status_code == 200
        assert read.json()["error_mention"] == "<@12345678901234567>"

    def test_error_mention_input_forms_preserve_user_and_role_kinds(
        self, tmp_path,
    ):
        _, client = make_client(tmp_path)
        discord_path = tmp_path / "uma_runtime" / "discord.json"
        expected_forms = [
            (
                "12345678901234567",
                {"kind": "user", "id": "12345678901234567"},
                "<@12345678901234567>",
            ),
            (
                "<@12345678901234567890>",
                {"kind": "user", "id": "12345678901234567890"},
                "<@12345678901234567890>",
            ),
            (
                "<@!12345678901234567>",
                {"kind": "user", "id": "12345678901234567"},
                "<@12345678901234567>",
            ),
            (
                "<@&12345678901234567890>",
                {"kind": "role", "id": "12345678901234567890"},
                "<@&12345678901234567890>",
            ),
        ]

        for value, stored, formatted in expected_forms:
            resp = client.post(
                "/api/settings/discord-webhook",
                json={"error_mention": value},
            )
            assert resp.status_code == 200
            assert resp.json()["error_mention"] == formatted
            config = json.loads(discord_path.read_text(encoding="utf-8"))
            assert config["error_mention"] == stored

    def test_invalid_error_mentions_are_rejected_without_storing_them(
        self, tmp_path,
    ):
        _, client = make_client(tmp_path)
        discord_path = tmp_path / "uma_runtime" / "discord.json"
        discord_path.parent.mkdir(exist_ok=True)
        original = {
            "webhook_url": "https://discord.test/webhooks/1/abc",
            "account_name": "Operator Account",
        }
        discord_path.write_text(json.dumps(original), encoding="utf-8")

        for value in [
            "1234567890123456",
            "123456789012345678901",
            "not-a-snowflake",
            "   ",
            "@everyone",
        ]:
            resp = client.post(
                "/api/settings/discord-webhook",
                json={"error_mention": value},
            )
            assert resp.status_code == 400
            assert resp.json()["success"] is False
            assert "17-20 digit Discord" in resp.json()["detail"]
            assert json.loads(discord_path.read_text(encoding="utf-8")) == original

    def test_test_endpoint_no_webhook_returns_error(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post("/api/settings/discord-webhook/test")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "No webhook" in body["detail"]

    def test_test_endpoint_sends_via_request_scoped_base_dir(
        self,
        tmp_path,
        monkeypatch,
    ):
        _, client = make_client(tmp_path)
        webhook_url = "https://discord.test/webhooks/1/abc"
        client.post(
            "/api/settings/discord-webhook",
            json={"webhook_url": webhook_url},
        )
        sent_base_dirs = []

        def fake_send_career_summary(source_root, state_root, summary):
            sent_base_dirs.append((source_root, state_root))
            return True

        monkeypatch.setattr(
            "integrations.discord.notify.send_career_summary",
            fake_send_career_summary,
        )
        resp = client.post("/api/settings/discord-webhook/test")
        assert resp.status_code == 200
        assert sent_base_dirs == [(tmp_path, tmp_path / "uma_runtime")]
