"""FastAPI TestClient characterization -- /api/debug + static/SPA (Phase 0).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
debug inspection routes and of the static-file / SPA-fallback / 404 surface, so
the strangle-the-monolith refactor can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline (and the frontend is deliberately NOT built here,
    which is exactly what the fallback assertions pin).
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
"""

import json

from urllib.parse import quote

from tests._helpers import PROJECT_ROOT, make_client


class TestDebugRoutes:
    def test_start_state_defaults_empty(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/debug/start-state", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

    def test_raw_load_no_cache(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/debug/raw-load", headers={"X-Account": "tester"})
        assert resp.status_code == 200
        assert resp.json() == {
            "success": False,
            "detail": "No cached load/index response",
            "endpoint": "load/index",
        }


class TestStaticAndSpaRoutes:
    def test_root_without_built_frontend(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Dashboard not built" in resp.text

    def test_spa_fallback_404s_without_built_frontend(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/some/client/side/route")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}

    def test_unmatched_api_path_is_json_404(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/does-not-exist")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}

    def test_image_not_found(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/images/999999999")
        assert resp.status_code == 404

    def test_sweep_and_broom_png_not_found(self, tmp_path):
        _, client = make_client(tmp_path)
        assert client.get("/sweep.png").status_code == 404
        assert client.get("/broom.png").status_code == 404

    def test_assets_data_not_found(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/assets/data/does_not_exist.json")
        assert resp.status_code == 404

    def test_races_image_not_found(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/races/does_not_exist.png")
        assert resp.status_code == 404


class TestAssetRoutesServeRealFiles:
    """Happy path for the four hand-written asset routes, against the REAL repo tree.

    The 404 cases above all run with a tmp base_dir, so they pass no matter what
    directory name the controllers point at -- a typo'd or renamed asset dir would
    still 404 and still look "correct". These tests pin the other half: the routes
    must actually resolve to the committed ``assets/`` store and serve its bytes.

    The app is still built with a tmp base_dir (never ``create_app(PROJECT_ROOT)``,
    which would fire the production-only startup side effects -- network master.mdb
    refresh + data regeneration); only ``ctx.base_dir`` is repointed at the repo
    root afterwards, which is the single input these four routes read.
    """

    def _real_root_client(self, tmp_path):
        app, client = make_client(tmp_path)
        app.state.ctx.base_dir = PROJECT_ROOT
        return client

    def test_sweep_png_served_from_assets_dir(self, tmp_path):
        resp = self._real_root_client(tmp_path).get("/sweep.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 1024
        assert resp.content.startswith(b"\x89PNG")

    def test_broom_png_served_from_assets_dir(self, tmp_path):
        resp = self._real_root_client(tmp_path).get("/broom.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 1024
        assert resp.content.startswith(b"\x89PNG")

    def test_asset_data_serves_generated_race_json(self, tmp_path):
        resp = self._real_root_client(tmp_path).get("/assets/data/uma_race_data.json")
        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert isinstance(body["races"], list)
        assert body["races"]

    def test_race_image_served_from_assets_races_dir(self, tmp_path):
        # Picked off disk rather than hardcoded: several race names carry spaces
        # and a U+2019 apostrophe, so the name is URL-encoded on the way out.
        names = sorted(path.name for path in (PROJECT_ROOT / "assets" / "races").glob("*.png"))
        assert names, "no race images on disk -- assets/races/ is missing or empty"

        resp = self._real_root_client(tmp_path).get(f"/races/{quote(names[0])}")

        assert resp.status_code == 200
        assert resp.content.startswith(b"\x89PNG")
