"""Preset scenario_id round-trip (§10.2 Phase-5 item 4, deferred half).

Before this change ``serialize_preset`` DROPPED the scenario id on save and
``hydrate_preset`` force-stamped MANT (4) on load, so a persisted non-MANT
preset lost its scenario and only survived because
``backend.app.domain.preset_runtime.sync_runtime_preset_scenario`` rescued the id at
RUNTIME from the server/request. These tests pin the three contracts the change
has to keep simultaneously:

  * legacy presets (no stored scenario key) hydrate BYTE-IDENTICALLY to the old
    force-stamp behaviour -- values AND key order;
  * a stored scenario id survives save -> load -> ``apply_bot_config_to_preset``
    and reaches the right scenario strategy;
  * the runtime rescue still OVERRIDES the stored id (server state wins).
"""

import copy
import json

from career_bot.bot_config import MANT_DEFAULTS, UNITY_CONFIG_KEY, apply_bot_config_to_preset
from career_bot.planning.presets import (
    MANT_SCENARIO_ID,
    PresetStore,
    hydrate_preset,
    serialize_preset,
    stored_scenario_id,
)
from career_bot.scenarios import resolve_scenario_id
from backend.app.domain.preset_runtime import sync_runtime_preset_scenario

UNITY_SCENARIO_ID = 2


# ---------------------------------------------------------------------------
# (a) legacy hydration is byte-identical to the pre-round-trip implementation
# ---------------------------------------------------------------------------

# Key order of the MANT_DEFAULTS block as hydrate_preset wrote it at f849a3b,
# MINUS the three knobs bot-config schema v2 deprecated (§12.6:
# special_training / spirit_explosion / wit_special_multiplier, which sat
# between "extra_weight"/"npc_score_value" and "compensate_failure" and were
# never read back off the runtime preset). Everything else -- values AND order
# -- is still pinned: json.dumps() below compares order too, so this list is
# part of the pin, not decoration.
_HEAD_DEFAULT_KEYS = (
    "cure_asap_conditions",
    "expect_attribute",
    "score_value",
    "base_score",
    "stat_value_multiplier",
    "extra_weight",
    "npc_score_value",
    "compensate_failure",
    "summer_score_threshold",
    "motivation_threshold_year1",
    "motivation_threshold_year2",
    "motivation_threshold_year3",
    "prioritize_recreation",
    "pal_thresholds",
    "rest_threshold",
    "buy_notepads",
    "manual_purchase_at_end",
)


def _hydrate_at_head(raw):
    """Verbatim transcription of ``hydrate_preset`` as of f849a3b
    (``git show f849a3b:career_bot/planning/presets.py``): serialize, force-stamp
    MANT under both scenario keys, deep-copy the MANT defaults in the order
    above, then reset ``mant_config``.

    Legacy raws carry no scenario key, so today's ``serialize_preset`` takes the
    exact same path it took at f849a3b for these inputs -- which is what makes
    this a fair reference rather than a circular one.
    """
    data = serialize_preset(raw)
    data["scenario_id"] = MANT_SCENARIO_ID
    data["scenario"] = MANT_SCENARIO_ID
    for key in _HEAD_DEFAULT_KEYS:
        data[key] = copy.deepcopy(MANT_DEFAULTS[key])
    data["mant_config"] = {}
    return data


LEGACY_CASES = [
    {},
    {"name": "default"},
    {
        "name": "xguri parent",
        "running_style": 2,
        "learn_skill_list": [["1001", "1002"], "2001"],
        "learn_skill_blacklist": "9001,9002",
        "extra_race_list": ["101", 102, "bad"],
        "learn_skill_threshold": 500,
    },
    {"name": "sirius", "sirius_throne_schedule": {"a": 1}},
    {"name": "aliases", "race_list": [7], "blacklistedSkills": "1,2", "skill_blacklist": ["3"]},
]


def test_legacy_presets_hydrate_byte_identical_to_pre_roundtrip():
    for raw in LEGACY_CASES:
        expected = json.dumps(_hydrate_at_head(raw), ensure_ascii=False, sort_keys=False)
        actual = json.dumps(hydrate_preset(raw), ensure_ascii=False, sort_keys=False)
        assert actual == expected, f"legacy hydration drifted for {raw!r}"


def test_legacy_presets_serialize_without_a_scenario_key():
    # The stored file shape for a legacy preset is unchanged -- no new key, so
    # nothing re-writes preset JSON just by being read.
    for raw in LEGACY_CASES:
        assert "scenario_id" not in serialize_preset(raw)
        assert "scenario" not in serialize_preset(raw)


def test_legacy_stored_file_still_hydrates_to_mant(tmp_path):
    store = PresetStore(tmp_path)
    store.ensure()
    (tmp_path / "presets" / "legacy.json").write_text(
        json.dumps({"name": "legacy", "extra_race_list": [1001]}), encoding="utf-8"
    )
    loaded = store.read_one("legacy")
    assert loaded is not None
    assert loaded["scenario_id"] == MANT_SCENARIO_ID
    assert loaded["scenario"] == MANT_SCENARIO_ID


# ---------------------------------------------------------------------------
# (b) MANT presets now serialize WITH scenario_id=4 (additive key only)
# ---------------------------------------------------------------------------

def test_mant_preset_serializes_with_its_scenario_id():
    hydrated = hydrate_preset({"name": "mant"})
    serialized = serialize_preset(hydrated)
    assert serialized["scenario_id"] == MANT_SCENARIO_ID
    # Additive only: every pre-existing key keeps its old value.
    legacy = serialize_preset({"name": "mant"})
    assert {k: v for k, v in serialized.items() if k != "scenario_id"} == legacy


