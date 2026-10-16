"""Parity + invariant test for the shared training-score primitives (REFACTOR_PLAN §10.2/5).

`career_bot/scenarios/score_primitives.py` is the single source of truth for the
game-domain primitives BOTH training scorers agree on (deck slots, bond
thresholds/tiers, facility indices, stat keys, param target types). This test
asserts the structural relations that must hold between each scorer and those
primitives -- not a frozen dump of every score -- plus a small frozen sample so
an accidental rescale is caught immediately.

The DELIBERATE divergences are pinned here too (rainbow eligibility, NPC bond,
the failure model, the stat-cap model): if someone "unifies" them, these tests
fail and point at the decision instead of silently changing live training picks.
"""

import ast

import career_bot.scenarios.base as base
import career_bot.scenarios.score_primitives as primitives
import career_bot.scenarios.unity_cup.config as unity_config
from career_bot.scenarios.base import STAT_TARGETS, TRAINING_COMMANDS, command_stat_gain
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.score_primitives import (
    BOND_TIER_HIGH,
    BOND_TIER_LOW,
    BOND_TIER_MAX,
    DECK_PARTNERS,
    ENERGY_PARAM_TARGET_TYPE,
    HIGH_BOND,
    MAX_BOND,
    SKILL_POINT_PARAM_TARGET_TYPE,
    SKILL_POINT_STAT_IDX,
    STAT_KEYS,
    STAT_PARAM_TARGET_TYPES,
    WIT_FACILITY_IDX,
    bond_tier,
    is_max_bond,
)
from career_bot.scenarios.unity_cup import UnityCupStrategy
from career_bot.scenarios.unity_cup.scoring import _raw_training_stat_gain, _unity_current_stat

SPEED_SUPPORT_ID = 10002   # Silence Suzuka (Speed)
WIT_SUPPORT_ID = 10013     # (Wisdom)
NPC_PARTNER_ID = 1010      # a team member, never a deck slot


def _command(command_id=101, partners=(), failure_rate=0, params=None):
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": failure_rate,
        "training_partner_array": list(partners),
        "params_inc_dec_info_array": list(params if params is not None else [{"target_type": 1, "value": 12}]),
    }


def _chara(turn=30, vital=70, bonds=None, supports=None, **stats):
    chara = {
        "turn": turn,
        "vital": vital,
        "playing_state": 1,
        "motivation": 5,
        "evaluation_info_array": [{"target_id": pid, "evaluation": value} for pid, value in sorted((bonds or {}).items())],
        "support_card_array": [{"position": slot, "support_card_id": sid} for slot, sid in sorted((supports or {}).items())],
    }
    for key in STAT_KEYS:
        chara[key] = stats.get(key, 500)
    return chara


def _mant_score(command, chara, preset=None):
    return MantStrategy()._score_command(command, {}, chara, preset if preset is not None else {})


def _unity_score(command, chara, preset=None, team_command=None):
    data = {
        "chara_info": chara,
        "home_info": {"command_info_array": [command]},
        "team_data_set": {"command_info_array": [team_command] if team_command else []},
    }
    return UnityCupStrategy()._unity_score_training(command, data, chara, preset if preset is not None else {})


# --- the primitives themselves -------------------------------------------

def test_primitives_module_is_import_free_and_authoritative():
    # Zero imports at all = no cycle risk for any scenario package that wants it.
    with open(primitives.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    assert [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))] == []

    # base re-exports the deck set rather than owning a second copy.
    assert base.DECK_PARTNERS is DECK_PARTNERS
    assert DECK_PARTNERS == {1, 2, 3, 4, 5, 6}
    # Unity's UNITY_* names are aliases of the shared ones, not parallel values.
    assert unity_config.UNITY_STAT_KEYS is STAT_KEYS
    assert unity_config.UNITY_SPEED_FACILITY_IDX is primitives.SPEED_FACILITY_IDX
    assert unity_config.UNITY_STAMINA_FACILITY_IDX is primitives.STAMINA_FACILITY_IDX
    assert unity_config.UNITY_POWER_FACILITY_IDX is primitives.POWER_FACILITY_IDX
    assert unity_config.UNITY_GUTS_FACILITY_IDX is primitives.GUTS_FACILITY_IDX
    assert unity_config.UNITY_WIT_FACILITY_IDX is WIT_FACILITY_IDX
    # base's wire-level map is keyed off the same primitives.
    assert STAT_TARGETS[SKILL_POINT_PARAM_TARGET_TYPE] == SKILL_POINT_STAT_IDX == len(STAT_KEYS)
    assert sorted(STAT_TARGETS[t] for t in STAT_PARAM_TARGET_TYPES) == list(range(len(STAT_KEYS)))


