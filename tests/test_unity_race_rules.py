"""Unity Cup (scenario_id 2) race rule regression tests:

R1 -- once the trainee has won the Junior Make Debut (or a prior Maiden race),
Maiden races must never be selected from a user preset again.
R2 -- in non-MANT scenarios, clock items (continues) may only be used to
re-race a route objective the trainee just failed (rank worse than the route
row's required rank); non-objective races never clock.

Real single_mode_route_race rows for chara 1051 / route 54 (captured
2026-07-08, confirmed against master.mdb): id 657 (turn 12) is the Junior
Make Debut objective with condition_value_1 = 0 (no rank demanded -- losing
the debut is not a failure); id 658 (turn 23) demands top 5
(condition_value_1 = 5); id 666 (turn 74) is a finals row (target_type 3).
"""
import pytest

from career_bot.bot_config import UNITY_CONFIG_KEY
from career_bot.planning.races import RacePlanner
from career_bot.engine import CareerRunner
from career_bot.scenarios import unity_cup
from career_bot.scenarios import objectives as objectives_module
from career_bot.scenarios.objectives import RouteObjectives
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.unity_cup import UnityCupStrategy
from uma_api.errors import ApiError

from tests._helpers import race_command, rest_command, train_command


DEBUT_ROW = {
    "id": 657, "race_set_id": 1051, "scenario_group_id": 100, "target_type": 1,
    "sort_id": 1, "turn": 12, "race_type": 0, "condition_type": 1,
    "condition_id": 1102, "condition_value_1": 0, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
TOP5_ROW = {
    "id": 658, "race_set_id": 1051, "scenario_group_id": 100, "target_type": 1,
    "sort_id": 2, "turn": 23, "race_type": 0, "condition_type": 1,
    "condition_id": 623, "condition_value_1": 5, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
FINALS_ROW = {
    "id": 666, "race_set_id": 1051, "scenario_group_id": 701, "target_type": 3,
    "sort_id": 10, "turn": 74, "race_type": 1, "condition_type": 1,
    "condition_id": 10001, "condition_value_1": 1, "condition_value_2": 0,
    "determine_race": 0, "determine_race_flag": 0,
}
DEBUT_PROGRAM_ID = 1102
MAIDEN_PROGRAM_ID = 500
DIRT_SPRINT_MAIDEN_PROGRAM_ID = 501
TURF_MEDIUM_MAIDEN_PROGRAM_ID = 502
TURF_MILE_MAIDEN_PROGRAM_ID = 503
CREEK_APTITUDES = {
    "proper_ground_turf": 7,
    "proper_ground_dirt": 1,
    "proper_distance_short": 2,
    "proper_distance_mile": 2,
    "proper_distance_middle": 7,
    "proper_distance_long": 7,
}


def _patch_unity_master(monkeypatch, objectives=None):
    monkeypatch.setattr(
        unity_cup.uma_data, "load_route_race_objectives",
        lambda base_dir: {"success": True, "objectives": objectives or {}},
    )


def _chara(turn, route_race_id_array=None, fans=0, vital=80, **extra):
    base = {
        "turn": turn,
        "route_race_id_array": route_race_id_array or [],
        "fans": fans,
        "vital": vital,
        "proper_ground_turf": 7,
        "proper_ground_dirt": 7,
        "proper_distance_short": 7,
        "proper_distance_mile": 7,
        "proper_distance_middle": 7,
        "proper_distance_long": 7,
    }
    base.update(extra)
    return base


def _unity_strategy_for_preset(monkeypatch, tmp_path, objectives=None):
    _patch_unity_master(monkeypatch, objectives=objectives)
    planner = RacePlanner(tmp_path)
    planner.program = {
        MAIDEN_PROGRAM_ID: {"ground": 1, "distance": 1200, "name": "Junior Maiden Race", "race_instance_id": 900100},
        DIRT_SPRINT_MAIDEN_PROGRAM_ID: {"ground": 2, "distance": 1300, "name": "Junior Maiden Race", "race_instance_id": 900101},
        TURF_MEDIUM_MAIDEN_PROGRAM_ID: {"ground": 1, "distance": 2000, "name": "Junior Maiden Race", "race_instance_id": 900102},
        TURF_MILE_MAIDEN_PROGRAM_ID: {"ground": 1, "distance": 1600, "name": "Junior Maiden Race", "race_instance_id": 900103},
        DEBUT_PROGRAM_ID: {"ground": 1, "distance": 1200, "name": "Junior Make Debut", "race_instance_id": 901100},
    }
    strategy = UnityCupStrategy(planner)
    return strategy


def _preset_state(turn=20, program_ids=None, **chara_overrides):
    if program_ids is None:
        program_ids = [MAIDEN_PROGRAM_ID]
    return {
        "data": {
            "chara_info": _chara(turn=turn, **chara_overrides),
            "home_info": {"command_info_array": [race_command(), train_command(partners=[1]), rest_command()]},
            "race_condition_array": [
                {"program_id": program_id}
                for program_id in program_ids
            ],
        }
    }


def test_forced_program_accepts_ordered_candidates_and_plain_int(tmp_path):
    planner = RacePlanner(tmp_path)
    state = {
        "data": {
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [
                {"program_id": program_id}
                for program_id in [77, 90, 113, 114, 115, 149, 1116, 1117, 1118]
            ],
        }
    }

    assert planner.forced_program(state, preferred=(1026, 1112, 1115, 1118)) == 1118
    assert planner.forced_program(state, preferred=1118) == 1118
    assert planner.forced_program(state) == 77


def test_forced_program_skips_rejected_candidates_for_current_turn(tmp_path):
    planner = RacePlanner(tmp_path)
    program_ids = [198, 199, 203, 266, 267, 268, 270, 271, 272]
    state = {
        "data": {
            "chara_info": {"turn": 28},
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [
                {"program_id": program_id}
                for program_id in program_ids
            ],
        }
    }

    assert planner.forced_program(state, preferred=(199,)) == 199

    planner.reject(27, 199)
    assert planner.forced_program(state, preferred=(199,)) == 199

    planner.reject(28, 199)
    assert planner.forced_program(state, preferred=(199,)) == 198

    for program_id in program_ids:
        planner.reject(28, program_id)
    assert planner.forced_program(state, preferred=(199,)) == 0
    assert planner.forced_race_exhausted(state) is True

    normal_state = {
        "data": {
            "chara_info": {"turn": 28},
            "home_info": {
                "command_info_array": [race_command(), train_command()],
            },
            "race_condition_array": [{"program_id": 199}],
        }
    }
    assert planner.forced_race_exhausted(normal_state) is False


def test_forced_program_skips_rejected_race_start_fallback(tmp_path):
    planner = RacePlanner(tmp_path)
    state = {
        "data": {
            "chara_info": {"turn": 28},
            "home_info": {"command_info_array": [race_command()]},
            "race_start_info": {"program_id": 199},
        }
    }

    assert planner.forced_program(state) == 199
    planner.reject(28, 199)
    assert planner.forced_program(state) == 0


# --- (a)/(b) R1: preset maiden exclusion after a debut/maiden win ----------

def test_preset_excludes_maiden_when_debut_won(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 1)  # won the debut

    decision = strategy.next_decision(_preset_state(), {"extra_race_list": [MAIDEN_PROGRAM_ID]})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_preset_allows_maiden_when_debut_lost_and_no_maiden_won(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)  # lost the debut -- not a win

    decision = strategy.next_decision(_preset_state(), {"extra_race_list": [MAIDEN_PROGRAM_ID]})

    assert decision.action == "race"
    assert decision.payload["program_id"] == MAIDEN_PROGRAM_ID


def test_preset_excludes_maiden_after_race_history_shows_debut_win(monkeypatch, tmp_path):
    # No live record_race_result call this run -- the win is only visible via
    # a reloaded server state's race_history (bot restarted mid-career).
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    state = _preset_state()
    state["data"]["race_history"] = [
        {"turn": 12, "program_id": DEBUT_PROGRAM_ID, "result_rank": 1},
    ]

    decision = strategy.next_decision(state, {"extra_race_list": [MAIDEN_PROGRAM_ID]})

    assert decision.action == "command"


# --- R3: maiden recovery after a lost debut -------------------------------

def test_maiden_recovery_races_maiden_after_debut_loss_without_preset(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)

    decision = strategy.next_decision(_preset_state(), {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == MAIDEN_PROGRAM_ID
    assert "_required_rank" not in decision.payload
    assert "_mandatory" not in decision.payload


def test_maiden_recovery_forced_turn_tries_another_maiden_after_rejection(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    state = _preset_state(
        program_ids=[MAIDEN_PROGRAM_ID, TURF_MEDIUM_MAIDEN_PROGRAM_ID],
    )
    state["data"]["home_info"]["command_info_array"] = [race_command()]

    first = strategy.next_decision(state, {})
    strategy.race_planner.reject(
        state["data"]["chara_info"]["turn"],
        first.payload["program_id"],
    )
    second = strategy.next_decision(state, {})

    assert first.action == "race"
    assert second.action == "race"
    assert second.payload["program_id"] != first.payload["program_id"]
    assert second.payload["program_id"] in {
        MAIDEN_PROGRAM_ID,
        TURF_MEDIUM_MAIDEN_PROGRAM_ID,
    }


def test_maiden_recovery_forced_turn_idles_after_every_program_rejected(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    turn = 20
    program_ids = [MAIDEN_PROGRAM_ID, TURF_MEDIUM_MAIDEN_PROGRAM_ID, 623]
    state = _preset_state(turn=turn, program_ids=program_ids)
    state["data"]["home_info"]["command_info_array"] = [race_command()]
    for program_id in program_ids:
        strategy.race_planner.reject(turn, program_id)
    exhaustion_checks = []
    forced_race_exhausted = strategy.race_planner.forced_race_exhausted
    strategy.race_planner.forced_race_exhausted = (
        lambda current_state: exhaustion_checks.append(current_state)
        or forced_race_exhausted(current_state)
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "idle"
    assert decision.reason == "forced race turn 20: server rejected every offered program"
    assert exhaustion_checks == [state]


def test_maiden_recovery_non_forced_turn_skips_rejected_maiden(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    turn = 20
    state = _preset_state(turn=turn, program_ids=[TURF_MEDIUM_MAIDEN_PROGRAM_ID])
    strategy.race_planner.reject(turn, TURF_MEDIUM_MAIDEN_PROGRAM_ID)

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_maiden_recovery_ignores_rejection_from_different_turn(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    turn = 20
    state = _preset_state(turn=turn, program_ids=[TURF_MEDIUM_MAIDEN_PROGRAM_ID])
    strategy.race_planner.reject(turn - 1, TURF_MEDIUM_MAIDEN_PROGRAM_ID)

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == TURF_MEDIUM_MAIDEN_PROGRAM_ID


def test_maiden_recovery_without_aptitude_data_races_preferred_maiden(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    state = _preset_state(program_ids=[TURF_MEDIUM_MAIDEN_PROGRAM_ID, MAIDEN_PROGRAM_ID])
    for aptitude_field in CREEK_APTITUDES:
        state["data"]["chara_info"].pop(aptitude_field)

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == MAIDEN_PROGRAM_ID
    assert decision.reason.endswith("(maiden recovery)")
    assert "off-aptitude" not in decision.reason


def test_maiden_recovery_missing_program_metadata_races_unknown_maiden(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy._debut_maiden_program_ids()
    strategy.race_planner.program.pop(MAIDEN_PROGRAM_ID)
    state = _preset_state(program_ids=[MAIDEN_PROGRAM_ID], **CREEK_APTITUDES)

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == MAIDEN_PROGRAM_ID


def test_maiden_recovery_prefers_known_fit_over_unknown_program_metadata(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy._debut_maiden_program_ids()
    strategy.race_planner.program.pop(MAIDEN_PROGRAM_ID)
    state = _preset_state(
        program_ids=[MAIDEN_PROGRAM_ID, TURF_MEDIUM_MAIDEN_PROGRAM_ID],
        **CREEK_APTITUDES,
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == TURF_MEDIUM_MAIDEN_PROGRAM_ID


def test_maiden_recovery_off_aptitude_trains_instead(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    state = _preset_state(
        program_ids=[DIRT_SPRINT_MAIDEN_PROGRAM_ID],
        **CREEK_APTITUDES,
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"


def test_maiden_recovery_races_surface_and_distance_fit(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    state = _preset_state(
        program_ids=[DIRT_SPRINT_MAIDEN_PROGRAM_ID, TURF_MEDIUM_MAIDEN_PROGRAM_ID],
        **CREEK_APTITUDES,
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == TURF_MEDIUM_MAIDEN_PROGRAM_ID
    assert decision.reason.endswith("(maiden recovery)")


def test_maiden_recovery_prefers_turn_objective_over_better_fit(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(
        monkeypatch,
        tmp_path,
        objectives={DEBUT_ROW["id"]: DEBUT_ROW},
    )
    state = _preset_state(
        turn=DEBUT_ROW["turn"],
        program_ids=[TURF_MEDIUM_MAIDEN_PROGRAM_ID, DEBUT_PROGRAM_ID],
        route_race_id_array=[DEBUT_ROW["id"]],
        **{**CREEK_APTITUDES, "proper_distance_short": 6},
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == DEBUT_PROGRAM_ID
    assert decision.reason.endswith("(maiden recovery)")


def test_maiden_recovery_keeps_best_fit_when_objective_not_offered(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(
        monkeypatch,
        tmp_path,
        objectives={DEBUT_ROW["id"]: DEBUT_ROW},
    )
    state = _preset_state(
        turn=DEBUT_ROW["turn"],
        program_ids=[MAIDEN_PROGRAM_ID, TURF_MEDIUM_MAIDEN_PROGRAM_ID],
        route_race_id_array=[DEBUT_ROW["id"]],
        **{**CREEK_APTITUDES, "proper_distance_short": 6},
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == TURF_MEDIUM_MAIDEN_PROGRAM_ID


def test_maiden_recovery_forced_off_aptitude_prefers_turn_objective(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(
        monkeypatch,
        tmp_path,
        objectives={DEBUT_ROW["id"]: DEBUT_ROW},
    )
    state = _preset_state(
        turn=DEBUT_ROW["turn"],
        program_ids=[TURF_MILE_MAIDEN_PROGRAM_ID, DEBUT_PROGRAM_ID],
        route_race_id_array=[DEBUT_ROW["id"]],
        proper_ground_turf=5,
        proper_ground_dirt=1,
        proper_distance_short=1,
        proper_distance_mile=5,
        proper_distance_middle=5,
        proper_distance_long=1,
    )
    state["data"]["home_info"]["command_info_array"] = [race_command()]

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == DEBUT_PROGRAM_ID
    assert decision.reason.endswith("(maiden recovery, forced, off-aptitude)")


def test_maiden_recovery_objective_does_not_bypass_gate(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(
        monkeypatch,
        tmp_path,
        objectives={DEBUT_ROW["id"]: DEBUT_ROW},
    )
    state = _preset_state(
        turn=DEBUT_ROW["turn"],
        program_ids=[DEBUT_PROGRAM_ID],
        route_race_id_array=[DEBUT_ROW["id"]],
        **CREEK_APTITUDES,
    )

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_maiden_recovery_aptitude_threshold_is_configurable(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    state = _preset_state(
        program_ids=[TURF_MILE_MAIDEN_PROGRAM_ID],
        **CREEK_APTITUDES,
    )

    default_decision = strategy.next_decision(state, {})
    lowered_decision = strategy.next_decision(
        state,
        {UNITY_CONFIG_KEY: {"maiden_recovery_min_aptitude": 2}},
    )

    assert default_decision.action == "command"
    assert lowered_decision.action == "race"
    assert lowered_decision.payload["program_id"] == TURF_MILE_MAIDEN_PROGRAM_ID


def test_maiden_recovery_stops_after_maiden_win(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(MAIDEN_PROGRAM_ID, 1)

    decision = strategy.next_decision(_preset_state(), {})

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_maiden_recovery_inert_when_race_command_disabled(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    state = _preset_state()
    state["data"]["home_info"]["command_info_array"][0] = race_command(enabled=0)

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"


def test_maiden_recovery_inert_when_no_maiden_on_offer(monkeypatch, tmp_path):
    strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    state = _preset_state()
    state["data"]["race_condition_array"] = [{"program_id": 623}]

    decision = strategy.next_decision(state, {})

    assert decision.action == "command"


def test_maiden_recovery_from_race_history_on_resume(monkeypatch, tmp_path):
    lost_strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    lost_state = _preset_state()
    lost_state["data"]["race_history"] = [
        {"turn": 12, "program_id": DEBUT_PROGRAM_ID, "result_rank": 4},
    ]

    lost_decision = lost_strategy.next_decision(lost_state, {})

    assert lost_decision.action == "race"
    assert lost_decision.payload["program_id"] == MAIDEN_PROGRAM_ID

    won_strategy = _unity_strategy_for_preset(monkeypatch, tmp_path)
    won_state = _preset_state()
    won_state["data"]["race_history"] = [
        {"turn": 12, "program_id": DEBUT_PROGRAM_ID, "result_rank": 1},
    ]

    won_decision = won_strategy.next_decision(won_state, {})

    assert won_decision.action == "command"


def test_maiden_recovery_beats_forced_objective_until_maiden_won(monkeypatch, tmp_path):
    _patch_unity_master(monkeypatch, objectives={TOP5_ROW["id"]: TOP5_ROW})
    planner = RacePlanner(tmp_path)
    planner.program = {
        MAIDEN_PROGRAM_ID: {"name": "Junior Maiden Race"},
        DEBUT_PROGRAM_ID: {"name": "Junior Make Debut"},
        623: {"name": "Route Objective Race"},
    }
    strategy = UnityCupStrategy(planner)
    strategy.record_race_result(DEBUT_PROGRAM_ID, 4)
    state = {
        "data": {
            "chara_info": _chara(turn=23, route_race_id_array=[TOP5_ROW["id"]]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [
                {"program_id": MAIDEN_PROGRAM_ID},
                {"program_id": 623},
            ],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == MAIDEN_PROGRAM_ID
    assert "_mandatory" not in decision.payload


# --- (c) required_rank_for_turn ---------------------------------------------

def test_required_rank_for_turn_reads_route_requirement(monkeypatch):
    monkeypatch.setattr(
        objectives_module.uma_data, "load_route_race_objectives",
        lambda base_dir: {"success": True, "objectives": {
            DEBUT_ROW["id"]: DEBUT_ROW, TOP5_ROW["id"]: TOP5_ROW, FINALS_ROW["id"]: FINALS_ROW,
        }},
    )
    route_obj = RouteObjectives(base_dir="fake")
    chara = {"route_race_id_array": [DEBUT_ROW["id"], TOP5_ROW["id"], FINALS_ROW["id"]]}

    assert route_obj.required_rank_for_turn(chara, 12) is None  # debut: no rank demanded
    assert route_obj.required_rank_for_turn(chara, 23) == 5     # "top 5" objective
    assert route_obj.required_rank_for_turn(chara, 74) == 1     # finals: must win


# --- (d) Unity objective payload carries _required_rank --------------------

def test_objective_race_payload_carries_required_rank(monkeypatch, tmp_path):
    _patch_unity_master(monkeypatch, objectives={TOP5_ROW["id"]: TOP5_ROW})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)
    state = {
        "data": {
            "chara_info": _chara(turn=23, route_race_id_array=[TOP5_ROW["id"]]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [{"program_id": 623}],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 623
    assert decision.payload["_mandatory"] is True
    assert decision.payload.get("_required_rank") == 5


def test_debut_objective_payload_has_no_required_rank(monkeypatch, tmp_path):
    _patch_unity_master(monkeypatch, objectives={DEBUT_ROW["id"]: DEBUT_ROW})
    planner = RacePlanner(tmp_path)
    strategy = UnityCupStrategy(planner)
    state = {
        "data": {
            "chara_info": _chara(turn=12, route_race_id_array=[DEBUT_ROW["id"]]),
            "home_info": {"command_info_array": [race_command()]},
            "race_condition_array": [{"program_id": DEBUT_PROGRAM_ID}],
        }
    }

    decision = strategy.next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload.get("_required_rank") is None


# --- (e)-(h) runner-level clock policy --------------------------------------

class FakeRaceClient:
    api_jitter = 0

    def __init__(self):
        self.calls = []
        self.continue_types = []

    def race_entry(self, program_id, current_turn, **kwargs):
        self.calls.append("race_entry")
        return {"data": {"chara_info": {"turn": current_turn}}}

    def race_start(self, is_short, current_turn):
        self.calls.append("race_start")
        return {"data": {}}

    def race_continue(self, current_turn, continue_type=1):
        self.calls.append("race_continue")
        self.continue_types.append(continue_type)
        return {"data": {}}

    def race_end(self, current_turn):
        self.calls.append("race_end")
        return {"data": {}}

    def race_out(self, current_turn):
        self.calls.append("race_out")
        return {"data": {"chara_info": {"turn": current_turn + 1}}}


def _quiet(monkeypatch):
    import career_bot.engine.runner as runner_module
    import career_bot.engine.racing as racing_module
    monkeypatch.setattr(runner_module, "dna_sleep", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "backoff_sleep", lambda *a, **k: None)
    monkeypatch.setattr(racing_module, "dna_gauss", lambda *a, **k: None)
    monkeypatch.setattr(racing_module, "dna_sleep", lambda *a, **k: None)


def _rank_sequence(runner, ranks):
    queue = list(ranks)
    runner._parse_race_rank = lambda res: queue.pop(0)


def test_non_mant_required_rank_satisfied_no_clock(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [4])
    state = {"data": {"home_info": {"available_continue_num": 0, "available_free_continue_num": 3}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": None, "_mandatory": True, "_required_rank": 5}

    runner._race(client, state, {}, payload)

    assert "race_continue" not in client.calls
    assert client.calls.count("race_start") == 1


def test_non_mant_required_rank_missed_triggers_clock_retry(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [6, 1])
    state = {"data": {"home_info": {"available_continue_num": 2, "available_free_continue_num": 2}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": None, "_mandatory": True, "_required_rank": 5}

    runner._race(client, state, {}, payload)

    assert client.calls.count("race_continue") == 1
    assert client.calls.count("race_start") == 2
    assert runner.status["clocks_used"] == 1


def test_non_mant_non_objective_race_never_clocks(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [5])
    state = {"data": {"home_info": {"available_continue_num": 0, "available_free_continue_num": 5}}}
    payload = {"program_id": MAIDEN_PROGRAM_ID, "current_turn": 20, "_strategy": None}

    runner._race(client, state, {}, payload)

    assert "race_continue" not in client.calls
    assert client.calls.count("race_start") == 1


def test_mant_force_clock_debut_regression_unchanged(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    runner.strategy = MantStrategy()
    assert runner.strategy.free_clock_retry is True
    runner.race_planner.program = {101: {"name": "Junior Make Debut"}}
    client = FakeRaceClient()
    _rank_sequence(runner, [3, 1])
    state = {"data": {"home_info": {"available_continue_num": 2, "available_free_continue_num": 2}}}
    payload = {"program_id": 101, "current_turn": 1, "_strategy": None}

    runner._race(client, state, {}, payload)

    assert client.calls.count("race_continue") == 1
    assert client.calls.count("race_start") == 2
    assert runner.status["clocks_used"] == 1


def test_paid_clock_preflight_false_skips_continue_but_finishes_race(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [6])
    runner._ensure_alarm_clock = lambda _client, _preset: False
    state = {"data": {"home_info": {"available_continue_num": 1, "available_free_continue_num": 0}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": None, "_required_rank": 5}

    runner._race(client, state, {}, payload)

    assert "race_continue" not in client.calls
    assert "race_end" in client.calls
    assert "race_out" in client.calls


def test_free_clock_never_runs_paid_preflight(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [6, 1])
    preflight_calls = []
    runner._ensure_alarm_clock = lambda _client, _preset: preflight_calls.append(1) or False
    state = {"data": {"home_info": {"available_continue_num": 1, "available_free_continue_num": 1}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": None, "_required_rank": 5}

    runner._race(client, state, {}, payload)

    assert preflight_calls == []
    assert client.continue_types == [1]


def test_race_continue_state_recovery_error_uses_recovery_path(monkeypatch, tmp_path):
    error = ApiError(201, "single_mode_team/continue", "desynced")

    class RecoveringRaceClient(FakeRaceClient):
        def race_continue(self, current_turn, continue_type=1):
            self.calls.append("race_continue")
            self.continue_types.append(continue_type)
            raise error

    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = RecoveringRaceClient()
    _rank_sequence(runner, [6])
    recovered = {"data": {"chara_info": {"turn": 24}}}
    recovery_calls = []
    runner._recover_state_error = lambda *args: recovery_calls.append(args) or recovered
    strategy = object()
    state = {"data": {"home_info": {"available_continue_num": 1, "available_free_continue_num": 1}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": strategy, "_required_rank": 5}

    result = runner._race(client, state, {}, payload)

    assert result is recovered
    assert recovery_calls == [
        (client, strategy, 23, "race_start_recovered", error),
    ]
    assert "race_end" not in client.calls
    assert not any(row["action"] == "race_clock_failed" for row in runner.status["log"])


def test_ordinary_paid_continue_rejection_is_logged_and_race_still_finishes(monkeypatch, tmp_path):
    class RejectingRaceClient(FakeRaceClient):
        def race_continue(self, current_turn, continue_type=1):
            self.calls.append("race_continue")
            self.continue_types.append(continue_type)
            raise ApiError(654, "single_mode_team/continue", "rejected")

    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = RejectingRaceClient()
    _rank_sequence(runner, [6])
    runner._ensure_alarm_clock = lambda _client, _preset: True
    state = {"data": {"home_info": {"available_continue_num": 1, "available_free_continue_num": 0}}}
    payload = {"program_id": 623, "current_turn": 23, "_strategy": None, "_required_rank": 5}

    runner._race(client, state, {}, payload)

    assert client.continue_types == [2]
    assert "race_end" in client.calls
    assert "race_out" in client.calls
    assert any("result_code=654" in row["detail"] for row in runner.status["log"])


def test_paid_continue_omitting_clock_row_forces_purchase_before_next_retry(
    monkeypatch,
    tmp_path,
):
    class PaidClockRaceClient(FakeRaceClient):
        ALARM_CLOCK_ITEM_ID = 95
        ALARM_CLOCK_CARAT_PRICE = 10

        def __init__(self):
            super().__init__()
            self.item_map = {95: 1}
            self.coin_info = {"fcoin": 20, "coin": 0}
            self.buy_calls = 0

        def race_continue(self, current_turn, continue_type=1):
            self.calls.append("race_continue")
            self.continue_types.append(continue_type)
            remaining = max(2 - len(self.continue_types), 0)
            return {
                "data": {
                    "home_info": {
                        "available_continue_num": remaining,
                        "available_free_continue_num": 0,
                    }
                }
            }

        def read_info(self):
            return {
                "data": {
                    "coin_info": {"fcoin": 20, "coin": 0},
                    "user_item": {"item_id": 95, "num": 0},
                }
            }

        def refresh_cached_account_state(self, data):
            self.coin_info = dict(data["coin_info"])
            if data.get("user_item"):
                self.item_map[95] = int(data["user_item"]["num"])

        def alarm_clock_carat_price(self):
            return 10

        def buy_alarm_clock(self, account_data=None):
            self.buy_calls += 1
            self.item_map[95] = int(self.item_map.get(95) or 0) + 1
            return {"data": {}}

    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = PaidClockRaceClient()
    _rank_sequence(runner, [6, 6, 1])
    state = {
        "data": {
            "home_info": {
                "available_continue_num": 2,
                "available_free_continue_num": 0,
            }
        }
    }
    payload = {
        "program_id": 623,
        "current_turn": 23,
        "_strategy": None,
        "_required_rank": 5,
    }

    runner._race(client, state, {}, payload)

    assert client.continue_types == [2, 2]
    assert client.buy_calls == 1


def test_race_continue_blocked_state_recovers_without_finishing_race(
    monkeypatch,
    tmp_path,
):
    error = ApiError(1503, "single_mode_team/continue", "blocked")

    class BlockedRaceClient(FakeRaceClient):
        def race_continue(self, current_turn, continue_type=1):
            self.calls.append("race_continue")
            self.continue_types.append(continue_type)
            raise error

    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = BlockedRaceClient()
    _rank_sequence(runner, [6])
    recovered = {"data": {"chara_info": {"turn": 23, "playing_state": 1}}}
    recovery_calls = []
    runner._recover_blocked_state = (
        lambda *args: recovery_calls.append(args) or recovered
    )
    state = {
        "data": {
            "home_info": {
                "available_continue_num": 1,
                "available_free_continue_num": 1,
            }
        }
    }
    payload = {
        "program_id": 623,
        "current_turn": 23,
        "_strategy": None,
        "_required_rank": 5,
    }

    result = runner._race(client, state, {}, payload)

    assert result is recovered
    assert recovery_calls == [(client, None, state)]
    assert "race_end" not in client.calls
    assert "race_out" not in client.calls
    assert any("result_code=1503" in row["detail"] for row in runner.status["log"])


def test_paid_preflight_blocked_state_recovers_without_finishing_race(
    monkeypatch,
    tmp_path,
):
    error = ApiError(102, "load/index", "blocked")
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    client = FakeRaceClient()
    _rank_sequence(runner, [6])

    def blocked_preflight(_client, _preset):
        raise error

    runner._ensure_alarm_clock = blocked_preflight
    recovered = {"data": {"chara_info": {"turn": 23, "playing_state": 1}}}
    runner._recover_blocked_state = lambda *_args: recovered
    state = {
        "data": {
            "home_info": {
                "available_continue_num": 1,
                "available_free_continue_num": 0,
            }
        }
    }
    payload = {
        "program_id": 623,
        "current_turn": 23,
        "_strategy": None,
        "_required_rank": 5,
    }

    with pytest.raises(ApiError) as caught:
        runner._race(client, state, {}, payload)

    assert caught.value is error
    assert runner._handle_turn_error(client, None, state, error) is recovered
    assert "race_continue" not in client.calls
    assert "race_end" not in client.calls
    assert "race_out" not in client.calls


def test_race_entry_208_reloads_before_bounded_rejection(tmp_path):
    class BusyRaceClient(FakeRaceClient):
        def race_entry(self, program_id, current_turn, **kwargs):
            self.calls.append("race_entry")
            raise ApiError(208, "single_mode_team/race_entry", "busy")

    runner = CareerRunner(tmp_path)
    client = BusyRaceClient()
    state = {"data": {"chara_info": {"turn": 28}}}
    runner._fresh_career_state = lambda *_args, **_kwargs: state
    payload = {
        "program_id": 199,
        "current_turn": 28,
        "_strategy": None,
    }

    for _ in range(runner._RACE_ENTRY_208_RELOAD_LIMIT):
        assert runner._race(client, state, {}, payload) is state
        assert (28, 199) not in runner.race_planner.rejected

    assert runner._race(client, state, {}, payload) is state
    assert (28, 199) in runner.race_planner.rejected


def test_race_entry_205_rejects_immediately(tmp_path):
    class RejectedRaceClient(FakeRaceClient):
        def race_entry(self, program_id, current_turn, **kwargs):
            self.calls.append("race_entry")
            raise ApiError(205, "single_mode_team/race_entry", "invalid")

    runner = CareerRunner(tmp_path)
    client = RejectedRaceClient()
    state = {"data": {"chara_info": {"turn": 28}}}
    runner._fresh_career_state = lambda *_args, **_kwargs: state
    payload = {
        "program_id": 199,
        "current_turn": 28,
        "_strategy": None,
    }

    assert runner._race(client, state, {}, payload) is state
    assert (28, 199) in runner.race_planner.rejected


# --- record_race_result wiring: runner._race must call it via self.strategy
# (not the payload["_strategy"] local) after the clock-retry loop, so the
# scenario's won-state guard (R1) actually gets fed live race results. -------

def test_race_wins_debut_records_result_on_strategy(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    runner.race_planner.program = {DEBUT_PROGRAM_ID: {"name": "Junior Make Debut"}}
    strategy = UnityCupStrategy(runner.race_planner)
    runner.strategy = strategy
    client = FakeRaceClient()
    _rank_sequence(runner, [1])
    state = {"data": {"home_info": {"available_continue_num": 0, "available_free_continue_num": 0}}}
    payload = {"program_id": DEBUT_PROGRAM_ID, "current_turn": 12, "_strategy": None}

    runner._race(client, state, {}, payload)

    assert strategy._debut_or_maiden_won is True


def test_race_loses_debut_does_not_record_win_on_strategy(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    runner = CareerRunner(tmp_path)
    runner.race_planner.program = {DEBUT_PROGRAM_ID: {"name": "Junior Make Debut"}}
    strategy = UnityCupStrategy(runner.race_planner)
    runner.strategy = strategy
    client = FakeRaceClient()
    _rank_sequence(runner, [4])
    state = {"data": {"home_info": {"available_continue_num": 0, "available_free_continue_num": 0}}}
    payload = {"program_id": DEBUT_PROGRAM_ID, "current_turn": 12, "_strategy": None}

    runner._race(client, state, {}, payload)

    assert strategy._debut_or_maiden_won is False
