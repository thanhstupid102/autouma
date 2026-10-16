import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from career_bot.scenarios.mant import MantStrategy, SUMMER_CAMP_TURNS, SUMMER_CONSERVE_TURNS
from career_bot.engine import CareerRunner


def cmd(command_id, partners, stat=10):
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": 0,
        "training_partner_array": partners,
        "params_inc_dec_info_array": [{"target_type": 1, "value": stat}],
    }


def state(turn, commands):
    return {"data": {"chara_info": {"turn": turn}, "home_info": {"command_info_array": commands}}}


def race_cmd():
    return {"command_type": 4, "command_id": 401, "is_enable": 1}


def check_first_24_turns_click_each_group_card_once():
    strategy = MantStrategy()
    chara = {
        "turn": 1,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [],
    }
    training = [cmd(101, [1], 5), cmd(102, [6], 50)]

    assert strategy._early_group_card_command(training, chara, 1, {}) is None
    first = strategy._early_group_card_command(training, chara, 1, {"two_pal_deck": True})
    assert first["training_partner_array"] == [6]
    strategy._mark_early_group_card_command(first, chara)

    second = strategy._early_group_card_command(training, {**chara, "turn": 2}, 2, {"two_pal_deck": True})
    assert second["training_partner_array"] == [1]
    strategy._mark_early_group_card_command(second, {**chara, "turn": 2})

    assert strategy._early_group_card_command(training, {**chara, "turn": 3}, 3, {"two_pal_deck": True}) is None

    strategy = MantStrategy()
    strategy._mark_early_group_card_command(training[1], chara)
    assert strategy._early_group_card_command(training, {**chara, "turn": 24}, 24, {"two_pal_deck": True})["training_partner_array"] == [1]
    assert strategy._early_group_card_command(training, {**chara, "turn": 25}, 25, {"two_pal_deck": True}) is None


def outing_cmd():
    return {"command_type": 3, "command_id": 390, "is_enable": 1, "select_id": 0}


def check_due_outing_beats_group_click():
    strategy = MantStrategy()
    training = cmd(101, [6], 5)
    outing = outing_cmd()
    chara = {
        "turn": 18,
        "vital": 100,
        "motivation": 5,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [{
            "target_id": 1,
            "group_outing_info_array": [{"chara_id": 1002, "is_outing": 1, "story_step": 0}],
        }],
    }
    strategy._early_group_card_clicked_slots = {1}
    picked = strategy._best_command({"home_info": {"command_info_array": [outing, training]}}, chara, {"two_pal_deck": True})
    assert picked["command_type"] == 3
    assert picked["select_id"] == 1002


def check_canonical_schedule_fallback_no_spam_no_swap():
    strategy = MantStrategy()
    chara = {
        "turn": 18,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [
            {
                "target_id": 1,
                "group_outing_info_array": [
                    {"chara_id": 1002, "is_outing": 0, "story_step": 0},
                    {"chara_id": 1016, "is_outing": 0, "story_step": 0},
                    {"chara_id": 1030, "is_outing": 1, "story_step": 0},
                ],
            },
            {
                "target_id": 6,
                "group_outing_info_array": [
                    {"chara_id": 1017, "is_outing": 1, "story_step": 0},
                    {"chara_id": 1003, "is_outing": 0, "story_step": 0},
                ],
            },
        ],
    }
    assert strategy._scheduled_recreation([outing_cmd()], 18, chara, {}) is None
    picked = strategy._scheduled_recreation([outing_cmd()], 18, chara, {"two_pal_deck": True})
    assert picked["select_id"] == 1017

    for turn in (19, 20, 21):
        chara["turn"] = turn
        assert strategy._scheduled_recreation([outing_cmd()], turn, chara, {"two_pal_deck": True}) is None

    chara["turn"] = 26
    chara["evaluation_info_array"][1]["group_outing_info_array"][0]["story_step"] = 1
    chara["evaluation_info_array"][0]["group_outing_info_array"][0]["is_outing"] = 1
    picked = strategy._scheduled_recreation([outing_cmd()], 26, chara, {"two_pal_deck": True})
    assert picked["select_id"] == 1002


