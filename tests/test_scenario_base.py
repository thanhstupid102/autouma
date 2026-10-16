from career_bot.scenarios.base import (
    ScenarioStrategy,
    TRAINING_COMMANDS,
    TRAINING_NAMES,
)


def _chara(turn=10, **extra):
    base = {"turn": turn, "playing_state": 1}
    base.update(extra)
    return base


def test_finish_common_decision():
    s = ScenarioStrategy()
    d = s._finish_common_decision({"single_mode_finish_common": {}}, _chara(turn=78))
    assert d.action == "finish" and d.payload == {"current_turn": 78}
    assert s._finish_common_decision({}, _chara()) is None


def test_career_end_decision_reason_is_overridable():
    s = ScenarioStrategy()
    assert s._career_end_decision(_chara(state=3)).reason == "ready to finish"
    assert s._career_end_decision(_chara(state=3), reason="finished").reason == "finished"
    assert s._career_end_decision(_chara()) is None


def test_event_decision_single_choice_and_multi_choice():
    s = ScenarioStrategy()
    single = {"event_id": 5, "chara_id": 1, "event_contents_info": {"choice_array": [{}]}}
    d = s._event_decision({"unchecked_event_array": [single]}, _chara(turn=3))
    assert d.action == "event"
    assert d.payload == {"event_id": 5, "chara_id": 1, "choice_number": 0, "current_turn": 3}
    multi = {"event_id": 6, "event_contents_info": {"choice_array": [{}, {}]}}
    d = s._event_decision({"unchecked_event_array": [multi]}, _chara(turn=4))
    assert d.payload["_event"] is multi and d.payload["_current_turn"] == 4


def test_race_state_decision_states():
    s = ScenarioStrategy()
    assert s._race_state_decision({}, _chara(playing_state=3)).action == "race_progress"
    assert s._race_state_decision({}, _chara(playing_state=5)).action == "finish"
    race = {"race_start_info": {"program_id": 123}}
    assert s._race_state_decision(race, _chara(playing_state=2)).action == "race_progress"
    assert s._race_state_decision(race, _chara(playing_state=1)) is None
    assert s._race_state_decision({}, _chara(playing_state=2)) is None


def test_capability_defaults():
    s = ScenarioStrategy()
    assert s.handles_shop_items is False
    assert s.verbose_response_log is False
    assert s.extra_playing_states == frozenset()
    assert s.extra_action_handlers() == {}


def test_base_has_no_sirius_throne_knowledge():
    # The Sirius/Throne two-pal-deck strat only works well in MANT: the base
    # hook must stay neutral even when the preset carries two_pal_deck=True.
    import career_bot.scenarios.base as base

    s = ScenarioStrategy()
    chara = {"support_card_array": [{"position": 1, "support_card_id": 30081}]}
    assert s._ignored_group_bond_slots(chara, 10, {"two_pal_deck": True}) == set()
    assert not hasattr(base, "TEAM_SIRIUS_SUPPORT_ID")
    assert not hasattr(ScenarioStrategy, "_group_card_slots")


def test_training_constants_live_in_base():
    assert TRAINING_COMMANDS[101] == 0 and TRAINING_COMMANDS[605] == 4
    assert TRAINING_NAMES == ["Speed", "Stamina", "Power", "Guts", "Wit"]


