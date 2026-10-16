import json
import logging

import pytest

from career_bot.bot_config import (
    DEFAULT_BOT_CONFIG,
    FIELD_DESCRIPTIONS,
    BotConfigStore,
    BotConfigValidationError,
    UNITY_CONFIG_KEY,
    apply_bot_config_to_preset,
    default_bot_config,
    validate_bot_config,
)
from backend.app.app import create_app


def test_default_config_contains_current_mant_and_unity_defaults():
    cfg = default_bot_config()

    # v2 = §12.6 deprecation of the never-read MANT knobs; see
    # tests/test_bot_config_migration.py for the upgrade contract.
    assert cfg["version"] == 2
    assert cfg["scenarios"]["4"]["score_value"][0] == [0.11, 0.1, 0.006, 0.09]
    assert cfg["scenarios"]["4"]["failure_penalty_denominator"] == 25.0
    assert cfg["scenarios"]["2"]["failure_score_penalty"] == 50.0
    assert cfg["scenarios"]["2"]["stamina_blue_purple_soul_bonus"] == 0.0
    assert cfg["scenarios"]["2"]["wit_blue_purple_soul_bonus"] == 0.0
    assert cfg["scenarios"]["2"]["speed_blue_purple_soul_stack_bonus_step"] == 0.1
    assert cfg["scenarios"]["2"]["stamina_blue_purple_soul_stack_bonus_step"] == 0.0
    assert cfg["scenarios"]["2"]["wit_full_energy_penalty_late"]["100"] == 0.65
    assert cfg["scenarios"]["3"]["grand_live_contextual_square_policy"] is True
    assert cfg["scenarios"]["3"]["grand_live_rest_score"] == 1.05
    assert cfg["scenarios"]["3"]["grand_live_light_hello_first_score"] == 1.25
    assert cfg["scenarios"]["3"]["grand_live_light_hello_date_vital_min"] == 25
    assert cfg["scenarios"]["3"]["grand_live_wit_full_vital_penalty_before_t24"]["100"] == 0.0
    assert cfg["scenarios"]["3"]["grand_live_wit_full_vital_penalty_from_t24"] == {"98": 0.2, "99": 0.4, "100": 0.8}


def test_validate_rejects_unknown_fields_and_invalid_types():
    with pytest.raises(BotConfigValidationError):
        validate_bot_config({"scenarios": {"4": {"unknown": 1}}})

    with pytest.raises(BotConfigValidationError):
        validate_bot_config({"scenarios": {"2": {"min_train_score": "high"}}})

    with pytest.raises(BotConfigValidationError):
        validate_bot_config({"scenarios": {"3": {"grand_live_contextual_square_policy": 1}}})

    with pytest.raises(BotConfigValidationError):
        validate_bot_config({"scenarios": {"3": {"grand_live_rest_score": "low"}}})

    partial = validate_bot_config({"scenarios": {"2": {"min_train_score": 2}}})
    assert partial["scenarios"]["2"]["min_train_score"] == 2.0
    assert partial["scenarios"]["4"]["rest_threshold"] == 48.0

    with pytest.raises(BotConfigValidationError, match="grand_live_panic_turns_before_concert must be an integer"):
        validate_bot_config({"scenarios": {"3": {"grand_live_panic_turns_before_concert": 2.5}}})

    numeric = validate_bot_config({
        "scenarios": {
            "4": {"rest_threshold": 48.5},
            "3": {"grand_live_rest_score": 0.9},
        },
    })
    assert numeric["scenarios"]["4"]["rest_threshold"] == 48.5
    assert isinstance(numeric["scenarios"]["4"]["rest_threshold"], float)
    assert numeric["scenarios"]["3"]["grand_live_rest_score"] == 0.9
    assert isinstance(numeric["scenarios"]["3"]["grand_live_rest_score"], float)

    migrated = validate_bot_config({"scenarios": {"2": {"speed_power_guts_stack_bonus_step": 0.2}}})
    unity = migrated["scenarios"]["2"]
    assert unity["speed_blue_purple_soul_stack_bonus_step"] == 0.2
    assert unity["power_blue_purple_soul_stack_bonus_step"] == 0.2
    assert unity["guts_blue_purple_soul_stack_bonus_step"] == 0.2
    assert unity["stamina_blue_purple_soul_stack_bonus_step"] == 0.0


def test_saved_integer_is_coerced_for_decimal_capable_knob():
    saved = default_bot_config()
    saved["scenarios"]["4"]["rest_threshold"] = 48

    validated = validate_bot_config(saved)

    assert validated["scenarios"]["4"]["rest_threshold"] == 48.0
    assert isinstance(validated["scenarios"]["4"]["rest_threshold"], float)


