from pathlib import Path

from career_bot.planning.races import RacePlanner
from career_bot.scenarios.unity_cup import UnityCupStrategy
from career_bot.scenarios.unity_cup.strategy import UnityTrainingScore
from career_bot.bot_config import UNITY_CONFIG_KEY


def state(
    turn=1,
    vital=80,
    commands=None,
    evaluations=None,
    playing_state=1,
    motivation=5,
    support_cards=None,
    chara_effects=None,
    team_evaluations=None,
    team_commands=None,
    speed=0,
    stamina=0,
    power=0,
    guts=0,
    wiz=0,
    max_vital=None,
):
    chara_info = {
        "turn": turn,
        "vital": vital,
        "playing_state": playing_state,
        "motivation": motivation,
        "speed": speed,
        "stamina": stamina,
        "power": power,
        "guts": guts,
        "wiz": wiz,
        "evaluation_info_array": evaluations or [],
        "support_card_array": support_cards or [],
        "chara_effect_id_array": chara_effects or [],
    }
    if max_vital is not None:
        chara_info["max_vital"] = max_vital
    return {
        "data": {
            "chara_info": chara_info,
            "home_info": {"command_info_array": commands or []},
            "team_data_set": {
                "evaluation_info_array": team_evaluations or [],
                "command_info_array": team_commands or [],
            },
        }
    }


