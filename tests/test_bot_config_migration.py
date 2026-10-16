"""§12.6 deferred half — versioned deprecation of unread bot-config knobs.

Schema v2 drops three MANT knobs no code path ever read
(``special_training`` / ``spirit_explosion`` / ``wit_special_multiplier``) and
the never-read third column of every ``npc_score_value`` row. Because
``validate_bot_config`` rejects unknown keys outright, an already-saved v1
config would become a hard error without an upgrade step — these tests pin that
it does not, and that nothing else about a stored config moves.
"""

import copy
import json

import pytest

from career_bot.bot_config import (
    BOT_CONFIG_VERSION,
    BotConfigStore,
    BotConfigValidationError,
    UNITY_CONFIG_KEY,
    apply_bot_config_to_preset,
    default_bot_config,
    migrate_bot_config,
    validate_bot_config,
)
from career_bot.planning.presets import hydrate_preset

DEAD_KEYS = ("special_training", "spirit_explosion", "wit_special_multiplier")

# The v1 values verbatim, as data/bot_config/default.json carried them at 07397aa.
V1_DEAD_VALUES = {
    "special_training": [0.095, 0.095, 0.095, 0.095, 0],
    "spirit_explosion": [[0.16, 0.16, 0.16, 0.06, 0.11]] * 5,
    "wit_special_multiplier": [1.57, 1.37],
}
V1_NPC_SCORE_VALUE = [
    [0.05, 0.05, 0.05],
    [0.05, 0.05, 0.05],
    [0.05, 0.05, 0.05],
    [0.03, 0.05, 0.05],
    [0, 0, 0.05],
]


def _v1_config(**mant_overrides):
    """A realistic *stored* v1 config: the v2 defaults, plus the dead keys and
    the wide npc rows put back, stamped version 1."""
    cfg = default_bot_config()
    cfg["version"] = 1
    mant = cfg["scenarios"]["4"]
    mant.update(copy.deepcopy(V1_DEAD_VALUES))
    mant["npc_score_value"] = copy.deepcopy(V1_NPC_SCORE_VALUE)
    mant.update(mant_overrides)
    return cfg


# ---------------------------------------------------------------------------
# migrate_bot_config itself
# ---------------------------------------------------------------------------

def test_v1_config_migrates_dead_keys_out_and_stamps_the_version():
    migrated = migrate_bot_config(_v1_config())

    assert migrated["version"] == BOT_CONFIG_VERSION == 2
    mant = migrated["scenarios"]["4"]
    for key in DEAD_KEYS:
        assert key not in mant, f"{key} survived the v1 -> v2 migration"
    assert mant["npc_score_value"] == [[0.05, 0.05], [0.05, 0.05], [0.05, 0.05], [0.03, 0.05], [0, 0]]


