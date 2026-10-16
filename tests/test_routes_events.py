"""FastAPI TestClient characterization -- /api/events (Phase 0 safety net).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
event catalog/rebuild/refresh routes and the event-choice prefs store, so the
strangle-the-monolith refactor can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
  * The real catalog refresh scrapes gametora.com, so a fake
    `scripts.scrape_gametora_effects` module is patched into sys.modules -- the
    fake pins only the service's own envelope, never touching the network.
"""

from tests._helpers import make_client


class TestEventsCatalog:
    def test_catalog_shape(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/events/catalog")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["success"], bool)
        assert isinstance(body["events"], list)

    def test_rebuild_shape(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.post("/api/events/catalog/rebuild")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["success"], bool)
        assert isinstance(body["count"], int)

    # The real scraper hits gametora.com, so these patch a fake
    # scripts.scrape_gametora_effects module into sys.modules and characterize
    # ONLY the EventService.update_database envelope around it (both paths).
    def _install_fake_scraper(self, monkeypatch, scrape):
        import sys
        import types

        fake = types.ModuleType("scripts.scrape_gametora_effects")
        fake.scrape = scrape
        monkeypatch.setitem(sys.modules, "scripts.scrape_gametora_effects", fake)
        # `from scripts import scrape_gametora_effects` prefers the package
        # attribute when the namespace package is already imported.
        import scripts as scripts_pkg
        monkeypatch.setattr(scripts_pkg, "scrape_gametora_effects", fake, raising=False)

    def test_update_database_success_envelope_with_fake_scraper(self, tmp_path, monkeypatch):
        self._install_fake_scraper(
            monkeypatch, lambda base_dir: {"events": 3, "multi": 2}
        )
        _, client = make_client(tmp_path)
        resp = client.post("/api/events/catalog/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["events"] == 3
        assert body["multi"] == 2
        # tmp runtime has no event logs -> rebuilt catalog is empty.
        assert body["count"] == 0

    def test_update_database_scraper_failure_returns_error_envelope(self, tmp_path, monkeypatch):
        def _boom(base_dir):
            raise RuntimeError("scrape boom")

        self._install_fake_scraper(monkeypatch, _boom)
        _, client = make_client(tmp_path)
        resp = client.post("/api/events/catalog/refresh")
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "detail": "scrape boom"}


class TestEventsPrefs:
    def test_get_empty_then_round_trip_through_post(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/events/prefs")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "prefs": {}}

        resp = client.post("/api/events/prefs", json={"prefs": {"12345": 1}})
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

        resp = client.get("/api/events/prefs")
        assert resp.json() == {"success": True, "prefs": {"12345": 1}}
