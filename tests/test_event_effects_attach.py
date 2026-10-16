"""Tests for event_catalog.attach_effects — surfaces scraped choice effects and
the bot's recommended pick onto catalog rows for the UI."""
import json

from career_bot.events import catalog as event_catalog


def _write_scraped(tmp_path, payload):
    # attach_effects reads the scraped DB from data/json/ (commit e6c1293).
    data = tmp_path / "data" / "json"
    data.mkdir(parents=True, exist_ok=True)
    (data / "event_effects_scraped.json").write_text(json.dumps(payload), encoding="utf-8")


def test_attach_effects_adds_choice_effects_and_recommended(tmp_path):
    _write_scraped(tmp_path, {
        "801001001": {
            "event_name": "Hope She'll Like It...",
            "choices": {
                "1": {"label": "A", "effect": "Bond +5, Power +20"},
                "2": {"label": "B", "effect": "Skill hint +1, Power +20"},
            },
        }
    })
    catalog = {"801001001": {"story_id": "801001001", "n_choices": 2}}
    out = event_catalog.attach_effects(catalog, tmp_path)
    entry = out["801001001"]
    assert entry["choice_effects"] == [
        {"select_index": 1, "label": "A", "effect": "Bond +5, Power +20"},
        {"select_index": 2, "label": "B", "effect": "Skill hint +1, Power +20"},
    ]
    # hint(25)+power20 = 45 beats bond(20)+power20 = 40 -> 2nd choice = position 1
    assert entry["recommended_choice"] == 1


def test_attach_effects_noop_when_event_not_in_db(tmp_path):
    _write_scraped(tmp_path, {"999": {"choices": {"1": {"effect": "Power +5"}}}})
    catalog = {"123": {"story_id": "123", "n_choices": 2}}
    out = event_catalog.attach_effects(catalog, tmp_path)
    assert "choice_effects" not in out["123"]
    assert "recommended_choice" not in out["123"]


def test_attach_effects_safe_when_no_scraped_file(tmp_path):
    catalog = {"1": {"story_id": "1"}}
    out = event_catalog.attach_effects(catalog, tmp_path)
    assert out["1"] == {"story_id": "1"}