def test_store_reads_default_saves_active_and_resets(tmp_path):
    default_path = tmp_path / "data" / "bot_config" / "default.json"
    default_path.parent.mkdir(parents=True)
    default_path.write_text(
        json.dumps(default_bot_config()),
        encoding="utf-8",
    )
    store = BotConfigStore(tmp_path, tmp_path / "state")
    default = store.read_active()
    assert default["scenarios"]["4"]["rest_threshold"] == 48
    assert store.default_path.exists()

    edited = default_bot_config()
    edited["scenarios"]["4"]["rest_threshold"] = 60
    saved = store.write_active(edited)
    assert saved["scenarios"]["4"]["rest_threshold"] == 60
    assert store.read_active()["scenarios"]["4"]["rest_threshold"] == 60

    reset = store.reset_active()
    assert reset["scenarios"]["4"]["rest_threshold"] == 48
    assert not store.active_path.exists()


def test_store_copies_legacy_active_config_once(tmp_path, caplog):
    legacy_path = tmp_path / "data" / "bot_config" / "active.json"
    legacy_path.parent.mkdir(parents=True)
    legacy = default_bot_config()
    legacy["scenarios"]["4"]["rest_threshold"] = 61
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    store = BotConfigStore(tmp_path, tmp_path / "state")
    caplog.set_level(logging.INFO)

    assert store.read_active()["scenarios"]["4"]["rest_threshold"] == 61
    assert store.active_path.is_file()
    assert legacy_path.is_file()
    assert "Migrated legacy active bot config" in caplog.text

    legacy["scenarios"]["4"]["rest_threshold"] = 62
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert store.read_active()["scenarios"]["4"]["rest_threshold"] == 61


def test_apply_bot_config_flattens_mant_and_attaches_unity():
    cfg = default_bot_config()
    cfg["scenarios"]["4"]["rest_threshold"] = 61
    cfg["scenarios"]["2"]["min_train_score"] = 2.5
    cfg["scenarios"]["3"]["grand_live_rest_score"] = 0.9

    mant = apply_bot_config_to_preset({"scenario_id": 4, "rest_threshold": 10}, config=cfg)
    assert mant["rest_threshold"] == 61
    assert UNITY_CONFIG_KEY not in mant

    unity = apply_bot_config_to_preset({"scenario_id": 2}, config=cfg)
    assert unity[UNITY_CONFIG_KEY]["min_train_score"] == 2.5
    assert "rest_threshold" not in unity

    grand_live = apply_bot_config_to_preset({"scenario_id": 3}, config=cfg)
    assert grand_live["grand_live_rest_score"] == 0.9
    assert grand_live["grand_live_light_hello_date_motivation_below"] == 3
    assert UNITY_CONFIG_KEY not in grand_live


def test_bot_config_api_get_save_and_reset(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    routes = {route.path for route in app.routes}
    assert "/api/bot-config" in routes
    assert "/api/bot-config/reset" in routes

    store = app.state.ctx.bot_config_store

    body = store.response()
    assert body["success"] is True
    assert {s["scenario_id"] for s in body["scenarios"]} == {2, 3, 4}
    assert all(
        spec.get("description")
        for specs in body["fields"].values()
        for spec in specs
    )

    edited = body["config"]
    edited["scenarios"]["2"]["min_train_score"] = 3.0
    saved = store.write_active(edited)
    assert saved["scenarios"]["2"]["min_train_score"] == 3.0

    with pytest.raises(BotConfigValidationError):
        store.write_active({"scenarios": {"2": {"bad": 1}}})

    reset = store.reset_active()
    assert reset["scenarios"]["2"]["min_train_score"] == 1.0


def _tuning_knob_keys(defaults):
    """Yield every *tuning-knob* leaf key in a scenario defaults dict.

    Recurses into knob-GROUP dicts -- whose sub-keys are knob identifiers
    (e.g. ``mant_config`` with ``tier_count``/``pre_summer_tier``/...) -- but
    treats a value-MAP dict as a single structural node with no per-entry
    knob: ``wit_full_energy_penalty_early``/``_late`` are keyed by energy
    level ("98"/"99"/"100"), i.e. data, not tuning-knob names. This mirrors
    the plan's "non-structural default leaf" distinction so the guard below
    does not demand a description for each energy level.
    """
    for key, value in defaults.items():
        if isinstance(value, dict) and value and all(k.isidentifier() for k in value):
            yield from _tuning_knob_keys(value)
        elif isinstance(value, dict):
            continue  # structural value-map: sub-keys are data, not knobs
        else:
            yield key


def test_every_tuning_knob_has_explicit_description():
    """Guard: a new tuning knob added to *_DEFAULTS without a matching
    FIELD_DESCRIPTIONS entry would silently show the generic placeholder in
    the Web UI forever (test_bot_config_api_* only checks the description is
    truthy, which the fallback satisfies). Fail CI instead."""
    missing = sorted({
        key
        for defaults in DEFAULT_BOT_CONFIG["scenarios"].values()
        for key in _tuning_knob_keys(defaults)
        if key not in FIELD_DESCRIPTIONS
    })
    assert not missing, (
        "tuning knobs missing an explicit FIELD_DESCRIPTIONS entry (they would "
        f"fall back to the generic Web-UI placeholder): {missing}"
    )