def check_recovery_prefers_unfinished_sirius_over_throne_slot():
    strategy = MantStrategy()
    chara = {
        "turn": 26,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [
            {
                "target_id": 1,
                "group_outing_info_array": [
                    {"chara_id": 1002, "is_outing": 1, "story_step": 0},
                    {"chara_id": 1016, "is_outing": 1, "story_step": 1},
                    {"chara_id": 1030, "is_outing": 1, "story_step": 0},
                ],
            },
            {
                "target_id": 6,
                "group_outing_info_array": [
                    {"chara_id": 1017, "is_outing": 1, "story_step": 1},
                    {"chara_id": 1003, "is_outing": 1, "story_step": 0},
                ],
            },
        ],
    }
    picked = strategy._scheduled_recreation([outing_cmd()], 26, chara, {"two_pal_deck": True})
    assert picked["select_id"] == 1002


def check_restart_when_no_group_outing_by_turn_18():
    strategy = MantStrategy()
    chara = {
        "turn": 18,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [
            {"target_id": 1, "group_outing_info_array": [{"chara_id": 1002, "is_outing": 0, "story_step": 0}]},
            {"target_id": 6, "group_outing_info_array": [{"chara_id": 1017, "is_outing": 0, "story_step": 0}]},
        ],
    }
    decision = strategy.next_decision({"data": {"chara_info": chara, "home_info": {"command_info_array": [outing_cmd(), cmd(101, [1], 50)]}}}, {})
    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def check_runner_force_delete_then_restart_callback():
    class Client:
        def __init__(self):
            self.calls = []

        def finish_career(self, current_turn, is_force_delete=False):
            self.calls.append((current_turn, is_force_delete))
            return {"data": {}}

    client = Client()
    runner = CareerRunner(".")
    runner._restart_callback = lambda: {"data": {"chara_info": {"turn": 1}}}
    runner._run_restart_count = 0
    state = runner._restart_career(client, MantStrategy(), {}, 18, "no outing")
    assert client.calls == [(18, True)]
    assert state["data"]["chara_info"]["turn"] == 1


def check_runner_stop_after_sp_dump_skips_finish_submit():
    class Client:
        def __init__(self):
            self.calls = []

        def finish_career(self, current_turn, is_force_delete=False):
            self.calls.append((current_turn, is_force_delete))
            return {"data": {}}

    client = Client()
    runner = CareerRunner(".")
    runner.stop_after_sp_dump = True
    runner.skill_buyer.recover_after_error = False
    calls = []
    runner._drain_events = lambda client, strategy, state, limit=50: state

    def buy_skills(client, state, preset, force):
        calls.append(("buy", force))
        return {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    runner._buy_skills = buy_skills
    runner._finish_career_flow(client, MantStrategy(), {"data": {"chara_info": {"turn": 78, "skill_point": 120}}}, {}, 78)
    assert calls == [("buy", True)]
    assert client.calls == []
    assert runner._should_stop()
    assert runner.snapshot()["last_action"] == "sp dump stop"


def check_group_cards_ignored_for_bond_after_once_clicked():
    strategy = MantStrategy()
    chara = {
        "turn": 10,
        "support_card_array": [
            {"support_card_id": 30081, "position": 1},
            {"support_card_id": 30067, "position": 6},
        ],
        "evaluation_info_array": [
            {"target_id": 1, "evaluation": 0},
            {"target_id": 2, "evaluation": 0},
            {"target_id": 6, "evaluation": 0},
        ],
    }
    strategy._early_group_card_clicked_slots = {1, 6}
    group_train = cmd(101, [1, 6], 50)
    normal_train = cmd(102, [2], 5)
    assert strategy._bondable_count(group_train, chara, {}) == 2
    assert strategy._bondable_count(group_train, chara, {"two_pal_deck": True}) == 0
    assert strategy._bondable_count(normal_train, chara) == 1
    assert strategy._pick_scored_training([group_train, normal_train], {}, chara, {"two_pal_deck": True}, 10)[1] is normal_train


def check_slot_6_has_no_pal_bonus():
    strategy = MantStrategy()
    chara = {
        "turn": 10,
        "support_card_array": [],
        "evaluation_info_array": [
            {"target_id": 5, "evaluation": 0},
            {"target_id": 6, "evaluation": 0},
        ],
    }
    assert strategy._score_command(cmd(101, [5], 10), {}, chara, {}) == strategy._score_command(cmd(101, [6], 10), {}, chara, {})


def check_summer_and_target_caps():
    assert SUMMER_CAMP_TURNS == {37, 38, 39, 40, 61, 62, 63, 64}
    assert SUMMER_CONSERVE_TURNS == {36, 60}

    strategy = MantStrategy()
    training = cmd(101, [], 100)
    preset = {
        "expect_attribute": [1000, 1000, 1000, 1000, 1000],
        "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
        "stat_balance": False,
    }
    score_84 = strategy._score_command(training, {}, {"turn": 30, "speed": 840}, preset)
    score_94 = strategy._score_command(training, {}, {"turn": 30, "speed": 940}, preset)
    score_96 = strategy._score_command(training, {}, {"turn": 30, "speed": 960}, preset)
    score_99 = strategy._score_command(training, {}, {"turn": 30, "speed": 990}, preset)
    score_101 = strategy._score_command(training, {}, {"turn": 30, "speed": 1010}, preset)
    assert score_84 > score_94 > score_96 > 0
    assert score_96 == score_99
    assert score_101 == 0

    summer_recreation = {"command_type": 3, "command_id": 301, "is_enable": 1}
    summer_rainbow = cmd(101, [1], 30)
    summer_state = state(37, [summer_recreation, summer_rainbow])
    summer_state["data"]["chara_info"].update({"vital": 40, "motivation": 5, "evaluation_info_array": [{"target_id": 1, "evaluation": 80}]})
    summer_state["data"]["free_data_set"] = {"user_item_info_array": [{"item_id": 2001, "num": 1}]}
    assert strategy.next_decision(summer_state, {}).payload["command_type"] == 1

    summer_state["data"]["free_data_set"] = {"user_item_info_array": []}
    assert strategy.next_decision(summer_state, {}).payload["command_type"] == 3


def check_sirius_throne_schedule_picks_due_available_outing():
    strategy = MantStrategy()
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1, "select_id": 0}
    chara = {
        "turn": 18,
        "support_card_array": [{"support_card_id": 30081, "position": 1}],
        "evaluation_info_array": [{
            "target_id": 1,
            "group_outing_info_array": [{"chara_id": 1002, "is_outing": 1, "story_step": 0}],
        }],
    }

    assert strategy._scheduled_recreation([outing], 18, chara, {}) is None
    picked = strategy._scheduled_recreation([outing], 18, chara, {"two_pal_deck": True})
    assert picked["command_id"] == 390
    assert picked["select_id"] == 1002


