import json
import logging

from career_bot.planning.presets import (
    PresetStore,
    RacePresetStore,
    serialize_race_preset,
    migrate_race_presets,
    apply_race_preset,
    serialize_preset,
)
from career_bot.planning.races import RacePlanner


# ---------------------------------------------------------------------------
# serialize_race_preset
# ---------------------------------------------------------------------------

def test_serialize_normalizes_races_to_ints():
    result = serialize_race_preset({"name": "My Races", "extra_race_list": ["1001", "1002", "abc", 1003]})
    assert result["extra_race_list"] == [1001, 1002, 1003]


def test_serialize_slugifies_name():
    result = serialize_race_preset({"name": "  My Fancy/Races!  ", "extra_race_list": []})
    assert result["name"] == "My FancyRaces"


def test_serialize_default_name_when_empty():
    result = serialize_race_preset({"extra_race_list": [1001]})
    assert result["name"] == "races"


def test_serialize_accepts_races_alias():
    result = serialize_race_preset({"name": "r", "races": [2001, 2002]})
    assert result["extra_race_list"] == [2001, 2002]


# ---------------------------------------------------------------------------
# RacePresetStore write / read_one / read_all / delete round-trip
# ---------------------------------------------------------------------------

def test_write_and_read_one(tmp_path):
    store = RacePresetStore(tmp_path)
    store.write({"name": "classics", "extra_race_list": [1001, 1002]})
    rp = store.read_one("classics")
    assert rp is not None
    assert rp["extra_race_list"] == [1001, 1002]


def test_read_one_case_insensitive(tmp_path):
    store = RacePresetStore(tmp_path)
    store.write({"name": "Classics", "extra_race_list": [1001]})
    assert store.read_one("CLASSICS") is not None
    assert store.read_one("classics") is not None


def test_read_all_sorted(tmp_path):
    store = RacePresetStore(tmp_path)
    store.write({"name": "zzz", "extra_race_list": [3001]})
    store.write({"name": "aaa", "extra_race_list": [1001]})
    all_presets = store.read_all()
    assert [p["name"] for p in all_presets] == ["aaa", "zzz"]


def test_read_one_returns_none_for_missing(tmp_path):
    store = RacePresetStore(tmp_path)
    assert store.read_one("nonexistent") is None


def test_delete_removes_preset(tmp_path):
    store = RacePresetStore(tmp_path)
    store.write({"name": "to-delete", "extra_race_list": [1001]})
    assert store.read_one("to-delete") is not None
    deleted = store.delete("to-delete")
    assert deleted is True
    assert store.read_one("to-delete") is None


def test_delete_nonexistent_returns_false(tmp_path):
    store = RacePresetStore(tmp_path)
    assert store.delete("ghost") is False


