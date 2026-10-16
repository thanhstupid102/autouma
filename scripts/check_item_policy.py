import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from career_bot.scenarios.mant.items import DISPLAY_TO_ID, MantItemManager


class UseClient:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.calls = []

    def use_items(self, payload, turn):
        self.calls.append((copy.deepcopy(payload), turn))
        return {"data": {}}

    def exchange_items(self, payload, turn):
        self.calls.append((copy.deepcopy(payload), turn))
        return {"data": {}}


def state(turn, vital=50, motivation=3, items=None):
    return {
        "data": {
            "chara_info": {"turn": turn, "vital": vital, "max_vital": 100, "motivation": motivation},
            "free_data_set": {
                "coin_num": 0,
                "user_item_info_array": [
                    {"item_id": DISPLAY_TO_ID[name], "num": count}
                    for name, count in (items or {}).items()
                ],
                "pick_up_item_info_array": [],
            },
        }
    }


def names_from_payload(payload):
    by_id = {v: k for k, v in DISPLAY_TO_ID.items()}
    return [by_id[row["item_id"]] for row in payload]


def check_pre_race_uses_only_one_edm_before_third_consecutive_race():
    manager = MantItemManager()
    s = state(20, vital=0, items={"Vita 20": 2, "Royal Kale Juice": 1})
    client = UseClient(s)
    manager.handle_pre_race(client, s, {}, {"program_id": 1, "current_turn": 20}, {"consecutive_race_count": 1})
    assert client.calls == []

    manager = MantItemManager()
    s = state(20, vital=0, items={"Vita 20": 2, "Energy Drink MAX": 2, "Royal Kale Juice": 1})
    client = UseClient(s)
    manager.handle_pre_race(client, s, {}, {"program_id": 1, "current_turn": 20}, {"consecutive_race_count": 1})
    assert client.calls[0][0] == [{"item_id": DISPLAY_TO_ID["Energy Drink MAX"], "use_num": 1, "current_num": 2}]

    manager = MantItemManager()
    s = state(20, vital=0, items={"Energy Drink MAX": 2})
    client = UseClient(s)
    manager.handle_pre_race(client, s, {}, {"program_id": 1, "current_turn": 20}, {"consecutive_race_count": 3})
    assert client.calls == []


def check_low_vital_train_prefers_rkj_over_vita():
    manager = MantItemManager()
    owned = {"Vita 20": 2, "Royal Kale Juice": 1, "Good-Luck Charm": 1, "Berry Sweet Cupcake": 1}
    cmd = {"command_type": 1, "command_id": 101}

    assert manager._energy_targets({"turn": 27, "vital": 18, "max_vital": 100}, owned, {}, cmd) == [("Royal Kale Juice", 1)]
    assert manager._energy_targets({"turn": 27, "vital": 18, "max_vital": 100}, owned, {}, {"command_type": 7}) == [("Royal Kale Juice", 1)]


def check_summer_cupcake_stock_and_use():
    manager = MantItemManager()
    owned = {"Plain Cupcake": 3, "Berry Sweet Cupcake": 1}

    reserved = manager._summer_reserved_items(owned, {}, 29)
    assert reserved["Plain Cupcake"] == 2
    assert reserved["Berry Sweet Cupcake"] == 1
    assert manager._mood_targets({"turn": 37, "motivation": 3}, owned, {}) == [("Berry Sweet Cupcake", 1)]
    assert manager._mood_targets({"turn": 37, "motivation": 4}, owned, {}) == [("Plain Cupcake", 1)]


def check_early_pre_summer_half_stock_does_not_count_rkj_but_can_buy_it():
    manager = MantItemManager()
    owned = {"Vita 20": 2, "Good-Luck Charm": 1, "Royal Kale Juice": 3}

    assert manager._summer_energy_charm_value(owned, 27) == 90
    assert manager._summer_stock_needed("Vita 20", owned, {}, 27) is True
    assert manager._summer_stock_needed("Royal Kale Juice", owned, {}, 27) is False

    s = state(27, items={"Vita 20": 2, "Good-Luck Charm": 1})
    s["data"]["free_data_set"].update({
        "coin_num": 300,
        "pick_up_item_info_array": [{"shop_item_id": 1, "item_id": DISPLAY_TO_ID["Royal Kale Juice"], "coin_num": 70, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0}],
    })
    client = UseClient(s)
    manager.buy_shop_items(client, s, {})
    assert client.calls[0][0] == [{"shop_item_id": 1, "current_num": 0}]


def check_energy_drink_max_ex_ignored():
    manager = MantItemManager()
    assert manager._skip_buy("Energy Drink MAX EX", {}, {}, 1, 999) is True
    s = state(20, vital=0, items={"Energy Drink MAX EX": 1})
    client = UseClient(s)
    manager.handle_pre_race(client, s, {}, {"program_id": 1, "current_turn": 20})
    assert client.calls == []


def check_grilled_carrots_wait_until_normal_card_crosses_80():
    manager = MantItemManager()
    s = state(20, items={"Grilled Carrots": 2})
    chara = s["data"]["chara_info"]
    chara["support_card_array"] = [
        {"position": 1, "support_card_id": 30081},
        {"position": 2, "support_card_id": 30067},
        {"position": 3, "support_card_id": 1},
    ]
    chara["evaluation_info_array"] = [
        {"target_id": 1, "evaluation": 71},
        {"target_id": 2, "evaluation": 71},
        {"target_id": 3, "evaluation": 70},
    ]
    assert manager._grilled_carrot_target(s["data"], {"Grilled Carrots": 2}, {}, 20) is None
    chara["evaluation_info_array"][2]["evaluation"] = 71
    assert manager._grilled_carrot_target(s["data"], {"Grilled Carrots": 2}, {}, 20) == ("Grilled Carrots", 2)


if __name__ == "__main__":
    check_pre_race_uses_only_one_edm_before_third_consecutive_race()
    check_low_vital_train_prefers_rkj_over_vita()
    check_summer_cupcake_stock_and_use()
    check_early_pre_summer_half_stock_does_not_count_rkj_but_can_buy_it()
    check_energy_drink_max_ex_ignored()
    check_grilled_carrots_wait_until_normal_card_crosses_80()
    print("item policy self-check ok")