def test_bond_tier_and_is_max_bond_match_the_raw_thresholds():
    assert (MAX_BOND, HIGH_BOND) == (80, 60)
    for bond in range(-10, 121):
        expected = BOND_TIER_MAX if bond >= MAX_BOND else BOND_TIER_HIGH if bond >= HIGH_BOND else BOND_TIER_LOW
        assert bond_tier(bond) == expected, bond
        assert is_max_bond(bond) is (bond >= MAX_BOND), bond
    assert bond_tier(79.999) == BOND_TIER_HIGH and bond_tier(80.0) == BOND_TIER_MAX


def test_facility_index_space_is_shared_by_both_scorers():
    # Both scorers key their per-facility tables on base.TRAINING_COMMANDS values.
    assert set(TRAINING_COMMANDS.values()) == {
        primitives.SPEED_FACILITY_IDX,
        primitives.STAMINA_FACILITY_IDX,
        primitives.POWER_FACILITY_IDX,
        primitives.GUTS_FACILITY_IDX,
        WIT_FACILITY_IDX,
    }
    chara = _chara()
    for command_id, facility_idx in sorted(TRAINING_COMMANDS.items()):
        scored = _unity_score(_command(command_id), chara)
        assert scored.facility_idx == facility_idx, command_id
        assert scored.is_wit is (facility_idx == WIT_FACILITY_IDX), command_id


def test_both_scorers_read_the_same_chara_stat_key_per_facility():
    chara = _chara(speed=101, stamina=202, power=303, guts=404, wiz=505)
    strategy = MantStrategy()
    for idx, key in enumerate(STAT_KEYS):
        assert strategy._current_stat(chara, idx) == float(chara[key]), key
        assert _unity_current_stat(chara, idx) == chara[key], key
    assert strategy._current_stat(chara, SKILL_POINT_STAT_IDX) == 0.0
    assert _unity_current_stat(chara, SKILL_POINT_STAT_IDX) == 0


def test_both_stat_gain_helpers_count_exactly_the_shared_param_target_types():
    for target_type in STAT_PARAM_TARGET_TYPES:
        command = _command(params=[{"target_type": target_type, "value": 7}])
        assert command_stat_gain(command) == 7, target_type
        assert _raw_training_stat_gain(command) == 7, target_type
    for ignored in (SKILL_POINT_PARAM_TARGET_TYPE, ENERGY_PARAM_TARGET_TYPE, 99):
        command = _command(params=[{"target_type": ignored, "value": 7}])
        assert command_stat_gain(command) == 0, ignored
        assert _raw_training_stat_gain(command) == 0, ignored


# --- both scorers break on the SAME bond thresholds ----------------------

def test_both_scorers_classify_bond_on_exactly_the_shared_thresholds():
    strategy = MantStrategy()
    command = _command(101, partners=[1])
    supports = {1: SPEED_SUPPORT_ID}
    for bond in (0, HIGH_BOND - 1, HIGH_BOND, MAX_BOND - 1, MAX_BOND, 100):
        chara = _chara(bonds={1: bond}, supports=supports)
        maxed = bond >= MAX_BOND
        # shared classification helpers (base, inherited by every scenario)
        assert strategy._bondable_count(command, chara) == (0 if maxed else 1), bond
        assert strategy._rainbow_count(command, chara) == (1 if maxed else 0), bond
        # Unity's own counters land on the same split
        scored = _unity_score(command, chara)
        assert scored.bondable_count == (0 if maxed else 1), bond
        assert scored.rainbow_count == (1 if maxed else 0), bond

    def mant(bond):
        return _mant_score(command, _chara(bonds={1: bond}, supports=supports))

    def unity(bond):
        return _unity_score(command, _chara(bonds={1: bond}, supports=supports)).score

    # Unity's per-tier score is flat, so the tiers are visible exactly:
    assert unity(0) == unity(HIGH_BOND - 1) != unity(HIGH_BOND)
    assert unity(HIGH_BOND) == unity(MAX_BOND - 1) != unity(MAX_BOND)
    # MANT interpolates inside a tier, but both shared thresholds are still live:
    assert mant(HIGH_BOND - 1) != mant(HIGH_BOND)
    assert mant(MAX_BOND - 1) != mant(MAX_BOND)


# --- deliberate divergences (pinned so a "unification" is a conscious act) ---

