"""Tests for career_bot.events.scoring — pure event-choice scoring.

Ports Icarus' gametora-effect scoring into the bot so the EventManager can pick
the best choice instead of blindly choosing option 1.
"""
from career_bot.events import scoring as es


# --------------------------------------------------------------------------- #
# parse_effect_string
# --------------------------------------------------------------------------- #
def test_parse_single_stat():
    assert es.parse_effect_string("Power +20") == {"power": 20}


def test_parse_multiple_tokens():
    assert es.parse_effect_string("Bond +5, Power +20") == {"bond": 5, "power": 20}


def test_parse_skill_points_and_negative_motivation():
    assert es.parse_effect_string("Skill points +30, Motivation -1, Wisdom +15") == {
        "skill_point": 30,
        "motivation": -1,
        "wiz": 15,
    }


def test_parse_skill_hint_counts():
    # Two "Skill hint +1" tokens accumulate into hints=2.
    assert es.parse_effect_string("Skill hint +1, Bond +5, Skill hint +1, Power +20") == {
        "hints": 2,
        "bond": 5,
        "power": 20,
    }


def test_parse_energy_and_max_energy():
    assert es.parse_effect_string("Energy +20") == {"vital": 20}
    assert es.parse_effect_string("Max Energy +4") == {"max_vital": 4}


def test_parse_all_stats():
    assert es.parse_effect_string("All stats +10") == {
        "speed": 10, "stamina": 10, "power": 10, "guts": 10, "wiz": 10,
    }


def test_parse_status_symbols():
    assert es.parse_effect_string("Get Practice Perfect ○") == {"positive_status": True}
    assert es.parse_effect_string("Get Practice Poor ✕") == {"negative_status": True}


def test_parse_empty_returns_none():
    assert es.parse_effect_string("") is None
    assert es.parse_effect_string(None) is None
    assert es.parse_effect_string("just narrative text") is None


# --------------------------------------------------------------------------- #
# stat_priority_from_targets
# --------------------------------------------------------------------------- #
def test_priority_orders_by_target_desc():
    # expect_attribute = [speed, stamina, power, guts, wiz] target values.
    assert es.stat_priority_from_targets([1200, 600, 1100, 600, 900]) == [0, 2, 4, 1, 3]


def test_priority_empty_falls_back_to_natural_order():
    assert es.stat_priority_from_targets(None) == [0, 1, 2, 3, 4]


# --------------------------------------------------------------------------- #
# score_reward
# --------------------------------------------------------------------------- #
def test_score_bare_stat_no_context():
    # No priority, no chara: a +20 stat is worth its raw value.
    assert es.score_reward({"power": 20}) == 20.0


def test_score_skill_point_is_raw():
    assert es.score_reward({"skill_point": 30}) == 30.0


def test_score_skill_hint_bonus_per_hint():
    assert es.score_reward({"hints": 2}) == es.SKILL_HINT_BONUS * 2


def test_score_bond_gain_is_flat():
    assert es.score_reward({"bond": 5}) == es.BOND_GAIN_BONUS


def test_score_motivation_loss_penalty():
    # Motivation -1 is a heavy penalty (per point).
    assert es.score_reward({"motivation": -1}) == es.MOOD_LOSS_PENALTY


def test_score_positive_status():
    assert es.score_reward({"positive_status": True}) == es.POSITIVE_STATUS_BONUS


def test_score_stat_priority_bonus():
    # power is idx 2; priority [0,2,4,1,3] puts it at rank 1 -> +40 bonus.
    priority = es.stat_priority_from_targets([1200, 600, 1100, 600, 900])
    assert es.score_reward({"power": 20}, stat_priority=priority) == (20 + 40) * 1.0


def test_score_stat_cap_factor_reduces_near_max():
    # A stat already at 1150 (50 below the 1200 cap, 250 window) is worth less.
    full = es.score_reward({"power": 20})
    capped = es.score_reward({"power": 20}, chara={"power": 1150})
    assert capped < full
    assert capped == 20 * max(0.1, (1200 - 1150) / 250)


def test_score_energy_uses_low_hp_multiplier():
    # Unknown hp defaults to 50 -> low-energy multiplier of 2x.
    assert es.score_reward({"vital": 20}) == 40.0


def test_score_energy_zero_when_full():
    assert es.score_reward({"vital": 20}, chara={"vital": 100, "max_vital": 100}) == 0.0


# --------------------------------------------------------------------------- #
# best_choice_index
# --------------------------------------------------------------------------- #
def _row(*effects):
    return {"choices": {str(i + 1): {"effect": e} for i, e in enumerate(effects)}}


def _choices(n):
    return [{"select_index": i + 1} for i in range(n)]


def test_best_choice_picks_higher_score():
    # select_index 2 has an extra skill hint -> higher score -> list index 1.
    row = _row("Power +20", "Skill hint +1, Power +20")
    assert es.best_choice_index(_choices(2), row) == 1


def test_best_choice_tie_prefers_lower_index():
    row = _row("Power +20", "Speed +20")  # both raw 20, no priority
    assert es.best_choice_index(_choices(2), row) == 0


def test_best_choice_none_when_no_effects():
    assert es.best_choice_index(_choices(2), {"choices": {}}) is None
    assert es.best_choice_index(_choices(2), None) is None


# --------------------------------------------------------------------------- #
# recommended_choice_position (0-based POSITION of the bot's pick, for UI display)
# --------------------------------------------------------------------------- #
def test_recommended_choice_position_returns_best_position():
    row = _row("Power +20", "Skill hint +1, Power +20")  # 2nd choice better
    assert es.recommended_choice_position(row) == 1  # position 1, not select_index 2


def test_recommended_choice_position_none_without_effects():
    assert es.recommended_choice_position({"choices": {}}) is None
    assert es.recommended_choice_position(None) is None
