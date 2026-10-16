"""§12.6 config single-source-of-truth: the committed data/bot_config/default.json
must stay byte-equal (as parsed JSON) to the typed defaults in
career_bot/bot_config/defaults.py:default_bot_config().

The typed defaults are the source; regenerate the JSON with
scripts/gen_default_bot_config.py whenever defaults.py changes. This test is
the drift alarm — measured in-sync on 2026-07-26.
"""

import json
from pathlib import Path

from career_bot.bot_config.defaults import default_bot_config

ROOT = Path(__file__).resolve().parents[1]

STRUCTURALLY_INTEGRAL_PATHS = {
    "version",
    "scenarios.4.max_clocks_bought_per_career",
    "scenarios.4.late_aggressive_turn",
    "scenarios.4.summer_conserve_turns[]",
    "scenarios.4.medic_tank_turns",
    "scenarios.4.deck_match_min_count",
    "scenarios.4.mant_config.tier_count",
    "scenarios.4.mant_config.bbq_unmaxxed_cards",
    "scenarios.4.mant_config.pre_summer_window[]",
    "scenarios.4.mant_config.mega_late_buy_buffer",
    "scenarios.4.mant_config.pre_summer_tier",
    "scenarios.2.late_turn",
    "scenarios.2.max_clocks_bought_per_career",
    "scenarios.2.maiden_recovery_min_aptitude",
    "scenarios.2.final_train_turns[]",
    "scenarios.2.medic_defer_ranges[][]",
    "scenarios.2.summer_bad_status_turns[]",
    "scenarios.3.grand_live_panic_turns_before_concert",
    "scenarios.3.grand_live_panic_min_session_songs",
    "scenarios.3.max_clocks_bought_per_career",
}


def _integer_paths(value, path=""):
    if isinstance(value, dict):
        paths = set()
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else key
            paths.update(_integer_paths(item, child_path))
        return paths
    if isinstance(value, list):
        paths = set()
        for item in value:
            paths.update(_integer_paths(item, f"{path}[]"))
        return paths
    if isinstance(value, int) and not isinstance(value, bool):
        return {path}
    return set()


def test_default_json_matches_typed_defaults():
    disk = json.loads((ROOT / "data" / "bot_config" / "default.json").read_text(encoding="utf-8"))
    code = default_bot_config()
    assert json.dumps(disk, sort_keys=True) == json.dumps(code, sort_keys=True), (
        "data/bot_config/default.json drifted from default_bot_config(); "
        "regenerate it with scripts/gen_default_bot_config.py"
    )


def test_only_structurally_integral_defaults_remain_integers():
    assert _integer_paths(default_bot_config()) == STRUCTURALLY_INTEGRAL_PATHS