def check_captured_late_outing_select_ids():
    plan = {step["turn"]: step["select_id"] for step in MantStrategy()._outing_plan()}
    assert plan[51] == 1017
    assert plan[58] == 1001
    assert plan[59] == 1017


def check_auto_races_skip_summer_camp_but_user_scheduled_and_forced_races_run():
    class Planner:
        def __init__(self, wanted=None):
            self.base_dir = None
            self.program = {2118: {"race_instance_id": 110201, "name": "Japan Dirt Derby"}}
            self.wanted = wanted or []

        def forced_program(self, _state):
            return 0

        def choose(self, _state, _preset):
            return 2118

        def wanted_programs(self, _preset, _turn=None):
            return self.wanted

        def label(self, program_id):
            return str(program_id)

    for turn in sorted(SUMMER_CAMP_TURNS):
        strategy = MantStrategy(Planner())
        decision = strategy.next_decision(state(turn, [race_cmd(), cmd(101, [], 10)]), {})
        assert decision.action == "command"

        strategy = MantStrategy(Planner([2118]))
        decision = strategy.next_decision(state(turn, [race_cmd(), cmd(101, [], 10)]), {})
        assert decision.action == "race"

        strategy.race_planner.forced_program = lambda _state: 2118
        decision = strategy.next_decision(state(turn, [race_cmd()]), {})
        assert decision.action == "race"


if __name__ == "__main__":
    check_first_24_turns_click_each_group_card_once()
    check_due_outing_beats_group_click()
    check_canonical_schedule_fallback_no_spam_no_swap()
    check_recovery_prefers_unfinished_sirius_over_throne_slot()
    check_restart_when_no_group_outing_by_turn_18()
    check_runner_force_delete_then_restart_callback()
    check_runner_stop_after_sp_dump_skips_finish_submit()
    check_group_cards_ignored_for_bond_after_once_clicked()
    check_slot_6_has_no_pal_bonus()
    check_summer_and_target_caps()
    check_sirius_throne_schedule_picks_due_available_outing()
    check_captured_late_outing_select_ids()
    check_auto_races_skip_summer_camp_but_user_scheduled_and_forced_races_run()
    print("sirius-throne early self-check ok")