def test_divergence_only_unity_requires_a_matching_support_type_to_rainbow():
    command = _command(102, partners=[1])  # Power facility
    chara = _chara(bonds={1: MAX_BOND}, supports={1: SPEED_SUPPORT_ID})  # off-type support

    # MANT: any maxed deck partner is a rainbow, whatever the card type.
    assert MantStrategy()._rainbow_count(command, chara) == 1
    # Unity: off-type maxed support gets the small off-type score, no rainbow.
    scored = _unity_score(command, chara)
    assert scored.rainbow_count == 0
    assert scored.score == 0.25
    matching = _unity_score(command, _chara(bonds={1: MAX_BOND}, supports={1: 10005}))  # Power card
    assert matching.rainbow_count == 1


def test_divergence_npc_partners_carry_bond_value_only_in_mant():
    chara = _chara(bonds={NPC_PARTNER_ID: 40})
    alone = _command(101, partners=[])
    with_npc = _command(101, partners=[NPC_PARTNER_ID])

    assert _mant_score(with_npc, chara) > _mant_score(alone, chara)
    assert _unity_score(with_npc, chara).score == _unity_score(alone, chara).score


def test_divergence_failure_is_multiplicative_in_mant_and_subtractive_in_unity():
    chara = _chara(bonds={1: 40}, supports={1: SPEED_SUPPORT_ID})
    partners = [1]
    clean_mant = _mant_score(_command(101, partners, failure_rate=0), chara)
    clean_unity = _unity_score(_command(101, partners, failure_rate=0), chara).score
    for failure_rate in (5, 10, 20):
        mant = _mant_score(_command(101, partners, failure_rate=failure_rate), chara)
        unity = _unity_score(_command(101, partners, failure_rate=failure_rate), chara)
        # MANT: raw percent scale, multiplicative discount (default denominator 25).
        assert mant == clean_mant * (1.0 - failure_rate / 25.0), failure_rate
        # Unity: normalised to 0..1, flat subtraction (default penalty 50).
        assert unity.failure == failure_rate / 100.0, failure_rate
        assert unity.score == clean_unity - unity.failure * 50.0, failure_rate


def test_divergence_stat_cap_is_a_preset_ratio_in_mant_and_a_flat_divisor_in_unity():
    command = _command(101, partners=[1])
    supports = {1: SPEED_SUPPORT_ID}
    # Unity: one flat soft-cap divisor at 1200, no preset target involved.
    under = _unity_score(command, _chara(bonds={1: MAX_BOND}, supports=supports, speed=1199)).score
    over = _unity_score(command, _chara(bonds={1: MAX_BOND}, supports=supports, speed=1200)).score
    assert over == under / 1.5
    # MANT: no cap effect at all without a preset target; the preset's
    # expect_attribute is what moves the boundary.
    chara_low = _chara(bonds={1: 40}, supports=supports, speed=100)
    chara_high = _chara(bonds={1: 40}, supports=supports, speed=1199)
    assert _mant_score(command, chara_low, {}) == _mant_score(command, chara_high, {})
    preset = {"expect_attribute": [1000, 9999, 9999, 9999, 9999]}
    assert _mant_score(command, chara_low, preset) != _mant_score(command, chara_high, preset)


# --- frozen sample (guards against a silent rescale) ---------------------

def test_frozen_mant_score_sample():
    # Captured from the pre-refactor scorer (verified equal on the HEAD tree); a
    # change here means the MANT training model moved, not that a primitive was
    # renamed. Exercises all three bond tiers + an NPC partner + energy/SP params.
    chara = _chara(turn=30, vital=70, bonds={1: 80, 2: 60, 3: 59, NPC_PARTNER_ID: 40}, supports={1: SPEED_SUPPORT_ID})
    command = _command(101, partners=[1, 2, 3, NPC_PARTNER_ID], failure_rate=10,
                       params=[{"target_type": 1, "value": 12}, {"target_type": 30, "value": 25}, {"target_type": 10, "value": 15}])
    assert _mant_score(command, chara, {}) == 0.300746875
    assert _mant_score(_command(106, partners=[1]), _chara(turn=70, vital=40, bonds={1: 79}), {}) == 0.14058670438878676
    assert _mant_score(_command(101), _chara(turn=10, vital=100, speed=100), {}) == 0.12


def test_frozen_unity_score_sample():
    # Same inputs through the Unity scorer -- deliberately a different number.
    chara = _chara(turn=30, vital=70, bonds={1: 80, 2: 60, 3: 59, NPC_PARTNER_ID: 40}, supports={1: SPEED_SUPPORT_ID})
    command = _command(101, partners=[1, 2, 3, NPC_PARTNER_ID], failure_rate=10)
    assert _unity_score(command, chara).score == -1.25
    wit = _unity_score(_command(106, partners=[1]), _chara(turn=70, vital=40, bonds={1: 80}, supports={1: WIT_SUPPORT_ID}))
    assert wit.score == 3.2
    assert wit.has_wit_rainbow is True
