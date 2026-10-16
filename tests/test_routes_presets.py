"""FastAPI TestClient characterization -- /api/presets + /api/skills (Phase 0).

Carved verbatim out of ``tests/test_api_routes.py`` by the §13.1/A13 by-owner
split; one file per router domain. Pins the CURRENT observable behaviour of the
preset stores (skill presets, race presets -- deliberately divergent on the
auto-create-on-save-races path) and the skills listing, so the strangle-the-
monolith refactor can be verified byte-identical.

Ground rules kept from the original suite:
  * Every app is built with `make_client(tmp_path)` -> `create_app(tmp_path)` --
    module-level startup skips master.mdb generation when the DB is absent, so
    this boots fully offline; preset files land under tmp_path, never the repo.
  * Assertions target status code + response shape/keys/types, NOT volatile
    exact values (timestamps, machine-specific paths, live master.mdb content).
"""

from tests._helpers import make_client


class TestPresets:
    def test_empty_list(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "presets": []}

    def test_save_read_save_races_delete_round_trip(self, tmp_path):
        _, client = make_client(tmp_path)

        resp = client.post("/api/presets", json={"preset": {"name": "My Preset"}})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # slugify() only strips disallowed chars/collapses whitespace -- it does NOT
        # lowercase, so the name is preserved as typed; only the filename is derived
        # from it (career_bot/presets.py:slugify + PresetStore.write).
        assert body["preset"]["name"] == "My Preset"
        assert (tmp_path / "uma_runtime" / "presets" / "My Preset.json").exists()

        resp = client.get("/api/presets")
        names = {p["name"] for p in resp.json()["presets"]}
        assert "My Preset" in names

        resp = client.put(
            "/api/presets/My Preset/races",
            json={"races": [101, 102]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        resp = client.get("/api/presets")
        saved = next(p for p in resp.json()["presets"] if p["name"] == "My Preset")
        assert saved["extra_race_list"] == [101, 102]

        resp = client.put(
            "/api/presets/does-not-exist/races",
            json={"races": [1]},
        )
        assert resp.json()["success"] is False
        assert "detail" in resp.json()

        resp = client.request("DELETE", "/api/presets/My Preset")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        assert not (tmp_path / "uma_runtime" / "presets" / "My Preset.json").exists()

        resp = client.request("DELETE", "/api/presets/My Preset")
        assert resp.json() == {"success": False}


class TestRacePresets:
    def test_empty_list(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/presets?kind=race")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "presets": []}

    def test_save_read_save_races_delete_round_trip(self, tmp_path):
        _, client = make_client(tmp_path)

        resp = client.post(
            "/api/presets?kind=race",
            json={"preset": {"name": "My Races"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # slugify() only strips disallowed chars/collapses whitespace -- it does NOT
        # lowercase, so the name is preserved as typed (see TestPresets above).
        assert body["preset"]["name"] == "My Races"
        assert (tmp_path / "uma_runtime" / "race_presets" / "My Races.json").exists()

        resp = client.put(
            "/api/presets/My Races/races?kind=race",
            json={"races": [201]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}

        resp = client.get("/api/presets?kind=race")
        saved = next(p for p in resp.json()["presets"] if p["name"] == "My Races")
        assert saved["extra_race_list"] == [201]

        resp = client.request(
            "DELETE",
            "/api/presets/My Races?kind=race",
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        assert not (tmp_path / "uma_runtime" / "race_presets" / "My Races.json").exists()

    def test_save_races_auto_creates_missing_preset(self, tmp_path):
        # Race-presets AUTO-CREATE a missing preset (legacy behaviour, deliberately
        # DIFFERENT from the presets domain, which returns an error for a missing name).
        _, client = make_client(tmp_path)
        resp = client.put(
            "/api/presets/Brand New/races?kind=race",
            json={"races": [301, 302]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        resp = client.get("/api/presets?kind=race")
        created = next(p for p in resp.json()["presets"] if p["name"] == "Brand New")
        assert created["extra_race_list"] == [301, 302]

    def test_kind_selects_an_isolated_store(self, tmp_path):
        _, client = make_client(tmp_path)
        client.post("/api/presets", json={"preset": {"name": "Skill Only"}})
        client.post(
            "/api/presets?kind=race",
            json={"preset": {"name": "Race Only"}},
        )

        skill_names = {
            preset["name"] for preset in client.get("/api/presets").json()["presets"]
        }
        race_names = {
            preset["name"]
            for preset in client.get("/api/presets?kind=race").json()["presets"]
        }
        assert skill_names == {"Skill Only"}
        assert race_names == {"Race Only"}


class TestSkills:
    def test_no_skill_data_file(self, tmp_path):
        _, client = make_client(tmp_path)
        resp = client.get("/api/skills")
        # skills is an array (each entry carries its own id); empty ctx -> []
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "skills": []}