def test_migration_loses_nothing_else_not_even_edited_live_knobs():
    """Everything except the deprecated keys/column comes out byte-identical —
    including knobs the operator had customised away from the defaults."""
    stored = _v1_config(rest_threshold=61, late_stat_cap=1400, mant_config={"tier_count": 9})
    stored["scenarios"]["2"]["min_train_score"] = 2.5

    migrated = migrate_bot_config(stored)

    expected = copy.deepcopy(stored)
    expected["version"] = BOT_CONFIG_VERSION
    for key in DEAD_KEYS:
        expected["scenarios"]["4"].pop(key)
    expected["scenarios"]["4"]["npc_score_value"] = [
        row[:2] for row in expected["scenarios"]["4"]["npc_score_value"]
    ]
    assert json.dumps(migrated, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert migrated["scenarios"]["4"]["rest_threshold"] == 61
    assert migrated["scenarios"]["4"]["mant_config"]["tier_count"] == 9
    assert migrated["scenarios"]["2"]["min_train_score"] == 2.5


def test_migration_does_not_mutate_its_input():
    stored = _v1_config()
    snapshot = copy.deepcopy(stored)
    migrate_bot_config(stored)
    assert stored == snapshot


def test_already_migrated_config_is_a_no_op():
    current = default_bot_config()
    assert current["version"] == BOT_CONFIG_VERSION
    assert migrate_bot_config(current) == current
    # ...and migrating twice changes nothing further.
    once = migrate_bot_config(_v1_config())
    assert migrate_bot_config(once) == once


def test_config_missing_the_version_field_is_treated_as_legacy():
    stored = _v1_config()
    stored.pop("version")
    migrated = migrate_bot_config(stored)
    assert migrated["version"] == BOT_CONFIG_VERSION
    for key in DEAD_KEYS:
        assert key not in migrated["scenarios"]["4"]

    # A null/0 version means the same thing.
    for blank in (None, 0, ""):
        blanked = _v1_config()
        blanked["version"] = blank
        assert migrate_bot_config(blanked)["version"] == BOT_CONFIG_VERSION


def test_unparseable_or_future_versions_are_left_for_validation_to_reject():
    for bad in ("nope", [1], BOT_CONFIG_VERSION + 1):
        stored = _v1_config()
        stored["version"] = bad
        assert migrate_bot_config(stored) is stored
        with pytest.raises(BotConfigValidationError):
            validate_bot_config(stored)


def test_non_dict_and_malformed_payloads_pass_through_untouched():
    for payload in (None, [], "x", 3, {"scenarios": []}):
        assert migrate_bot_config(payload) is payload
        with pytest.raises(BotConfigValidationError):
            validate_bot_config(payload)


def test_partial_config_without_scenarios_still_gets_stamped():
    assert migrate_bot_config({}) == {"version": BOT_CONFIG_VERSION}
    assert migrate_bot_config({"version": 1}) == {"version": BOT_CONFIG_VERSION}


def test_unity_legacy_stack_bonus_step_migration_still_runs_at_every_version():
    # Version-independent legacy rename (it predates the version field); it moved
    # from schema.py into migrations.py and must keep firing for v1 AND v2.
    for version in (1, BOT_CONFIG_VERSION):
        migrated = validate_bot_config(
            {"version": version, "scenarios": {"2": {"speed_power_guts_stack_bonus_step": 0.2}}}
        )
        unity = migrated["scenarios"]["2"]
        assert unity["speed_blue_purple_soul_stack_bonus_step"] == 0.2
        assert unity["power_blue_purple_soul_stack_bonus_step"] == 0.2
        assert unity["guts_blue_purple_soul_stack_bonus_step"] == 0.2
        assert unity["stamina_blue_purple_soul_stack_bonus_step"] == 0.0


# ---------------------------------------------------------------------------
# the load paths that must survive an old config on disk
# ---------------------------------------------------------------------------

def test_validate_accepts_a_v1_config_instead_of_erroring():
    validated = validate_bot_config(_v1_config(rest_threshold=61))
    assert validated["version"] == BOT_CONFIG_VERSION
    assert validated["scenarios"]["4"]["rest_threshold"] == 61
    for key in DEAD_KEYS:
        assert key not in validated["scenarios"]["4"]
    # Equal to the current defaults once the one edited knob is put back.
    expected = default_bot_config()
    expected["scenarios"]["4"]["rest_threshold"] = 61
    assert validated == expected


def test_wide_npc_rows_keep_extra_column_without_the_truncation_step():
    """Guard on WHY the row truncation is part of the migration, not cosmetic:
    the float row template accepts the stale decimal third column, so without
    migration that dead column would survive validation."""
    from career_bot.bot_config.schema import _validate_value

    validated = _validate_value(
        copy.deepcopy(V1_NPC_SCORE_VALUE),
        default_bot_config()["scenarios"]["4"]["npc_score_value"],
        "scenarios.4.npc_score_value",
    )

    assert len(validated[0]) == 3
    assert validated[0][2] == 0.05


def test_store_loads_and_rewrites_v1_files_on_disk(tmp_path):
    store = BotConfigStore(tmp_path, tmp_path / "state")
    store.ensure()
    # Both the generated default and the operator's saved config are stale v1.
    stale = _v1_config(rest_threshold=61)
    store.default_path.parent.mkdir(parents=True, exist_ok=True)
    store.default_path.write_text(json.dumps(stale), encoding="utf-8")
    store.active_path.write_text(json.dumps(stale), encoding="utf-8")

    default = store.read_default()
    active = store.read_active()
    for loaded in (default, active):
        assert loaded["version"] == BOT_CONFIG_VERSION
        assert loaded["scenarios"]["4"]["rest_threshold"] == 61
        for key in DEAD_KEYS:
            assert key not in loaded["scenarios"]["4"]

    # The full API response (config + default_config + field specs) builds fine
    # off the stale files, and no field spec advertises a dead knob.
    body = store.response()
    assert body["success"] is True
    spec_keys = {spec["key"] for specs in body["fields"].values() for spec in specs}
    assert not spec_keys & set(DEAD_KEYS)
    assert "npc_score_value" in spec_keys

    # Saving a v1 payload upgrades the file in place rather than 400-ing.
    saved = store.write_active(stale)
    assert saved["version"] == BOT_CONFIG_VERSION
    on_disk = json.loads(store.active_path.read_text(encoding="utf-8"))
    assert on_disk["version"] == BOT_CONFIG_VERSION
    for key in DEAD_KEYS:
        assert key not in on_disk["scenarios"]["4"]


# ---------------------------------------------------------------------------
# no live-knob behavior change downstream
# ---------------------------------------------------------------------------

def test_apply_paths_produce_identical_live_knobs_from_v1_and_v2_configs():
    v1 = _v1_config(rest_threshold=61)
    v2 = default_bot_config()
    v2["scenarios"]["4"]["rest_threshold"] = 61

    mant_from_v1 = apply_bot_config_to_preset({"scenario_id": 4}, config=v1)
    mant_from_v2 = apply_bot_config_to_preset({"scenario_id": 4}, config=v2)
    assert mant_from_v1 == mant_from_v2
    for key in DEAD_KEYS:
        assert key not in mant_from_v1
    assert mant_from_v1["rest_threshold"] == 61
    assert mant_from_v1["npc_score_value"] == [[0.05, 0.05], [0.05, 0.05], [0.05, 0.05], [0.03, 0.05], [0, 0]]

    unity_from_v1 = apply_bot_config_to_preset({"scenario_id": 2}, config=v1)
    unity_from_v2 = apply_bot_config_to_preset({"scenario_id": 2}, config=v2)
    assert unity_from_v1 == unity_from_v2
    assert unity_from_v1[UNITY_CONFIG_KEY] == v2["scenarios"]["2"]


def test_hydrate_preset_no_longer_seeds_the_dead_keys():
    hydrated = hydrate_preset({"name": "mant"})
    for key in DEAD_KEYS:
        assert key not in hydrated
    # Live knobs it still seeds are untouched.
    assert hydrated["npc_score_value"] == default_bot_config()["scenarios"]["4"]["npc_score_value"]
    assert hydrated["rest_threshold"] == 48


def test_npc_bond_scoring_is_unchanged_by_the_narrower_rows():
    """The dropped column was never read: _npc_score interpolates [0] -> [1]."""
    from career_bot.scenarios.mant.strategy import MantStrategy

    strategy = MantStrategy()
    wide = {"npc_score_value": copy.deepcopy(V1_NPC_SCORE_VALUE)}
    narrow = {"npc_score_value": default_bot_config()["scenarios"]["4"]["npc_score_value"]}
    for turn in (1, 24, 25, 48, 49, 60, 61, 72, 73, 78):
        for bond in (0, 15, 40, 79, 80, 100):
            assert strategy._npc_score(bond, turn, wide) == strategy._npc_score(bond, turn, narrow)