def test_scoring_mixin_is_reusable_without_mant():
    from career_bot.scenarios.base import ScenarioStrategy
    from career_bot.scenarios.scoring import TrainingScoreMixin

    class Toy(TrainingScoreMixin, ScenarioStrategy):
        scenario_id = 99

    s = Toy()
    command = {
        "command_id": 101,
        "training_partner_array": [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": 10}],
        "failure_rate": 0,
    }
    score = s._score_command(command, {}, {"turn": 10, "vital": 100, "speed": 100}, {})
    assert score > 0


def test_scoring_mixin_failure_penalty_uses_doubled_coefficient():
    from career_bot.scenarios.base import ScenarioStrategy
    from career_bot.scenarios.scoring import TrainingScoreMixin

    class Toy(TrainingScoreMixin, ScenarioStrategy):
        scenario_id = 99

    s = Toy()
    command = {
        "command_id": 101,
        "training_partner_array": [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": 10}],
        "failure_rate": 10,
    }

    score = s._score_command(command, {}, {"turn": 10, "vital": 100, "speed": 100}, {})

    assert round(score, 6) == 0.06


def test_scoring_mixin_failure_penalty_denominator_is_configurable():
    from career_bot.scenarios.base import ScenarioStrategy
    from career_bot.scenarios.scoring import TrainingScoreMixin

    class Toy(TrainingScoreMixin, ScenarioStrategy):
        scenario_id = 99

    s = Toy()
    command = {
        "command_id": 101,
        "training_partner_array": [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": 10}],
        "failure_rate": 10,
    }

    score = s._score_command(command, {}, {"turn": 10, "vital": 100, "speed": 100}, {"failure_penalty_denominator": 50})

    assert round(score, 6) == 0.08


def test_mant_strategy_uses_scoring_mixin():
    from career_bot.scenarios.mant import MantStrategy
    from career_bot.scenarios.scoring import TrainingScoreMixin

    assert issubclass(MantStrategy, TrainingScoreMixin)
    assert MantStrategy.SUMMER_CAMP_TURNS == {37, 38, 39, 40, 61, 62, 63, 64}


def test_scenario_capability_declarations():
    from career_bot.scenarios.mant import MantStrategy
    from career_bot.scenarios.unity_cup import UnityCupStrategy

    assert MantStrategy.handles_shop_items is True
    assert MantStrategy.verbose_response_log is False
    assert MantStrategy.extra_playing_states == frozenset()

    assert UnityCupStrategy.handles_shop_items is False
    assert UnityCupStrategy.verbose_response_log is True
    assert UnityCupStrategy.extra_playing_states == frozenset({7, 8, 9})


def test_mant_exhausted_forced_race_idles_but_normal_turn_still_trains(tmp_path):
    from career_bot.planning.races import RacePlanner
    from career_bot.scenarios.mant import MantStrategy

    planner = RacePlanner(tmp_path)
    planner.reject(28, 198)
    planner.reject(28, 199)
    strategy = MantStrategy(planner)
    forced_state = {
        "data": {
            "chara_info": {"turn": 28, "vital": 100, "motivation": 3},
            "home_info": {
                "command_info_array": [
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                ]
            },
            "race_condition_array": [
                {"program_id": 198},
                {"program_id": 199},
            ],
        }
    }
    normal_state = {
        "data": {
            "chara_info": {"turn": 29, "vital": 100, "motivation": 3},
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 10},
                        ],
                    },
                ]
            },
        }
    }

    exhausted = strategy.next_decision(forced_state, {})
    normal = strategy.next_decision(normal_state, {})

    assert exhausted.action == "idle"
    assert exhausted.reason == (
        "forced race turn 28: server rejected every offered program"
    )
    assert normal.action == "command"
    assert normal.payload["command_id"] == 101


def test_command_stat_gain_module_helper_matches_item_manager():
    from career_bot.scenarios.mant.items import MantItemManager
    from career_bot.scenarios.base import command_stat_gain

    samples = [
        {"params_inc_dec_info_array": [{"target_type": 1, "value": 12}, {"target_type": 5, "value": 3}, {"target_type": 10, "value": -20}]},
        {"params_inc_dec_info_array": [], "speed": 5, "stamina": 2},
        {"params_inc_dec_info_array": [{"target_type": 30, "value": 9}]},
        {},
    ]
    manager = MantItemManager()
    for cmd in samples:
        assert command_stat_gain(cmd) == manager._command_stat_gain(cmd)