def test_write_normalizes_on_disk(tmp_path):
    store = RacePresetStore(tmp_path)
    store.write({"name": "test preset", "extra_race_list": ["999", 1000]})
    # Read the raw file to confirm stored shape
    files = list((tmp_path / "race_presets").glob("*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text())
    assert on_disk["extra_race_list"] == [999, 1000]
    assert on_disk["name"] == "test preset"


# ---------------------------------------------------------------------------
# migrate_race_presets
# ---------------------------------------------------------------------------

def _seed_skill_preset(base_path, name, races):
    preset_dir = base_path / "presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    data = serialize_preset({"name": name, "extra_race_list": races})
    (preset_dir / f"{data['name']}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_migration_creates_race_presets_from_skill_presets(tmp_path):
    _seed_skill_preset(tmp_path, "xguri parent", [1001, 1002])
    count = migrate_race_presets(tmp_path)
    assert count == 1
    store = RacePresetStore(tmp_path)
    rp = store.read_one("xguri parent races")
    assert rp is not None
    assert rp["extra_race_list"] == [1001, 1002]


def test_migration_skips_presets_without_races(tmp_path):
    _seed_skill_preset(tmp_path, "no races preset", [])
    count = migrate_race_presets(tmp_path)
    assert count == 0


def test_migration_is_idempotent(tmp_path):
    _seed_skill_preset(tmp_path, "xguri parent", [1001, 1002])
    count1 = migrate_race_presets(tmp_path)
    count2 = migrate_race_presets(tmp_path)
    assert count1 == 1
    assert count2 == 0  # dir non-empty — no-op


def test_migration_handles_multiple_presets(tmp_path):
    _seed_skill_preset(tmp_path, "preset a", [1001])
    _seed_skill_preset(tmp_path, "preset b", [2001, 2002])
    _seed_skill_preset(tmp_path, "empty preset", [])
    count = migrate_race_presets(tmp_path)
    assert count == 2
    store = RacePresetStore(tmp_path)
    assert store.read_one("preset a races") is not None
    assert store.read_one("preset b races") is not None
    assert store.read_one("empty preset races") is None


def test_readers_fall_back_to_legacy_directories_before_migration(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    _seed_skill_preset(source_root / "data", "legacy skill", [1001])
    legacy_races = source_root / "data" / "race_presets"
    legacy_races.mkdir(parents=True)
    (legacy_races / "legacy race.json").write_text(
        json.dumps({"name": "legacy race", "extra_race_list": [2001]}),
        encoding="utf-8",
    )

    assert PresetStore(state_root, source_root).read_one("legacy skill") is not None
    assert RacePresetStore(state_root, source_root).read_one("legacy race") is not None
    assert not (state_root / "presets" / "legacy skill.json").exists()
    assert not (state_root / "race_presets" / "legacy race.json").exists()


def test_migration_copies_legacy_presets_without_removing_originals(
    tmp_path, caplog,
):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    _seed_skill_preset(source_root / "data", "legacy skill", [1001])
    caplog.set_level(logging.INFO)

    assert migrate_race_presets(state_root, source_root) == 2
    assert PresetStore(state_root).read_one("legacy skill") is not None
    assert RacePresetStore(state_root).read_one("legacy skill races") is not None
    assert (source_root / "data" / "presets" / "legacy skill.json").is_file()
    assert "Migrated 1 legacy presets preset(s)" in caplog.text


# ---------------------------------------------------------------------------
# apply_race_preset
# ---------------------------------------------------------------------------

def test_apply_race_preset_overrides_extra_race_list():
    skill_preset = {"name": "sp", "extra_race_list": [1001, 1002], "running_style": 2}
    race_preset = {"name": "rp", "extra_race_list": [9001, 9002, 9003]}
    result = apply_race_preset(skill_preset, race_preset)
    assert result["extra_race_list"] == [9001, 9002, 9003]
    assert result["running_style"] == 2  # other fields intact


def test_apply_race_preset_does_not_mutate_original():
    skill_preset = {"name": "sp", "extra_race_list": [1001]}
    race_preset = {"name": "rp", "extra_race_list": [2001]}
    apply_race_preset(skill_preset, race_preset)
    assert skill_preset["extra_race_list"] == [1001]


def test_apply_race_preset_with_none_is_identity():
    skill_preset = {"name": "sp", "extra_race_list": [1001]}
    result = apply_race_preset(skill_preset, None)
    assert result["extra_race_list"] == [1001]


def test_apply_race_preset_empty_race_list_replaces():
    skill_preset = {"name": "sp", "extra_race_list": [1001, 1002]}
    race_preset = {"name": "rp", "extra_race_list": []}
    result = apply_race_preset(skill_preset, race_preset)
    assert result["extra_race_list"] == []


def test_choose_returns_zero_with_low_fans_and_no_wanted_race(tmp_path):
    planner = RacePlanner(tmp_path)
    planner.program = {
        500: {"ground": 1, "distance": 1200, "name": "Available race"},
    }
    state = {
        "data": {
            "chara_info": {
                "turn": 20,
                "fans": 0,
                "proper_ground_turf": 7,
                "proper_distance_short": 7,
            },
            "home_info": {
                "command_info_array": [
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                ],
            },
            "race_condition_array": [{"program_id": 500}],
        },
    }

    assert planner.choose(state, {"extra_race_list": []}) == 0
