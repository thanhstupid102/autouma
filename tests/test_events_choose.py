"""Integration tests for EventManager.choose with effect-based scoring.

Verifies the new scraped-effect scoring picks smart choices while preserving
every existing behavior (prefs override, curated good/bad, hardcoded special,
blind fallback).
"""
import json

from career_bot.events import EventManager


def _make_base(tmp_path, *, scraped=None, outcomes=None, prefs=None):
    # EventManager reads all event data files from data/json/ (commit e6c1293).
    data = tmp_path / "data" / "json"
    data.mkdir(parents=True, exist_ok=True)
    if scraped is not None:
        (data / "event_effects_scraped.json").write_text(
            json.dumps(scraped), encoding="utf-8")
    if outcomes is not None:
        (data / "event_outcomes.json").write_text(
            json.dumps(outcomes), encoding="utf-8")
    if prefs is not None:
        (data / "event_prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8")
    return tmp_path


def _event(story_id, n_choices):
    return {
        "story_id": story_id,
        "event_contents_info": {
            "choice_array": [{"select_index": i + 1} for i in range(n_choices)]
        },
    }


def test_choose_uses_scraped_effects_when_no_curated_data(tmp_path):
    # Best choice is index 0 so this discriminates from the old blind "pick 1".
    scraped = {
        "801001002": {
            "choices": {
                "1": {"effect": "Skill hint +1, Bond +5, Power +20"},
                "2": {"effect": "Motivation -1, Power +5"},
            }
        }
    }
    base = _make_base(tmp_path, scraped=scraped)
    em = EventManager(base, base / "uma_runtime")
    # Default stat priority [0,1,2,3,4] (speed,stamina,power,guts,wiz) adds a
    # rank bonus to positive stats via STAT_PRIORITY_BONUS_BY_RANK; power is
    # rank 2 -> +30.
    # choice 1 = hint 25 + bond 20 + power (20+30) = 95.0
    # choice 2 = motivation -150 + power (5+30) = -115.0 -> position 0
    assert em.choose(_event("801001002", 2)) == 0


def test_choose_three_choices_picks_best_index(tmp_path):
    scraped = {
        "801001003": {
            "choices": {
                "1": {"effect": "Power +10"},
                "2": {"effect": "Power +15"},
                "3": {"effect": "Skill hint +1, Skill points +30, Power +20"},
            }
        }
    }
    base = _make_base(tmp_path, scraped=scraped)
    em = EventManager(base, base / "uma_runtime")
    # Default stat priority makes power rank 2 -> +30 bonus (see above).
    # choice 1 = power (10+30) = 40.0 ; choice 2 = power (15+30) = 45.0
    # choice 3 = hint 25 + skill_point 30 + power (20+30) = 105.0 (best) -> position 2
    assert em.choose(_event("801001003", 3)) == 2


def test_choose_ignores_loose_suffix_curated_collision(tmp_path):
    # A curated entry for an UNRELATED event that merely shares trailing digits
    # must not hijack scoring for a different story_id (Icarus-style tightening).
    outcomes = {"830028002": {"outcomes": {"1": "good", "2": "bad"}}}
    scraped = {"801001002": {"choices": {
        # Default stat priority makes power rank 2 -> +30 bonus (see above).
        "1": {"effect": "Skill points +30, Motivation -1, Power +20"},        # skill_point 30 - mood 150 + power (20+30) = -70.0
        "2": {"effect": "Skill hint +1, Bond +5, Skill hint +1, Power +20"},  # hints 2*25=50 + bond 20 + power (20+30) = 120.0
    }}}
    base = _make_base(tmp_path, outcomes=outcomes, scraped=scraped)
    em = EventManager(base, base / "uma_runtime")
    assert em.choose(_event("801001002", 2)) == 1


def test_choose_falls_back_to_second_when_no_data(tmp_path):
    base = _make_base(tmp_path)  # no data files at all
    em = EventManager(base, base / "uma_runtime")
    assert em.choose(_event("999999999", 2)) == 1
    assert em.choose(_event("999999999", 1)) == 0


def test_choose_respects_curated_good_outcome(tmp_path):
    outcomes = {"500001": {"outcomes": {"1": "bad", "2": "good"}}}
    base = _make_base(tmp_path, outcomes=outcomes)
    em = EventManager(base, base / "uma_runtime")
    # select_index 2 is "good" -> position 1
    assert em.choose(_event("500001", 2)) == 1


def test_choose_prefs_override_wins_over_scoring(tmp_path):
    scraped = {"700001": {"choices": {
        "1": {"effect": "Power +50"}, "2": {"effect": "Power +5"}}}}
    base = _make_base(tmp_path, scraped=scraped, prefs={"700001": 1})
    em = EventManager(base, base / "uma_runtime")
    # scoring would pick position 0 (Power +50); pref forces position 1
    assert em.choose(_event("700001", 2)) == 1


def test_choose_hardcoded_special(tmp_path):
    base = _make_base(tmp_path)
    em = EventManager(base, base / "uma_runtime")
    # 0-based POSITION 1 (runner boundary maps it to the original wire value 2).
    assert em.choose(_event("400004002", 4)) == 1


def test_choose_no_choices_returns_zero(tmp_path):
    base = _make_base(tmp_path)
    em = EventManager(base, base / "uma_runtime")
    assert em.choose({"story_id": "1", "event_contents_info": {"choice_array": []}}) == 0


def test_choose_context_priority_changes_pick(tmp_path):
    scraped = {"900001": {"choices": {
        "1": {"effect": "Speed +30"}, "2": {"effect": "Power +30"}}}}
    base = _make_base(tmp_path, scraped=scraped)
    em = EventManager(base, base / "uma_runtime")
    # No context: not a tie. Default stat priority [0,1,2,3,4] ranks speed (idx
    # 0) above power (idx 2), so choice 1 = 30+50 = 80.0 beats
    # choice 2 = 30+30 = 60.0 -> position 0.
    assert em.choose(_event("900001", 2)) == 0
    # Power-priority preset: power choice gets the rank-0 bonus -> position 1.
    preset = {"expect_attribute": [600, 600, 1200, 600, 600]}
    assert em.choose(_event("900001", 2), preset=preset) == 1
