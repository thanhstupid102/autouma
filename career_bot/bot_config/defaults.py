from __future__ import annotations

import copy
from typing import Any

from career_bot.game_calendar import SUMMER_CAMP_TURNS


# Schema version of DEFAULT_BOT_CONFIG. Bump whenever a knob is REMOVED or
# reshaped, and add the matching upgrade step in career_bot/bot_config/migrations.py
# so stored configs written by an older version keep loading.
#   1 -> 2 (§12.6): dropped the never-read MANT knobs `special_training`,
#          `spirit_explosion`, `wit_special_multiplier`, and the unused third
#          column of every `npc_score_value` row.
BOT_CONFIG_VERSION = 2
MANT_SCENARIO_ID = 4
UNITY_CUP_SCENARIO_ID = 2
GRAND_LIVE_SCENARIO_ID = 3
UNITY_CONFIG_KEY = "_bot_config_unity_cup"


SCENARIOS: dict[str, dict[str, Any]] = {
    "4": {
        "scenario_id": MANT_SCENARIO_ID,
        "name": "MANT / Make a New Track",
        "description": "Global training scoring, bond, energy, failure, rescue, and MANT shop-item decision tuning.",
    },
    "2": {
        "scenario_id": UNITY_CUP_SCENARIO_ID,
        "name": "Unity Cup",
        "description": "Global soul, bond, rainbow, cap, failure, Wit, medic, recreation, and late-game scoring tuning.",
    },
    "3": {
        "scenario_id": GRAND_LIVE_SCENARIO_ID,
        "name": "Grand Live",
        "description": "Grand Live Live Tree song/common-square buying, support/Wit/Light Hello training scoring, token scoring, rest, and date tuning.",
    },
}


