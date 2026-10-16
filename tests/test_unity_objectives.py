import sqlite3
from pathlib import Path

import pytest

from career_bot.planning.races import RacePlanner
from career_bot.engine import CareerRunner
from career_bot.scenarios import unity_cup
from career_bot.scenarios.unity_cup import UnityCupStrategy
from career_bot.scenarios.unity_cup.team_race import _team_race_set_id
import uma_data

from tests._helpers import race_command, rest_command, train_command


# Real single_mode_route_race rows for chara 1051 / route 54, captured
# 2026-07-08 (raw.jsonl) and confirmed against master.mdb via PRAGMA + direct
# query. Ids 657/658 are race objectives (condition_type 1, target_type != 3);
# id 900 below is a synthetic fan objective (condition_type 3) shaped like the
# real ones (e.g. id 56/57/58 in master.mdb) to prove it is ignored. Ids
# 40001/40004 mirror real MANT-only rows (condition_type 7/9) to prove they're
# ignored gracefully.
RACE_OBJECTIVE_TURN_12 = {
    "id": 657, "race_set_id": 1051, "scenario_group_id": 100, "target_type": 1,
    "sort_id": 1, "turn": 12, "race_type": 0, "condition_type": 1,
    "condition_id": 1102, "condition_value_1": 0, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
RACE_OBJECTIVE_TURN_23 = {
    "id": 658, "race_set_id": 1051, "scenario_group_id": 100, "target_type": 1,
    "sort_id": 2, "turn": 23, "race_type": 0, "condition_type": 1,
    "condition_id": 623, "condition_value_1": 5, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
FAN_OBJECTIVE_TURN_30 = {
    "id": 900, "race_set_id": 1051, "scenario_group_id": 100, "target_type": 1,
    "sort_id": 3, "turn": 30, "race_type": 0, "condition_type": 3,
    "condition_id": 0, "condition_value_1": 5000, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
MANT_POINT_OBJECTIVE = {
    "id": 40001, "race_set_id": 10001, "scenario_group_id": 4, "target_type": 1,
    "sort_id": 2, "turn": 24, "race_type": 0, "condition_type": 7,
    "condition_id": 0, "condition_value_1": 60, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
FINALS_TURN_74 = {
    "id": 666, "race_set_id": 1051, "scenario_group_id": 701, "target_type": 3,
    "sort_id": 10, "turn": 74, "race_type": 1, "condition_type": 1,
    "condition_id": 10001, "condition_value_1": 1, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
COPANO_RICKEY_JBC_TURN_69 = {
    "id": 763, "race_set_id": 1098, "target_type": 1, "turn": 69,
    "race_type": 4, "condition_type": 1, "condition_id": 20003,
    "condition_value_1": 3,
}


def _patch_master(monkeypatch, objectives=None, race_groups=None):
    result = {"success": True, "objectives": objectives or {}}
    if race_groups is not None:
        result["race_groups"] = race_groups
    monkeypatch.setattr(
        unity_cup.uma_data, "load_route_race_objectives",
        lambda base_dir: result,
    )


def _chara(turn, route_race_id_array=None, fans=0, vital=80, **extra):
    base = {
        "turn": turn,
        "route_race_id_array": route_race_id_array or [],
        "fans": fans,
        "vital": vital,
        "proper_ground_turf": 1,
        "proper_ground_dirt": 1,
        "proper_distance_short": 1,
        "proper_distance_mile": 1,
        "proper_distance_middle": 1,
        "proper_distance_long": 1,
    }
    base.update(extra)
    return base


# --- Objective schedule parsing --------------------------------------------

def test_objective_race_decision_at_scheduled_turn(monkeypatch, tmp_path):
    _patch_master(
        monkeypatch,
        objectives={657: RACE_OBJECTIVE_TURN_12, 658: RACE_OBJECTIVE_TURN_23, 40001: MANT_POINT_OBJECTIVE},
    )
    planner = RacePlanner(tmp_path)

    def _no_preset_racing(*_args, **_kwargs):
        raise AssertionError("Unity Cup must not use preset/extra_race_list racing")
    planner.choose = _no_preset_racing

    strategy = UnityCupStrategy(planner)
    state = {
        "data": {
            "chara_info": _chara(turn=12, route_race_id_array=[657, 658, 40001]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [{"program_id": 1102}],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 1102
    assert decision.payload["_mandatory"] is True


def test_copano_rickey_turn_69_selects_offered_jbc_variant(monkeypatch, tmp_path):
    # Real career_log_thanhtran_20260717_150057 offered one random-group JBC
    # variant (1118) beside QE2 Cup (77). condition_id 20003 is the group id,
    # so passing it directly as a program id incorrectly fell back to 77.
    _patch_master(
        monkeypatch,
        objectives={763: COPANO_RICKEY_JBC_TURN_69},
        race_groups={20003: [1026, 1112, 1115, 1118]},
    )
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)
    state = {
        "data": {
            "chara_info": _chara(turn=69, route_race_id_array=[763]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [
                {"program_id": program_id}
                for program_id in [77, 90, 113, 114, 115, 149, 1116, 1117, 1118]
            ],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 1118
    assert decision.payload["_mandatory"] is True
    assert decision.payload["_required_rank"] == 3


def test_no_objective_race_on_non_scheduled_turn_trains_instead(monkeypatch, tmp_path):
    _patch_master(monkeypatch, objectives={657: RACE_OBJECTIVE_TURN_12, 658: RACE_OBJECTIVE_TURN_23})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)

    state = {
        "data": {
            "chara_info": _chara(turn=13, route_race_id_array=[657, 658], vital=80),
            "home_info": {"command_info_array": [train_command(partners=[1]), rest_command()]},
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_mant_point_objectives_are_ignored_gracefully(monkeypatch, tmp_path):
    _patch_master(monkeypatch, objectives={40001: MANT_POINT_OBJECTIVE})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)

    schedule = strategy._ensure_route_schedule(_chara(turn=24, route_race_id_array=[40001]))

    assert schedule == {"race_turns": {}, "race_ranks": {}, "finals_turns": set()}


# --- Fan objectives are ignored --------------------------------------------

def test_low_fans_and_fan_objective_train_instead_of_racing(monkeypatch, tmp_path):
    _patch_master(monkeypatch, objectives={900: FAN_OBJECTIVE_TURN_30})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)

    state = {
        "data": {
            "chara_info": _chara(
                turn=20, route_race_id_array=[900], fans=1000,
                proper_ground_turf=7, proper_distance_short=7,
            ),
            "home_info": {"command_info_array": [race_command(), train_command(partners=[1]), rest_command()]},
            "race_condition_array": [{"program_id": 500}],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


# --- Finals (server-forced, no hardcoded program ids) -----------------------

def test_finals_turn_uses_server_listed_program(monkeypatch, tmp_path):
    _patch_master(monkeypatch, objectives={666: FINALS_TURN_74})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)

    state = {
        "data": {
            "chara_info": _chara(turn=74, route_race_id_array=[666]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [{"program_id": 9999}],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 9999
    assert decision.payload["_mandatory"] is True
    assert decision.payload["program_id"] != 2022


# --- team_race._team_race_set_id (called with a CareerRunner as its services arg) ---

def test_team_race_set_id_picks_highest_team_power(tmp_path):
    runner = CareerRunner(tmp_path)
    response = {
        "data": {
            "team_data_set": {
                "opponent_info_array": [
                    {"team_power": 100, "team_race_set_id": 301},
                    {"team_power": 250, "team_race_set_id": 807},
                    {"team_power": 150, "team_race_set_id": 403},
                ]
            }
        }
    }

    assert _team_race_set_id(runner, response, 60) == 807


def test_team_race_set_id_raises_when_undeterminable(tmp_path):
    runner = CareerRunner(tmp_path)

    with pytest.raises(RuntimeError):
        _team_race_set_id(runner, {"data": {}}, 24)


# Guard the race-group invariant against future live master-data updates. This
# is intentionally a direct database assertion: a loader fallback to the raw
# condition_id would otherwise make a newly unresolved group fail silently.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_MASTER_MDB_PATH = uma_data.configured_master_mdb_path(PROJECT_ROOT)


@pytest.mark.skipif(
    not LIVE_MASTER_MDB_PATH.is_file(),
    reason=f"live master.mdb absent: {LIVE_MASTER_MDB_PATH}",
)
def test_live_master_resolves_every_route_race_group():
    with sqlite3.connect(str(LIVE_MASTER_MDB_PATH)) as conn:
        route_group_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT condition_id FROM single_mode_route_race "
                "WHERE condition_type = 1 AND target_type != 3;"
            ).fetchall()
        }
        resolved_group_ids = {
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT race_group_id FROM single_mode_race_group "
                "WHERE race_program_id IS NOT NULL AND race_program_id != 0;"
            ).fetchall()
        }

    assert route_group_ids, "live master has no non-finals route race objectives"
    assert not (route_group_ids - resolved_group_ids), (
        "unresolved single_mode_route_race condition_ids: "
        f"{sorted(route_group_ids - resolved_group_ids)}"
    )
