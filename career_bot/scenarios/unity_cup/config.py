from career_bot.bot_config import UNITY_CONFIG_KEY
from career_bot.game_calendar import SUMMER_CAMP_TURNS as GAME_SUMMER_CAMP_TURNS
from career_bot.scenarios.score_primitives import (
    GUTS_FACILITY_IDX,
    POWER_FACILITY_IDX,
    SPEED_FACILITY_IDX,
    STAMINA_FACILITY_IDX,
    STAT_KEYS,
    WIT_FACILITY_IDX,
)


UNITY_CUP_SCENARIO_ID = 2
UNITY_TEAM_RACE_TURNS = {24, 36, 48, 60, 72}
UNITY_SPEED_WIT_COMMANDS = {101, 601, 106, 605}
# Server proper_* grades are ordinal G=1 through S=8; B is the default gate.
UNITY_MAIDEN_RECOVERY_MIN_APTITUDE = 6
# The facility index space and the stat keys are game-wide, not Unity-specific
# (career_bot/scenarios/score_primitives.py); the UNITY_* names stay as the
# aliases this package's `import *` facade already exports.
UNITY_POWER_FACILITY_IDX = POWER_FACILITY_IDX
UNITY_GUTS_FACILITY_IDX = GUTS_FACILITY_IDX
UNITY_WIT_FACILITY_IDX = WIT_FACILITY_IDX
UNITY_WIT_COMMANDS = {106, 605}
UNITY_MIN_TRAIN_SCORE = 1.0
UNITY_WIT_BASE_SCORE = 1.2
UNITY_STAT_KEYS = STAT_KEYS
UNITY_SPEED_FACILITY_IDX = SPEED_FACILITY_IDX
UNITY_STAMINA_FACILITY_IDX = STAMINA_FACILITY_IDX
UNITY_FAILURE_SCORE_PENALTY = 50.0
UNITY_SPEED_BLUE_PURPLE_SOUL_BONUS = 0.1
UNITY_STAMINA_BLUE_PURPLE_SOUL_BONUS = 0.0
UNITY_STAMINA_BLUE_PURPLE_SOUL_FALLOFF = 0.2
UNITY_POWER_BLUE_PURPLE_SOUL_BONUS = 0.25
UNITY_GUTS_BLUE_PURPLE_SOUL_BONUS = 0.0
UNITY_WIT_BLUE_PURPLE_SOUL_BONUS = 0.0
UNITY_SPEED_BLUE_PURPLE_SOUL_STACK_BONUS_STEP = 0.1
UNITY_STAMINA_BLUE_PURPLE_SOUL_STACK_BONUS_STEP = 0.0
UNITY_POWER_BLUE_PURPLE_SOUL_STACK_BONUS_STEP = 0.1
UNITY_GUTS_BLUE_PURPLE_SOUL_STACK_BONUS_STEP = 0.1
UNITY_WIT_BLUE_PURPLE_SOUL_STACK_BONUS_STEP = 0.0
# Legacy constant kept for external/private-test compatibility. Runtime scoring
# now reads per-facility stack-step config keys.
UNITY_SPEED_POWER_GUTS_STACK_BONUS_STEP = UNITY_SPEED_BLUE_PURPLE_SOUL_STACK_BONUS_STEP
UNITY_WIT_FULL_ENERGY_PENALTY_EARLY = {98: 0.3, 99: 0.4, 100: 0.5}
UNITY_WIT_FULL_ENERGY_PENALTY_LATE = {98: 0.35, 99: 0.5, 100: 0.65}
UNITY_LATE_LOW_ENERGY_WIT_SCORE_MIN = 6.0
UNITY_SAFE_WIT_SCORE_EARLY = 2.2
UNITY_SAFE_WIT_SCORE_LATE = 3.7
UNITY_NORMAL_CAP_RULE = (1200, 1.5, 1250, 2.0)
UNITY_WIT_CAP_RULE = (1200, 1.25, 1280, 2.0)
UNITY_BAD_STATUS_IDS = {1, 2, 3, 4, 5, 6}
UNITY_MEDIC_DEFER_RANGES = ((22, 29), (51, 59))
# Default only -- a preset may override it (strategy.py reads it through
# _unity_sequence(config, "summer_bad_status_turns", ...)).
UNITY_SUMMER_BAD_STATUS_TURNS = set(GAME_SUMMER_CAMP_TURNS)
UNITY_FINAL_TRAIN_TURNS = {73, 75, 77}
UNITY_WIT_SUPPORT_TYPES = {"wit", "wisdom"}
UNITY_FACILITY_SUPPORT_TYPES = {
    0: {"speed"},
    1: {"stamina"},
    2: {"power"},
    3: {"guts"},
    4: UNITY_WIT_SUPPORT_TYPES,
}
UNITY_FACILITY_SHORT_LABELS = {
    0: "Spd",
    1: "Sta",
    2: "Power",
    3: "Guts",
    4: "Wit",
}


def _unity_config(preset):
    cfg = (preset or {}).get(UNITY_CONFIG_KEY) if isinstance(preset, dict) else None
    return cfg if isinstance(cfg, dict) else {}


def _unity_num(config, key, default):
    value = (config or {}).get(key, default) if isinstance(config, dict) else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _unity_int(config, key, default):
    value = (config or {}).get(key, default) if isinstance(config, dict) else default
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _unity_sequence(config, key, default):
    value = (config or {}).get(key, default) if isinstance(config, dict) else default
    return value if isinstance(value, (list, tuple, set)) else default


def _unity_cap_rule(config, key, default):
    values = list(_unity_sequence(config, key, default))
    if len(values) < 4:
        values = list(default)
    try:
        return float(values[0]), float(values[1]), float(values[2]), float(values[3])
    except (TypeError, ValueError):
        return default


def _unity_penalty_table(config, key, default):
    value = (config or {}).get(key, default) if isinstance(config, dict) else default
    if not isinstance(value, dict):
        value = default
    result = {}
    for percent, penalty in value.items():
        try:
            result[int(percent)] = float(penalty)
        except (TypeError, ValueError):
            continue
    return result
