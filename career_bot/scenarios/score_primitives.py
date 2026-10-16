"""Game-domain primitives shared by every scenario's training scorer.

Only the pieces the MANT and Unity Cup scorers **provably agree on** live here:
the support-deck slot set, the bond ("evaluation") thresholds/tiers, the
facility-index space (= the values of `base.TRAINING_COMMANDS`), the chara stat
keys indexed by that space, and the `params_inc_dec_info_array` target types.
Changing a game rule (e.g. the max-bond threshold) is now a one-line change
instead of the same edit in three files.

The scoring **formulas** deliberately do NOT live here -- the two scenarios use
genuinely different models and unifying them would be a behavior change, not a
refactor. Each divergence is named in a comment at its site:
  * MANT  -- career_bot/scenarios/scoring.py
  * Unity -- career_bot/scenarios/unity_cup/{scoring,strategy}.py

This module imports nothing (not even from `career_bot`) so any scenario module
can use it without import-cycle risk.
"""

# --- support deck ---------------------------------------------------------
# Partner ids 1..6 are the six support-card slots; anything else on a training
# is an NPC / team member and never triggers friendship (rainbow) training.
DECK_PARTNERS = {1, 2, 3, 4, 5, 6}

# --- bond ("evaluation") thresholds --------------------------------------
# 80 = max bond: the support delivers a rainbow and can gain no more bond.
# 60 = the game's "high bond" step where training efficiency picks up.
MAX_BOND = 80
HIGH_BOND = 60

BOND_TIER_LOW = 0
BOND_TIER_HIGH = 1
BOND_TIER_MAX = 2


def bond_tier(bond):
    """Classify a bond value into LOW (<60) / HIGH (60..79) / MAX (>=80).

    Both scorers split partners on exactly these two thresholds; what they then
    DO with each tier is scenario-specific (MANT interpolates a preset weight,
    Unity adds a flat per-tier score).
    """
    if bond >= MAX_BOND:
        return BOND_TIER_MAX
    if bond >= HIGH_BOND:
        return BOND_TIER_HIGH
    return BOND_TIER_LOW


def is_max_bond(bond):
    """True when this support is maxed (no bond left to build; rainbows now)."""
    return bond >= MAX_BOND


# --- facility index space -------------------------------------------------
# `base.TRAINING_COMMANDS` maps every training command_id (both the 10x and the
# 60x family) onto these indices; both scorers key their per-facility tables on
# them.
SPEED_FACILITY_IDX = 0
STAMINA_FACILITY_IDX = 1
POWER_FACILITY_IDX = 2
GUTS_FACILITY_IDX = 3
WIT_FACILITY_IDX = 4

# --- chara stat keys, indexed by facility idx ----------------------------
STAT_KEYS = ("speed", "stamina", "power", "guts", "wiz")
SKILL_POINT_KEY = "skill_point"
# Skill points sit one slot past the five stats in `base.STAT_TARGETS`.
SKILL_POINT_STAT_IDX = len(STAT_KEYS)

# --- params_inc_dec_info_array target types (game wire) -------------------
# 1..5 = the five stats, 30 = skill points, 10 = energy/vital.
STAT_PARAM_TARGET_TYPES = (1, 2, 3, 4, 5)
SKILL_POINT_PARAM_TARGET_TYPE = 30
ENERGY_PARAM_TARGET_TYPE = 10