MANT_DEFAULTS: dict[str, Any] = {
    "buy_clocks_with_carats": True,
    "max_clocks_bought_per_career": 3,
    # Existing hydrate_preset defaults / scoring weights
    "cure_asap_conditions": [
        "Migraine",
        "Night Owl",
        "Skin Outbreak",
        "Slacker",
        "Slow Metabolism",
        "(Practice poor isn't worth a turn to cure)",
    ],
    "expect_attribute": [9999.0, 9999.0, 9999.0, 9999.0, 9999.0],
    "score_value": [
        [0.11, 0.1, 0.006, 0.09],
        [0.11, 0.1, 0.006, 0.09],
        [0.11, 0.1, 0.006, 0.09],
        [0.03, 0.05, 0.006, 0.09],
        [0.0, 0.0, 0.006, 0.0],
    ],
    "base_score": [0.0, 0.0, 0.0, 0.0, 0.0],
    "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
    "extra_weight": [[0.0, 0.0, 0.0, 0.0, 0.0]] * 4,
    # [bond-0 weight, bond-max weight] per turn period; TrainingScoreMixin._npc_score
    # interpolates between the two. A third column existed historically and was
    # never read -- dropped in schema v2.
    "npc_score_value": [
        [0.05, 0.05],
        [0.05, 0.05],
        [0.05, 0.05],
        [0.03, 0.05],
        [0.0, 0.0],
    ],
    "compensate_failure": True,
    "failure_penalty_denominator": 25.0,
    "hint_count_scale": 0.5,
    "score_skill_points": False,
    "skill_point_weight": 1.0,
    "stat_balance": True,
    "stat_balance_threshold": 0.85,
    "stat_balance_boost": 0.6,
    "rainbow_explicit": True,
    "rainbow_useful_ref": 0.12,
    "rainbow_bonus": 0.12,
    "rainbow_stack_bonus": 0.06,
    "late_aggressive_turn": 65,
    "late_stat_cap": 1200.0,
    "late_cap_95_multiplier": 0.35,
    "late_cap_90_multiplier": 0.9,
    "wit_overcap_multiplier": 0.75,
    "wit_overcap_late_multiplier": 0.35,
    "wit_energy_boost": 0.25,
    "wit_energy_target": 85.0,

    # Existing MANT train/rest/recreation/medic decision defaults
    "summer_score_threshold": 0.34,
    "summer_recreate_vital_threshold": 40.0,
    "summer_conserve_energy": 60.0,
    "summer_conserve_turns": [36, 60],
    "high_failure_rest_threshold": 35.0,
    "energy_medic_general": 85.0,
    "medic_tank_turns": 6,
    "medic_good_train_stat": 30.0,
    "medic_good_train_score": 0.55,
    "motivation_threshold_year1": 3.0,
    "motivation_threshold_year2": 4.0,
    "motivation_threshold_year3": 4.0,
    "prioritize_recreation": False,
    "late_allow_recreation": False,
    "mood_target_recreate": False,
    "mood_recreate_max_score": 0.30,
    "pal_thresholds": [],
    "rest_threshold": 48.0,
    "junior_bond_rush": True,

    # Existing rescue defaults
    "rescue_good_training": True,
    "rescue_min_vital": 25.0,
    "rescue_score_threshold": 0.55,
    "rescue_vital_margin": 12.0,
    "failure_hard_cap": 50.0,
    "late_uncovered_failure_rest": 30.0,

    # Existing MANT item/shop policy defaults that affect train decisions
    "buy_notepads": True,
    "manual_purchase_at_end": False,
    "pre_summer_stock": True,
    "deck_match_stat_items": True,
    "deck_match_min_count": 2,
    "mant_config": {
        "tier_count": 8,
        "bbq_unmaxxed_cards": 3,
        "pre_summer_window": [
            23, 24, 25, 26, 27, 28,
            29, 30, 31, 32, 33, 34, 35, 36,
            47, 48, 49, 50, 51, 52,
            53, 54, 55, 56, 57, 58, 59, 60,
        ],
        "mant_coin_cap_t20": 999999.0,
        "mant_coin_cap_t35": 300.0,
        "mant_coin_cap_t45": 260.0,
        "mant_coin_cap_t55": 200.0,
        "mant_coin_cap_t64": 140.0,
        "mant_coin_cap_t72": 80.0,
        "mant_coin_cap_final": 0.0,
        "energy_recovery_threshold": 30.0,
        "rescue_failure": 30.0,
        "rescue_train_stat": 27.0,
        "late_train_stat_target": 20.0,
        "summer_raw_stat_target": 50.0,
        "whistle_score_threshold": 35.0,
        "charm_failure_rate": 30.0,
        "charm_min_stat": 27.0,
        "mega_small_threshold": 11.0,
        "mega_medium_threshold": 21.0,
        "mega_large_threshold": 35.0,
        "mega_late_buy_buffer": 3,
        "pre_summer_tier": 2,
    },
}