def test_scenario_id_is_the_only_scenario_key_persisted():
    # The legacy 'scenario' alias is regenerated on hydrate, never written.
    serialized = serialize_preset(hydrate_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID}))
    assert serialized["scenario_id"] == UNITY_SCENARIO_ID
    assert "scenario" not in serialized


# ---------------------------------------------------------------------------
# (c) a Unity preset round-trips and dispatches Unity delivery
# ---------------------------------------------------------------------------

def test_serialize_persists_scenario_id_from_either_key():
    assert serialize_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID})["scenario_id"] == 2
    assert serialize_preset({"name": "u", "scenario": UNITY_SCENARIO_ID})["scenario_id"] == 2
    assert serialize_preset({"name": "u", "scenario_id": "2"})["scenario_id"] == 2


def test_hydrate_respects_a_stored_scenario_id():
    hydrated = hydrate_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID})
    assert hydrated["scenario_id"] == UNITY_SCENARIO_ID
    assert hydrated["scenario"] == UNITY_SCENARIO_ID
    assert resolve_scenario_id(hydrated) == UNITY_SCENARIO_ID


def test_unregistered_or_unset_scenario_ids_fall_back_to_mant():
    for raw in ({"scenario_id": 99}, {"scenario_id": 0}, {"scenario": 0}, {"scenario_id": "nope"}):
        hydrated = hydrate_preset(dict(raw, name="x"))
        assert hydrated["scenario_id"] == MANT_SCENARIO_ID
        assert hydrated["scenario"] == MANT_SCENARIO_ID


def test_store_round_trips_a_unity_preset(tmp_path):
    store = PresetStore(tmp_path)
    written = store.write({"name": "unity run", "scenario_id": UNITY_SCENARIO_ID})
    # write() persists the serialized form and hands back the hydrated one.
    assert written["scenario_id"] == UNITY_SCENARIO_ID

    on_disk = json.loads((tmp_path / "presets" / "unity run.json").read_text("utf-8"))
    assert on_disk["scenario_id"] == UNITY_SCENARIO_ID

    loaded = store.read_one("unity run")
    assert loaded is not None
    assert loaded["scenario_id"] == UNITY_SCENARIO_ID
    assert [p["scenario_id"] for p in store.read_all()] == [UNITY_SCENARIO_ID]


def test_save_races_style_rewrite_keeps_the_scenario(tmp_path):
    # Mirrors PresetService.save_races: read the hydrated preset, mutate one
    # field, write it straight back. Before the round-trip this silently
    # downgraded a Unity preset to MANT.
    store = PresetStore(tmp_path)
    store.write({"name": "unity run", "scenario_id": UNITY_SCENARIO_ID})
    preset = store.read_one("unity run")
    preset["extra_race_list"] = [1001, 1002]
    store.write(preset)

    reloaded = store.read_one("unity run")
    assert reloaded["extra_race_list"] == [1001, 1002]
    assert reloaded["scenario_id"] == UNITY_SCENARIO_ID


def test_round_tripped_unity_preset_dispatches_unity_delivery(tmp_path):
    store = PresetStore(tmp_path)
    store.write({"name": "unity run", "scenario_id": UNITY_SCENARIO_ID})
    loaded = store.read_one("unity run")

    applied = apply_bot_config_to_preset(loaded)
    # Unity's strategy attaches its config under a private key; MANT's flattens
    # into mant_config instead. The key present proves which strategy ran.
    assert UNITY_CONFIG_KEY in applied
    assert applied[UNITY_CONFIG_KEY]

    mant = apply_bot_config_to_preset(hydrate_preset({"name": "mant"}))
    assert UNITY_CONFIG_KEY not in mant
    assert "mant_config" in mant


# ---------------------------------------------------------------------------
# stored_scenario_id helper + runtime-rescue precedence (must be UNCHANGED)
# ---------------------------------------------------------------------------

def test_stored_scenario_id_distinguishes_absent_from_mant():
    assert stored_scenario_id({}) is None
    assert stored_scenario_id(None) is None
    assert stored_scenario_id({"scenario_id": 0}) is None
    assert stored_scenario_id({"scenario_id": 4}) == 4
    assert stored_scenario_id({"scenario": 2}) == 2
    assert stored_scenario_id({"scenario_id": 0, "scenario": 2}) == 2


class _Req:
    def __init__(self, scenario_id=0):
        self.scenario_id = scenario_id


def test_runtime_rescue_still_overrides_the_stored_scenario():
    # Server state wins over whatever the preset persisted.
    preset = hydrate_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID})
    req = _Req()
    result = {"data": {"chara_info": {"scenario_id": MANT_SCENARIO_ID}}}
    assert sync_runtime_preset_scenario(preset, result, req) == MANT_SCENARIO_ID
    assert preset["scenario_id"] == MANT_SCENARIO_ID
    assert preset["scenario"] == MANT_SCENARIO_ID
    assert req.scenario_id == MANT_SCENARIO_ID


def test_runtime_rescue_falls_back_to_the_request_then_the_preset():
    preset = hydrate_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID})
    req = _Req(MANT_SCENARIO_ID)
    assert sync_runtime_preset_scenario(preset, None, req) == MANT_SCENARIO_ID

    # No server result and no request hint -> the stored id is what survives.
    # This is the leg that used to be MANT-only because the id was dropped.
    preset = hydrate_preset({"name": "u", "scenario_id": UNITY_SCENARIO_ID})
    assert sync_runtime_preset_scenario(preset, None, _Req()) == UNITY_SCENARIO_ID
    assert preset["scenario_id"] == UNITY_SCENARIO_ID
