from career_bot.scenarios.mant.items import MantItemManager
from career_bot.scenarios.mant import MantStrategy


def _state(turn=71, item_id=7001, num=2, stat=14):
    return {
        "data": {
            "chara_info": {"turn": turn, "speed": 1080, "evaluation_info_array": []},
            "free_data_set": {"user_item_info_array": [{"item_id": item_id, "num": num}]},
        }
    }, {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": [{"target_type": 1, "value": stat}]}


def test_late_whistle_rerolls_sub_20_training_without_bond_gate():
    state, command = _state()
    assert MantItemManager()._whistle_target(state, command, {"Reset Whistle": 2}, {}, {}, 71) == ("Reset Whistle", 1)


def test_late_whistle_stops_on_20_or_rainbow():
    state, command = _state(stat=20)
    assert MantItemManager()._whistle_target(state, command, {"Reset Whistle": 1}, {}, {}, 71) is None

    rainbow = dict(command, training_partner_array=[1])
    state["data"]["chara_info"]["evaluation_info_array"] = [{"target_id": 1, "evaluation": 80}]
    assert MantItemManager()._whistle_target(state, rainbow, {"Reset Whistle": 1}, {}, {}, 71) is None


def test_late_dumps_training_items_on_any_training():
    state, command = _state(item_id=9001, num=1, stat=14)
    assert MantItemManager()._anklet_target(state, command, {"Speed Ankle Weights": 1}, {}) == ("Speed Ankle Weights", 1)
    assert MantItemManager()._megaphone_target(state, command, {"Motivating Megaphone": 1}, {}, {}, 71, None) == ("Motivating Megaphone", 1)


def test_late_cap_soft_at_90_hard_at_95_with_1200_cap():
    strat = MantStrategy()
    command = {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": [{"target_type": 1, "value": 100}]}
    base = strat._score_command(command, {}, {"turn": 71, "speed": 1000}, {})
    soft = strat._score_command(command, {}, {"turn": 71, "speed": 1080}, {})
    hard = strat._score_command(command, {}, {"turn": 71, "speed": 1140}, {})
    assert round(soft / base, 2) == 0.90
    assert round(hard / base, 2) == 0.35


def test_late_rescue_allows_weak_training_if_whistle_exists_and_energy_can_cover():
    strat = MantStrategy()
    data = {"free_data_set": {"user_item_info_array": [{"item_id": 7001, "num": 1}, {"item_id": 2001, "num": 1}]}}
    chara = {"turn": 71, "vital": 45, "evaluation_info_array": []}
    command = {"command_type": 1, "command_id": 101, "failure_rate": 0, "params_inc_dec_info_array": [{"target_type": 1, "value": 14}]}
    assert strat._can_rescue_training(data, chara, {}, command, 0.1, 45, 0, 48) is True


def test_late_rescue_allows_very_low_energy_when_item_can_cover():
    strat = MantStrategy()
    data = {"free_data_set": {"user_item_info_array": [{"item_id": 7001, "num": 1}, {"item_id": 2003, "num": 1}]}}
    chara = {"turn": 71, "vital": 10, "evaluation_info_array": []}
    command = {"command_type": 1, "command_id": 101, "failure_rate": 0, "params_inc_dec_info_array": [{"target_type": 1, "value": 14}]}
    assert strat._can_rescue_training(data, chara, {}, command, 0.1, 10, 0, 48) is True


def test_late_glc_failure_threshold_drops_with_stock():
    manager = MantItemManager()
    command = {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": [{"target_type": 1, "value": 20}]}
    for qty, threshold in [(1, 20), (2, 16), (3, 10), (4, 3)]:
        owned = {"Good-Luck Charm": qty}
        chara = {"turn": 71, "evaluation_info_array": []}
        assert manager._charm_target(dict(command, failure_rate=threshold - 1), owned, {}, {}, chara) is None
        assert manager._charm_target(dict(command, failure_rate=threshold), owned, {}, {}, chara) == ("Good-Luck Charm", 1)
        assert manager._charm_target(dict(command, failure_rate=threshold), owned, {}, {}, chara, vita_covered=True) == ("Good-Luck Charm", 1)


def _late_command_state(failure, items=None, vital=0, stat=20):
    return {
        "home_info": {"command_info_array": [
            {"command_type": 1, "command_id": 101, "is_enable": 1, "failure_rate": failure, "params_inc_dec_info_array": [{"target_type": 1, "value": stat}]},
            {"command_type": 7, "command_id": 701, "is_enable": 1},
        ]},
        "free_data_set": {"user_item_info_array": items or []},
        "chara_info": {"turn": 71, "vital": vital, "motivation": 5, "evaluation_info_array": []},
    }


def test_late_trains_through_empty_energy_with_glc():
    strat = MantStrategy()
    data = _late_command_state(20, [{"item_id": 10001, "num": 1}])
    assert strat._best_command(data, data["chara_info"], {})["command_type"] == 1


def test_late_only_rests_without_energy_or_glc_above_30_failure():
    strat = MantStrategy()
    safe = _late_command_state(30, stat=5)
    risky = _late_command_state(31, stat=5)
    assert strat._best_command(safe, safe["chara_info"], {})["command_type"] == 1
    assert strat._best_command(risky, risky["chara_info"], {})["command_type"] == 7


def test_late_uses_energy_before_rest_even_above_hard_cap():
    strat = MantStrategy()
    data = _late_command_state(50, [{"item_id": 2001, "num": 1}], vital=0, stat=5)
    assert strat._best_command(data, data["chara_info"], {})["command_type"] == 1
    assert MantItemManager()._energy_targets(data["chara_info"], {"Vita 20": 1}, {}, data["home_info"]["command_info_array"][0]) == [("Vita 20", 1)]


def test_late_skips_auto_mood_recreation_by_default():
    strat = MantStrategy()
    assert strat._should_recreate({"command_type": 3, "command_id": 301}, {}, 71, 1, 80, 0.0) is False


def _medic_state(turn, stat=10, partners=None):
    return {
        "home_info": {"command_info_array": [
            {"command_type": 1, "command_id": 101, "is_enable": 1, "training_partner_array": partners or [], "params_inc_dec_info_array": [{"target_type": 1, "value": stat}]},
            {"command_type": 3, "command_id": 301, "is_enable": 1},
            {"command_type": 7, "command_id": 701, "is_enable": 1},
            {"command_type": 8, "command_id": 801, "is_enable": 1},
        ]},
        "chara_info": {"turn": turn, "vital": 80, "motivation": 5, "chara_effect_id_array": [5], "evaluation_info_array": [{"target_id": 1, "evaluation": 80}]},
    }


def test_medic_waits_six_turns_after_bad_status():
    strat = MantStrategy()
    preset = {"cure_asap_conditions": ["Migraine"]}
    assert strat._best_command(_medic_state(20), _medic_state(20)["chara_info"], preset)["command_type"] == 1
    assert strat._best_command(_medic_state(25), _medic_state(25)["chara_info"], preset)["command_type"] == 1
    assert strat._best_command(_medic_state(26), _medic_state(26)["chara_info"], preset)["command_type"] == 8


def test_recreate_and_good_train_outrank_ready_medic():
    preset = {"cure_asap_conditions": ["Migraine"], "prioritize_recreation": True, "pal_thresholds": [[5, 90, 0.3]]}
    strat = MantStrategy()
    strat._bad_status_first_turn = {"migraine": 10}
    assert strat._best_command(_medic_state(20), _medic_state(20)["chara_info"], preset)["command_type"] == 3

    strat = MantStrategy()
    strat._bad_status_first_turn = {"migraine": 10}
    good = _medic_state(20, stat=35)
    assert strat._best_command(good, good["chara_info"], {"cure_asap_conditions": ["Migraine"]})["command_type"] == 1