UNITY_DEFAULTS: dict[str, Any] = {
    "buy_clocks_with_carats": True,
    "max_clocks_bought_per_career": 3,
    "maiden_recovery_min_aptitude": 6,
    "min_train_score": 1.0,
    "white_soul_score": 0.525,
    "blue_soul_score": 1.0,
    "purple_soul_score": 1.3,
    "wit_base_score": 1.2,
    "failure_score_penalty": 50.0,
    "speed_blue_purple_soul_bonus": 0.1,
    "stamina_blue_purple_soul_bonus": 0.0,
    "stamina_blue_purple_soul_falloff": 0.2,
    "power_blue_purple_soul_bonus": 0.25,
    "guts_blue_purple_soul_bonus": 0.0,
    "wit_blue_purple_soul_bonus": 0.0,
    "speed_blue_purple_soul_stack_bonus_step": 0.1,
    "stamina_blue_purple_soul_stack_bonus_step": 0.0,
    "power_blue_purple_soul_stack_bonus_step": 0.1,
    "guts_blue_purple_soul_stack_bonus_step": 0.1,
    "wit_blue_purple_soul_stack_bonus_step": 0.0,
    "support_bond_low_score": 1.0,
    "support_bond_mid_score": 1.3,
    "matching_rainbow_score": 1.45,
    "off_type_high_bond_score": 0.25,
    "wit_rainbow_score_early": 1.3,
    "wit_rainbow_score_late": 2.0,
    "late_turn": 65,
    "normal_cap_rule": [1200.0, 1.5, 1250.0, 2.0],
    "wit_cap_rule": [1200.0, 1.25, 1280.0, 2.0],
    "wit_full_energy_penalty_early": {"98": 0.3, "99": 0.4, "100": 0.5},
    "wit_full_energy_penalty_late": {"98": 0.35, "99": 0.5, "100": 0.65},
    "near_tie_gap": 0.5,
    "near_tie_non_wit_failure_max": 0.10,
    "safe_wit_score_early": 2.2,
    "safe_wit_score_late": 3.7,
    "safe_wit_failure_max": 0.10,
    "late_low_energy_wit_score_min": 6.0,
    "late_low_energy_vital_threshold": 30.0,
    "low_energy_vital_threshold": 50.0,
    "low_energy_purple_score_threshold": 3.0,
    "final_train_turns": [73, 75, 77],
    "final_train_min_vital": 10.0,
    "late_min_vital": 10.0,
    "recreation_motivation_threshold": 3.0,
    "recreation_safe_wit_score": 1.0,
    "recreation_best_score_threshold": 3.0,
    "recreation_best_failure_threshold": 0.25,
    "medic_safe_purple_score_threshold": 3.0,
    "medic_safe_late_failure_max": 0.10,
    "medic_defer_ranges": [[22, 29], [51, 59]],
    "summer_bad_status_turns": list(SUMMER_CAMP_TURNS),
}


GRAND_LIVE_DEFAULTS: dict[str, Any] = {
    "buy_clocks_with_carats": True,
    "max_clocks_bought_per_career": 3,
    # Legacy broad-tier fallback weights. Still used by choose_square callers
    # that do not pass the contextual Grand Live policy.
    "grand_live_song_square_weight": 400.0,
    "grand_live_skill_square_weight": 100.0,
    "grand_live_parameter_square_weight": 200.0,
    "grand_live_hp_square_weight": 50.0,

    # Live Tree contextual policy.
    "grand_live_contextual_square_policy": True,
    "grand_live_panic_turns_before_concert": 3,
    "grand_live_panic_min_session_songs": 3,

    # Training / rest / token scoring.
    "grand_live_token_score_weight": 0.01,
    "grand_live_good_training_score": 1.0,
    "grand_live_rest_score": 1.05,
    "grand_live_wit_base_score": 1.0,
    "grand_live_wit_full_vital_penalty_before_t24": {"98": 0.0, "99": 0.0, "100": 0.0},
    "grand_live_wit_full_vital_penalty_from_t24": {"98": 0.2, "99": 0.4, "100": 0.8},
    "grand_live_failure_penalty_denominator": 50.0,

    # Support scoring.
    "grand_live_support_bond_low_score": 0.5,
    "grand_live_support_bond_mid_score": 0.75,
    "grand_live_support_stack_bonus": 0.1,
    "grand_live_matching_rainbow_score": 1.0,
    "grand_live_wit_rainbow_score": 1.2,
    "grand_live_off_type_max_bond_score": 0.05,
    "grand_live_rainbow_stack_bonus": 0.25,
    "grand_live_npc_score": 0.05,

    # Light Hello (support id 30052).
    "grand_live_light_hello_first_score": 1.25,
    "grand_live_light_hello_wit_score": 1.2,
    "grand_live_light_hello_non_wit_score": 1.0,
    "grand_live_light_hello_date_motivation_below": 3.0,
    "grand_live_light_hello_date_vital_min": 25.0,
    "grand_live_light_hello_date_vital_max": 65.0,
}


DEFAULT_BOT_CONFIG: dict[str, Any] = {
    "version": BOT_CONFIG_VERSION,
    "scenarios": {
        "4": MANT_DEFAULTS,
        "2": UNITY_DEFAULTS,
        "3": GRAND_LIVE_DEFAULTS,
    },
}


def default_bot_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_BOT_CONFIG)