def train(command_id, gain=0, partners=None, failure_rate=0, soul_partners=None, sp_soul_partners=None):
    cmd = {
        "command_type": 1,
        "command_id": command_id,
        "command_group_id": command_id,
        "is_enable": 1,
        "failure_rate": failure_rate,
        "training_partner_array": partners or [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": gain}],
    }
    if soul_partners is not None:
        cmd["soul_event_partner_array"] = soul_partners
    if sp_soul_partners is not None:
        cmd["sp_soul_event_partner_array"] = sp_soul_partners
    return cmd


def rest():
    return {"command_type": 7, "command_id": 701, "command_group_id": 701, "is_enable": 1}


def recreation():
    return {"command_type": 3, "command_id": 301, "command_group_id": 301, "is_enable": 1}


def medic():
    return {"command_type": 8, "command_id": 801, "command_group_id": 801, "is_enable": 1}


def support(position, support_card_id):
    return {"position": position, "support_card_id": support_card_id}


def bond(target_id, value):
    return {"target_id": target_id, "evaluation": value}


def soul(target_id, threshold_id, soul_state=0):
    return {"target_id": target_id, "soul_threshold_id": threshold_id, "soul_event_state": soul_state}


def member_soul(target_id, threshold_id, soul_state=0, member_state=1):
    row = soul(target_id, threshold_id, soul_state)
    row["member_state"] = member_state
    return row


def team_train(command_id, guide_partners=None, soul_partners=None, sp_soul_partners=None):
    return {
        "command_id": command_id,
        "guide_event_partner_array": guide_partners or [],
        "soul_event_partner_array": soul_partners or [],
        "sp_soul_event_partner_array": sp_soul_partners or [],
    }


def picked_command_id(decision):
    assert decision.action == "command"
    return decision.payload["command_id"] or decision.payload["command_group_id"]


def scored_training(command_id, souls=None, team_command=None, turn=1, vital=80, max_vital=None, partners=None, evaluations=None, support_cards=None, **stats):
    game_state = state(
        turn=turn,
        vital=vital,
        max_vital=max_vital,
        commands=[train(command_id, partners=partners)],
        evaluations=evaluations,
        support_cards=support_cards,
        team_evaluations=souls,
        team_commands=[team_command] if team_command else None,
        **stats,
    )
    data = game_state["data"]
    command = data["home_info"]["command_info_array"][0]
    return UnityCupStrategy()._unity_score_training(command, data, data["chara_info"], {})


def score_row(command_id, score, *, is_wit=False, failure=0.0, purple=0, blue=0, bondable=0, gain=0):
    return UnityTrainingScore(
        command={"command_id": command_id},
        command_id=command_id,
        facility_idx=4 if is_wit else 0,
        is_wit=is_wit,
        score=score,
        failure=failure,
        raw_gain=gain,
        bondable_count=bondable,
        purple_count=purple,
        blue_count=blue,
        soul_count=purple + blue,
        has_wit_rainbow=False,
    )


def test_more_low_bond_supports_win_without_removed_wit_bonus():
    decision = UnityCupStrategy().next_decision(
        state(
            turn=10,
            commands=[train(105, partners=[1, 2, 3, 4]), train(106, partners=[5, 6]), rest()],
            evaluations=[bond(i, 10) for i in range(1, 7)],
        ),
        {},
    )

    assert picked_command_id(decision) == 105


def test_bond_boundaries_and_two_support_wit_base():
    two_supports = scored_training(106, partners=[1, 2], evaluations=[bond(1, 59), bond(2, 59)])
    assert two_supports.score == 3.2
    assert two_supports.bondable_count == 2

    for value, expected in ((59, 2.2), (60, 2.5), (79, 2.5)):
        scored = scored_training(106, partners=[1], evaluations=[bond(1, value)])
        assert scored.score == expected
        assert scored.bondable_count == 1


def test_known_rainbow_types_and_late_wit_replacement():
    normal = scored_training(101, partners=[1], evaluations=[bond(1, 80)], support_cards=[support(1, 10002)])
    early_wit = scored_training(106, partners=[1], evaluations=[bond(1, 80)], support_cards=[support(1, 10013)])
    late_one = scored_training(106, turn=65, partners=[1], evaluations=[bond(1, 80)], support_cards=[support(1, 10013)])
    late_two = scored_training(
        106,
        turn=65,
        partners=[1, 2],
        evaluations=[bond(1, 80), bond(2, 80)],
        support_cards=[support(1, 10013), support(2, 10013)],
    )

    assert normal.score == 1.45
    assert early_wit.score == 2.5
    assert late_one.score == 3.2
    assert late_two.score == 5.2
    assert normal.bondable_count == early_wit.bondable_count == 0


def test_high_bond_support_only_rainbows_on_matching_facility_type():
    off_type = scored_training(102, partners=[1], evaluations=[bond(1, 80)], support_cards=[support(1, 10002)])
    matching = scored_training(102, partners=[1], evaluations=[bond(1, 80)], support_cards=[support(1, 10005)])

    assert off_type.score == 0.25
    assert off_type.rainbow_count == 0
    assert matching.score == 1.45
    assert matching.rainbow_count == 1


def test_bond_uses_home_training_partners_not_team_soul_arrays():
    scored = scored_training(
        105,
        souls=[soul(1, 5, 1)],
        team_command=team_train(105, guide_partners=[6], soul_partners=[1]),
        partners=[1, 2, 6],
        evaluations=[bond(1, 10), bond(2, 10), bond(6, 10)],
    )

    assert scored.bondable_count == 3
    assert scored.white_count == 1
    assert scored.blue_count == 1
    assert scored.purple_count == 0
    assert scored.soul_count == 2


def test_training_partners_alone_do_not_count_as_souls():
    scored = scored_training(
        101,
        souls=[soul(1, 4, 0), soul(2, 5, 1)],
        partners=[1, 2],
        evaluations=[bond(1, 10), bond(2, 10)],
    )

    assert scored.bondable_count == 2
    assert scored.white_count == scored.blue_count == scored.purple_count == scored.soul_count == 0


def test_guide_array_counts_white_without_evaluation_gate():
    scored = scored_training(
        101,
        souls=[soul(10, 4, 0), soul(11, 5, 1), soul(12, 5, 0)],
        team_command=team_train(101, guide_partners=[10, 11, 12]),
    )

    assert round(scored.score, 6) == 1.575
    assert scored.white_count == 3
    assert scored.blue_count == 0
    assert scored.purple_count == 0
    assert scored.soul_count == 3


def test_facility_arrays_classify_soul_colors_without_event_state():
    scored = scored_training(
        101,
        souls=[
            soul(10, 5, 1),
            soul(11, 4, 1),
            soul(12, 4, 0),
            soul(13, 5, 0),
        ],
        team_command=team_train(101, soul_partners=[10], sp_soul_partners=[11]),
    )

    assert scored.blue_count == 1
    assert scored.purple_count == 1
    assert scored.white_count == 0
    assert scored.soul_count == 2
    assert round(scored.score, 6) == 2.7


def test_sp_soul_array_counts_purple_and_stays_facility_local():
    game_state = state(
        turn=36,
        commands=[train(101, failure_rate=4), train(102, failure_rate=4)],
        team_evaluations=[soul(10, 5, 1), soul(11, 5, 0), soul(12, 4, 0)],
        team_commands=[
            team_train(101, soul_partners=[10, 11], sp_soul_partners=[12]),
            team_train(102),
        ],
    )
    data = game_state["data"]
    speed_command, power_command = data["home_info"]["command_info_array"]

    speed = UnityCupStrategy()._unity_score_training(speed_command, data, data["chara_info"], {})
    power = UnityCupStrategy()._unity_score_training(power_command, data, data["chara_info"], {})

    assert speed.purple_count == 1
    assert speed.blue_count == 2
    assert speed.failure == 0.0
    assert power.purple_count == 0
    assert power.failure == 0.04


def test_sp_soul_array_logs_active_purple_and_zeroes_failure():
    decision = UnityCupStrategy().next_decision(
        state(
            turn=36,
            commands=[train(101, partners=[1, 2, 3], failure_rate=4), rest()],
            evaluations=[bond(1, 10), bond(2, 10), bond(3, 10)],
            team_evaluations=[soul(10, 5, 0), soul(11, 5, 0)],
            team_commands=[team_train(101, soul_partners=[10], sp_soul_partners=[11])],
        ),
        {},
    )

    assert picked_command_id(decision) == 101
    assert "0Ws, 1Bs, 1Ps, 0F" in decision.payload["_score_detail"]
    assert decision.payload["_score_debug"]["blue_count"] == 1
    assert decision.payload["_score_debug"]["purple_count"] == 1
    assert decision.payload["_score_debug"]["failure_percent"] == 0


def test_non_deck_team_members_can_have_souls_but_no_bond():
    scored = scored_training(
        101,
        souls=[soul(1010, 4, 0), soul(1020, 4, 0), soul(1030, 5, 1)],
        team_command=team_train(101, guide_partners=[1010], soul_partners=[1020], sp_soul_partners=[1030]),
        partners=[1010, 1020, 1030],
    )

    assert scored.bondable_count == 0
    assert scored.rainbow_count == 0
    assert scored.white_count == 1
    assert scored.blue_count == 1
    assert scored.purple_count == 1


def test_active_blue_soul_adds_bonus_beyond_other_training():
    decision = UnityCupStrategy().next_decision(
        state(
            turn=25,
            commands=[train(102), train(105), rest()],
            team_evaluations=[soul(12, 4, 0)],
            team_commands=[team_train(105, soul_partners=[12])],
        ),
        {},
    )

    assert picked_command_id(decision) == 105


def test_purple_soul_makes_training_failure_free():
    scored = scored_training(
        101,
        souls=[soul(10, 5, 1)],
        team_command=team_train(101, sp_soul_partners=[10]),
    )
    failed_command = dict(scored.command, failure_rate=20)
    game_state = state(
        turn=25,
        commands=[failed_command],
        team_evaluations=[soul(10, 5, 1)],
        team_commands=[team_train(101, sp_soul_partners=[10])],
    )
    data = game_state["data"]
    scored = UnityCupStrategy()._unity_score_training(failed_command, data, data["chara_info"], {})

    assert scored.failure == 0.0
    assert scored.purple_count == 1
    assert round(scored.score, 6) == 1.4


def test_failure_penalty_uses_doubled_coefficient():
    game_state = state(turn=25, commands=[train(101, failure_rate=20)])
    data = game_state["data"]
    command = data["home_info"]["command_info_array"][0]

    scored = UnityCupStrategy()._unity_score_training(command, data, data["chara_info"], {})

    assert scored.score == -10.0


def test_unity_training_score_uses_attached_bot_config_overrides():
    game_state = state(turn=25, commands=[train(101, failure_rate=20)])
    data = game_state["data"]
    command = data["home_info"]["command_info_array"][0]

    preset = {UNITY_CONFIG_KEY: {"failure_score_penalty": 25.0, "min_train_score": 0.0}}
    scored = UnityCupStrategy()._unity_score_training(command, data, data["chara_info"], preset)

    assert scored.score == -5.0


def test_score_detail_counts_bond_rainbow_souls_and_purple_zero_failure():
    decision = UnityCupStrategy().next_decision(
        state(
            turn=25,
            commands=[train(101, failure_rate=9, partners=[1, 2, 3, 4]), rest()],
            evaluations=[bond(1, 10), bond(2, 70), bond(3, 80), bond(4, 80)],
            support_cards=[support(3, 10002), support(4, 10002)],
            team_evaluations=[soul(10, 1, 1), soul(11, 3, 1), soul(12, 4, 0), soul(13, 5, 1)],
            team_commands=[team_train(101, guide_partners=[10, 11], soul_partners=[12], sp_soul_partners=[13])],
        ),
        {},
    )

    assert picked_command_id(decision) == 101
    assert decision.payload["_facility_label"] == "Spd"
    assert "(2B, 2RB, 2Ws, 1Bs, 1Ps, 0F)" in decision.payload["_score_detail"]
    debug = decision.payload["_score_debug"]
    assert debug["bondable_count"] == 2
    assert debug["rainbow_count"] == 2
    assert debug["white_count"] == 2
    assert debug["blue_count"] == 1
    assert debug["purple_count"] == 1
    assert debug["failure_percent"] == 0
    assert debug["tie_break"] is None


def test_evaluation_rows_and_malformed_array_ids_do_not_affect_score_or_debug_counts():
    scored = scored_training(
        101,
        souls=[
            soul(10, 1, 0),
            soul(11, 4, 2),
            soul(12, 5, 99),
            {"target_id": 13, "soul_threshold_id": 5},
            {"target_id": 14, "soul_threshold_id": 4, "soul_event_state": "bad"},
            member_soul(15, 4, 0, member_state=0),
            {"target_id": 16, "soul_threshold_id": "nope", "soul_event_state": 0},
            {"target_id": 17, "soul_threshold_id": 4.5, "soul_event_state": 0},
            {"target_id": 0, "soul_threshold_id": 4, "soul_event_state": 0},
        ],
        team_command=team_train(
            101,
            guide_partners=[0, -1, None, "bad", 4.5, True],
            soul_partners=[0, -1, None, "bad", 4.5, True],
            sp_soul_partners=[0, -1, None, "bad", 4.5, True],
        ),
    )

    assert scored.score == 0.0
    assert scored.white_count == 0
    assert scored.blue_count == 0
    assert scored.purple_count == 0
    assert scored.soul_count == 0


def test_guide_array_counts_white_without_member_state_filter():
    scored = scored_training(
        101,
        souls=[member_soul(10, 5, 1, member_state=0), soul(11, 5, 1)],
        team_command=team_train(101, guide_partners=[10, 11]),
    )

    assert scored.white_count == 2
    assert scored.soul_count == 2


def test_normal_cap_exact_boundaries():
    expected = {1199: 1.45, 1200: 1.45 / 1.5, 1249: 1.45 / 1.5, 1250: 1.45 / 2.0}
    for current, score in expected.items():
        scored = scored_training(
            101,
            partners=[1],
            evaluations=[bond(1, 80)],
            support_cards=[support(1, 10002)],
            speed=current,
        )
        assert scored.score == score


def test_wit_cap_exact_boundaries():
    expected = {1199: 2.5, 1200: 2.5 / 1.25, 1279: 2.5 / 1.25, 1280: 2.5 / 2.0}
    for current, score in expected.items():
        scored = scored_training(
            106,
            partners=[1],
            evaluations=[bond(1, 80)],
            support_cards=[support(1, 10013)],
            wiz=current,
        )
        assert scored.score == score


def test_speed_power_stamina_and_wit_blue_purple_bonus_tuning():
    speed = scored_training(101, [soul(10, 4, 0), soul(11, 5, 1)], team_train(101, soul_partners=[10], sp_soul_partners=[11]))
    power = scored_training(102, [soul(10, 4, 0), soul(11, 5, 1)], team_train(102, soul_partners=[10], sp_soul_partners=[11]))
    stamina = scored_training(
        105,
        [soul(10, 4, 0), soul(11, 5, 1), soul(12, 4, 0)],
        team_train(105, soul_partners=[10, 12], sp_soul_partners=[11]),
    )
    wit = scored_training(
        106,
        [soul(10, 4, 0), soul(11, 5, 1), soul(12, 4, 0)],
        team_train(106, soul_partners=[10, 12], sp_soul_partners=[11]),
    )

    assert round(speed.score, 6) == 2.7
    assert round(power.score, 6) == 3.0
    assert round(stamina.score, 6) == 3.3
    assert round(wit.score, 6) == 4.5


def test_wit_blue_purple_bonus_and_stack_step_are_configurable():
    game_state = state(
        commands=[train(106)],
        team_evaluations=[soul(10, 4, 0), soul(11, 5, 1), soul(12, 4, 0)],
        team_commands=[team_train(106, soul_partners=[10, 12], sp_soul_partners=[11])],
    )
    data = game_state["data"]
    command = data["home_info"]["command_info_array"][0]

    scored = UnityCupStrategy()._unity_score_training(
        command,
        data,
        data["chara_info"],
        {UNITY_CONFIG_KEY: {"wit_blue_purple_soul_bonus": 0.5, "wit_blue_purple_soul_stack_bonus_step": 0.1}},
    )

    assert round(scored.score, 6) == 6.5


def test_guts_blue_purple_souls_use_small_base_with_stack_bonus():
    guts = scored_training(
        103,
        [soul(10, 4, 0), soul(11, 5, 1), soul(12, 4, 0)],
        team_train(103, soul_partners=[10, 12], sp_soul_partners=[11]),
    )

    assert round(guts.score, 6) == 3.8


def test_wit_vitality_floor_percent_turn_buckets_and_fallbacks():
    souls = [soul(10, 5, 1)]
    team_command = team_train(106, sp_soul_partners=[10])
    vital_by_percent = {97: 194, 98: 196, 99: 198, 100: 200}

    early = [round(scored_training(106, souls, team_command, turn=24, vital=vital_by_percent[p], max_vital=200).score, 2) for p in (97, 98, 99, 100)]
    late = [round(scored_training(106, souls, team_command, turn=25, vital=vital_by_percent[p], max_vital=200).score, 2) for p in (97, 98, 99, 100)]

    assert early == [2.5, 2.2, 2.1, 2.0]
    assert late == [2.5, 2.15, 2.0, 1.85]
    assert round(scored_training(106, souls, team_command, vital=99).score, 2) == 2.1
    assert round(scored_training(106, souls, team_command, vital=99, max_vital=0).score, 2) == 2.1


def test_low_energy_purple_score_above_three_trains_before_rest():
    strategy = UnityCupStrategy()
    decision = strategy.next_decision(
        state(
            turn=25,
            vital=20,
            commands=[train(105), rest()],
            team_evaluations=[soul(10, 5, 1), soul(11, 5, 1), soul(12, 5, 1)],
            team_commands=[team_train(105, sp_soul_partners=[10, 11, 12])],
        ),
        {},
    )

    assert picked_command_id(decision) == 105


def test_low_energy_safe_wit_score_and_failure_boundaries():
    strategy = UnityCupStrategy()
    rest_command = rest()

    for turn, score, failure, expected in (
        (23, 2.19, 0.0, 701),
        (23, 2.2, 0.0, 106),
        (24, 3.69, 0.0, 701),
        (24, 3.7, 0.0, 106),
        (24, 4.5, 0.10, 701),
    ):
        scores = [score_row(106, score, is_wit=True, failure=failure)]
        result = strategy._unity_low_energy_command(scores, rest_command, None, turn, 40, 5)
        assert result is (rest_command if expected == 701 else scores[0].command)


def test_low_energy_safe_wit_threshold_is_configurable():
    strategy = UnityCupStrategy()
    rest_command = rest()
    scores = [score_row(106, 2.0, is_wit=True, failure=0.0)]
    preset = {UNITY_CONFIG_KEY: {"safe_wit_score_early": 2.0}}

    result = strategy._unity_low_energy_command(scores, rest_command, None, 23, 40, 5, preset)

    assert result is scores[0].command


def test_low_energy_rests_without_purple_or_acceptable_wit():
    decision = UnityCupStrategy().next_decision(
        state(turn=25, vital=40, commands=[train(106, failure_rate=0), train(101, gain=99), rest()]),
        {},
    )

    assert picked_command_id(decision) == 701


def test_score_below_one_does_not_train_enabled_facility():
    disabled_rest = {"command_type": 7, "command_id": 701, "command_group_id": 701, "is_enable": 0}
    decision = UnityCupStrategy().next_decision(
        state(
            turn=40,
            vital=0,
            commands=[train(605, partners=[1], failure_rate=81), recreation(), disabled_rest],
            evaluations=[bond(1, 80)],
            support_cards=[support(1, 10013)],
        ),
        {},
    )

    assert picked_command_id(decision) == 301


def test_recreation_wins_when_wit_is_below_safe_threshold():
    bad_turn = UnityCupStrategy().next_decision(
        state(turn=25, motivation=2, commands=[train(101, partners=[1]), recreation(), rest()], evaluations=[bond(1, 10)]),
        {},
    )
    wit_edge = UnityCupStrategy().next_decision(
        state(
            turn=25,
            motivation=2,
            commands=[train(105, partners=[1, 2, 3, 4], failure_rate=50), train(106, partners=[5], failure_rate=9), recreation(), rest()],
            evaluations=[bond(i, 10) for i in range(1, 6)],
        ),
        {},
    )

    assert picked_command_id(bad_turn) == 301
    assert picked_command_id(wit_edge) == 301


def test_medic_is_deferred_before_summer_windows():
    decision = UnityCupStrategy().next_decision(
        state(turn=25, commands=[train(101), medic(), rest()], chara_effects=[5]),
        {},
    )

    assert picked_command_id(decision) != 801


def test_summer_bad_status_prefers_rest():
    decision = UnityCupStrategy().next_decision(
        state(turn=37, commands=[train(101), medic(), rest()], chara_effects=[5]),
        {},
    )

    assert picked_command_id(decision) == 701


def test_after_summer_low_energy_wit_requires_score_above_six():
    blocked = UnityCupStrategy().next_decision(
        state(
            turn=65,
            vital=20,
            commands=[train(106, partners=[1, 2, 3, 4, 5, 6], failure_rate=2.4), rest()],
            evaluations=[bond(i, 10) for i in range(1, 7)],
        ),
        {},
    )
    allowed = UnityCupStrategy().next_decision(
        state(
            turn=65,
            vital=20,
            commands=[train(106, partners=[1, 2, 3, 4, 5, 6], failure_rate=2.3), rest()],
            evaluations=[bond(i, 10) for i in range(1, 7)],
        ),
        {},
    )

    assert picked_command_id(blocked) == 701
    assert picked_command_id(allowed) == 106


def test_final_train_turns_use_safe_non_wit_or_wit_fallback():
    safe_non_wit = UnityCupStrategy().next_decision(
        state(
            turn=73,
            commands=[train(101, partners=[1, 2, 3, 4, 5, 6], failure_rate=10), train(106, partners=[1], failure_rate=0), rest()],
            evaluations=[bond(i, 10) for i in range(1, 7)],
        ),
        {},
    )
    wit_fallback = UnityCupStrategy().next_decision(
        state(
            turn=73,
            commands=[train(101, partners=[1, 2, 3, 4, 5, 6], failure_rate=11), train(106, partners=[1], failure_rate=0), rest()],
            evaluations=[bond(i, 10) for i in range(1, 7)],
        ),
        {},
    )

    assert picked_command_id(safe_non_wit) == 101
    assert picked_command_id(wit_fallback) == 106


def test_near_tie_gap_boundaries_and_safe_non_wit_rule():
    strategy = UnityCupStrategy()
    wit = score_row(106, 10.0, is_wit=True)

    assert strategy._unity_pick_best_training([wit, score_row(101, 9.51)], 1).command_id == 101
    assert strategy._unity_pick_best_training([wit, score_row(101, 9.50)], 1).command_id == 101
    assert strategy._unity_pick_best_training([wit, score_row(101, 9.49)], 1).command_id == 106
    assert strategy._unity_pick_best_training([wit, score_row(101, 9.50, failure=0.10)], 1).command_id == 101
    assert strategy._unity_pick_best_training([wit, score_row(101, 9.50, failure=0.101)], 1).command_id == 106


def test_near_tie_only_considers_raw_top_two():
    strategy = UnityCupStrategy()
    leader = score_row(106, 10.0, is_wit=True)
    second = score_row(101, 9.6, failure=0.11)
    metadata_rich_third = score_row(102, 9.5, purple=9, blue=9, bondable=9, gain=999)

    assert strategy._unity_pick_best_training([metadata_rich_third, second, leader], 1) is leader
    assert strategy._unity_pick_best_training([], 1) is None
    assert strategy._unity_pick_best_training([second], 1) is second


def test_score_detail_includes_tie_break_only_for_near_tie_selection_branch():
    tie = UnityCupStrategy().next_decision(
        state(
            turn=25,
            commands=[train(101, soul_partners=[10]), train(106), rest()],
            team_evaluations=[soul(10, 4, 0)],
            team_commands=[team_train(101, soul_partners=[10])],
        ),
        {},
    )
    clear_gap = UnityCupStrategy().next_decision(
        state(
            turn=25,
            commands=[train(101, partners=[1, 2]), train(106), rest()],
            evaluations=[bond(1, 10), bond(2, 10)],
        ),
        {},
    )

    assert picked_command_id(tie) == 101
    assert "TB w/ Wit: 1.2" in tie.payload["_score_detail"]
    assert tie.payload["_score_debug"]["tie_break"] == {"facility": "Wit", "score": 1.2}
    assert picked_command_id(clear_gap) == 101
    assert "TB w/" not in clear_gap.payload["_score_detail"]
    assert clear_gap.payload["_score_debug"]["tie_break"] is None


def test_non_training_unity_command_does_not_get_score_detail():
    decision = UnityCupStrategy().next_decision(state(turn=25, commands=[rest()]), {})

    assert picked_command_id(decision) == 701
    assert "_score_detail" not in decision.payload
    assert "_score_debug" not in decision.payload


def test_forced_program_becomes_mandatory_race():
    class Planner:
        base_dir = None

        def forced_program(self, _state, preferred=None):
            return 1234

        def label(self, program_id):
            return f"race {program_id}"

    decision = UnityCupStrategy(Planner()).next_decision(state(turn=12, commands=[rest()]), {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 1234
    assert decision.payload["_mandatory"] is True


def test_turn_28_forced_off_aptitude_maiden_recovery_beats_stakes_pick(monkeypatch):
    planner = RacePlanner(Path(__file__).resolve().parents[1])
    strategy = UnityCupStrategy(planner)
    monkeypatch.setattr(
        strategy.objectives,
        "race_program_candidates_for_turn",
        lambda _chara, _turn: [199],
    )
    game_state = state(
        turn=28,
        vital=0,
        motivation=1,
        commands=[{"command_type": 4, "command_id": 401, "is_enable": 1}],
    )
    game_state["data"]["chara_info"].update({
        "fans": 895,
        "chara_grade": 2,
        "proper_ground_turf": 7,
        "proper_ground_dirt": 1,
        "proper_distance_short": 2,
        "proper_distance_mile": 2,
        "proper_distance_middle": 7,
        "proper_distance_long": 7,
    })
    game_state["data"]["race_history"] = [
        {"turn": turn, "program_id": 266, "result_rank": 7 if turn == 12 else 9}
        for turn in range(12, 28)
    ]
    game_state["data"]["race_condition_array"] = [
        {"program_id": program_id}
        for program_id in [198, 199, 203, 266, 267, 268, 270, 271, 272]
    ]

    recovery = strategy.next_decision(game_state, {})

    assert recovery.action == "race"
    assert recovery.payload["program_id"] == 270
    assert recovery.reason.endswith("(maiden recovery, forced, off-aptitude)")
    assert "_mandatory" not in recovery.payload

    won_strategy = UnityCupStrategy(planner)
    won_strategy._debut_or_maiden_won = True
    monkeypatch.setattr(
        won_strategy.objectives,
        "race_program_candidates_for_turn",
        lambda _chara, _turn: [199],
    )

    forced = won_strategy.next_decision(game_state, {})

    assert forced.action == "race"
    assert forced.payload["program_id"] == 199
    assert forced.payload["_mandatory"] is True


def test_forced_race_dead_end_explains_all_programs_were_rejected(monkeypatch):
    planner = RacePlanner(Path(__file__).resolve().parents[1])
    strategy = UnityCupStrategy(planner)
    monkeypatch.setattr(
        strategy.objectives,
        "race_program_candidates_for_turn",
        lambda _chara, _turn: [199],
    )
    game_state = state(
        turn=28,
        commands=[{"command_type": 4, "command_id": 401, "is_enable": 1}],
    )
    game_state["data"]["race_condition_array"] = [
        {"program_id": 198},
        {"program_id": 199},
    ]
    planner.reject(28, 198)
    planner.reject(28, 199)

    decision = strategy.next_decision(game_state, {})

    assert decision.action == "idle"
    assert "forced race turn 28" in decision.reason
    assert "rejected every offered program" in decision.reason


def test_team_race_triggers_on_playing_state_7_once():
    # Team race fires on the server's playing_state 7 (post-training team
    # race phase), not on the turn number alone -- verified against a real
    # client capture: turn 24 goes train -> event 201029 -> ps 7 -> team_edit.
    strategy = UnityCupStrategy()
    first = strategy.next_decision(state(turn=24, playing_state=7, commands=[rest()]), {})
    strategy.mark_team_race_done(24)
    second = strategy.next_decision(state(turn=24, playing_state=7, commands=[rest()]), {})

    assert first.action == "team_race"
    assert second.action != "team_race"


def test_team_race_turn_trains_first_when_not_in_team_race_state():
    # On a team-race turn the bot must run its normal training command first;
    # jumping straight to team_edit/opponent_list before playing_state 7
    # gets a 102 from opponent_list (live failure 2026-07-08).
    decision = UnityCupStrategy().next_decision(
        state(turn=24, playing_state=1, commands=[train(101, 20, partners=[1]), rest()], evaluations=[bond(1, 10)]),
        {},
    )

    assert decision.action == "command"
    assert decision.payload["command_type"] == 1


def test_team_race_triggers_on_playing_state_7_regardless_of_turn():
    # Server truth wins over the static turn list.
    decision = UnityCupStrategy().next_decision(
        state(turn=25, playing_state=7, commands=[rest()]),
        {},
    )

    assert decision.action == "team_race"


class PresetPlanner:
    # Fake planner: no forced race, preset race 777 chosen from
    # extra_race_list via choose().
    base_dir = None

    def forced_program(self, _state, preferred=None):
        return 0

    def choose(self, _state, _preset):
        return 777

    def label(self, program_id):
        return f"race {program_id}"


def test_preset_extra_race_is_raced_when_available():
    decision = UnityCupStrategy(PresetPlanner()).next_decision(
        state(turn=20, commands=[train(101, 20), rest()]),
        {"extra_race_list": [100625]},
    )

    assert decision.action == "race"
    assert decision.payload["program_id"] == 777
    assert decision.payload.get("_mandatory") is not True


def test_team_race_beats_preset_race():
    decision = UnityCupStrategy(PresetPlanner()).next_decision(
        state(turn=24, playing_state=7, commands=[rest()]),
        {"extra_race_list": [100625]},
    )

    assert decision.action == "team_race"


def test_team_race_resume_states_8_and_9_carry_playing_state():
    # ps 8/9 = career died mid team-race; the runner resumes the remaining
    # calls based on payload playing_state.
    for ps in (7, 8, 9):
        decision = UnityCupStrategy().next_decision(
            state(turn=24, playing_state=ps, commands=[rest()]),
            {},
        )
        assert decision.action == "team_race", ps
        assert decision.payload["playing_state"] == ps


def test_unity_is_not_a_mant_subclass():
    from career_bot.scenarios.mant import MantStrategy
    from career_bot.scenarios.unity_cup import UnityCupStrategy

    strategy = UnityCupStrategy()
    assert not isinstance(strategy, MantStrategy)
    # MANT-only policy must not leak into Unity anymore:
    assert not hasattr(strategy, "_scheduled_recreation")
    assert not hasattr(strategy, "_can_rescue_training")
    assert not hasattr(strategy, "_score_command")
    # Sirius/Throne group-card tactics are MANT-only; Unity gets the neutral hook:
    assert not hasattr(strategy, "_group_card_slots")
    chara = {"support_card_array": [{"position": 1, "support_card_id": 30081}]}
    assert strategy._ignored_group_bond_slots(chara, 10, {"two_pal_deck": True}) == set()


def test_route_objectives_are_shared_not_unity_specific():
    # Most scenarios carry trainee route objectives (MANT is the exception),
    # so the layer must live at career_bot.scenarios.objectives, ready for
    # the next scenario to mix in.
    from career_bot.scenarios.objectives import RouteObjectives, RouteObjectivesMixin
    from career_bot.scenarios.unity_cup import UnityCupStrategy

    assert issubclass(UnityCupStrategy, RouteObjectivesMixin)
    assert isinstance(UnityCupStrategy().objectives, RouteObjectives)
