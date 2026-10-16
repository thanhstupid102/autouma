"""The MANT coin-shop / item-use manager (``career_bot/scenarios/mant/items/``).

Renamed from ``test_items.py``: the flat ``career_bot/items.py`` it was named
after moved into the scenarios package in §12.3a. The non-summer megaphone
ladder lives in its own suite, ``test_mant_megaphone_ladder.py``.
"""
import copy
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

from career_bot.scenarios.mant.items import MantItemManager
from career_bot.engine import CareerRunner


class ExchangeClient:
    def __init__(self):
        self.calls = []

    def exchange_items(self, payload, turn):
        self.calls.append((copy.deepcopy(payload), turn))
        return {"data": {}}


def _shop_state(turn=60, coin=200, owned=None, pickups=None):
    return {
        "data": {
            "chara_info": {"turn": turn, "motivation": 3},
            "free_data_set": {
                "coin_num": coin,
                "user_item_info_array": [
                    {"item_id": item_id, "num": count}
                    for item_id, count in (owned or {}).items()
                ],
                "pick_up_item_info_array": pickups or [],
            },
        }
    }


def test_cleat_shop_target_no_longer_blocks_normal_buy_loop():
    assert MantItemManager()._old_ui_cleat_shop_target([], {}, 999, 60) is None


def test_shop_buys_all_available_hammers_through_normal_flow():
    manager = MantItemManager()
    client = ExchangeClient()
    state = _shop_state(pickups=[
        {"shop_item_id": 1, "item_id": 11002, "coin_num": 40, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
        {"shop_item_id": 2, "item_id": 11001, "coin_num": 25, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
    ])

    _, bought = manager.buy_shop_items(client, state, {})

    assert bought == 2
    assert {row["shop_item_id"] for row in client.calls[0][0]} == {1, 2}


def test_cleat_reserves_three_master_two_artisan_before_climax():
    manager = MantItemManager()

    result = manager._old_ui_cleat_before_race(
        {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 0},
        turn=65,
        program_id=1,
        race_planner=type("RacePlanner", (), {"program": {1: {"race_instance_id": "100001"}}})(),
    )

    assert result is None


def test_cleat_spends_master_spare_in_senior():
    manager = MantItemManager()

    result = manager._old_ui_cleat_before_race(
        {"Master Cleat Hammer": 2, "Artisan Cleat Hammer": 2},
        turn=65,
        program_id=1,
        race_planner=type("RacePlanner", (), {"program": {1: {"race_instance_id": "100001"}}})(),
    )

    assert result == "Master Cleat Hammer"


def test_cleat_prefers_artisan_when_master_scarce():
    manager = MantItemManager()

    result = manager._old_ui_cleat_before_race(
        {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 4},
        turn=65,
        program_id=1,
        race_planner=type("RacePlanner", (), {"program": {1: {"race_instance_id": "100001"}}})(),
    )

    assert result == "Artisan Cleat Hammer"


def test_cleat_spends_freely_at_climax_master():
    manager = MantItemManager()

    result = manager._old_ui_cleat_before_race(
        {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 0},
        turn=74,
        program_id=0,
        race_planner=None,
    )

    assert result == "Master Cleat Hammer"


def test_cleat_spends_freely_at_climax_artisan():
    manager = MantItemManager()

    result = manager._old_ui_cleat_before_race(
        {"Master Cleat Hammer": 0, "Artisan Cleat Hammer": 1},
        turn=74,
        program_id=0,
        race_planner=None,
    )

    assert result == "Artisan Cleat Hammer"


class CapCheckingClient:
    def __init__(self):
        self.calls = []

    def exchange_items(self, exchange_item_info_array, current_turn):
        self.calls.append((exchange_item_info_array, current_turn))
        for item in exchange_item_info_array:
            if item["current_num"] >= 5:
                raise Exception("API error 205 on single_mode_free/multi_item_exchange")
        return {"data": {}}


def test_exchange_does_not_buy_duplicate_item_past_inventory_cap():
    manager = MantItemManager()
    client = CapCheckingClient()
    state = {
        "data": {
            "chara_info": {"turn": 58},
            "free_data_set": {
                "coin_num": 151,
                "user_item_info_array": [{"item_id": 9001, "num": 4}],
                "pick_up_item_info_array": [
                    {"shop_item_id": 101, "item_id": 9001, "coin_num": 50, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 102, "item_id": 9001, "coin_num": 50, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                ],
            },
        }
    }

    _, bought = manager._exchange_batch(
        client,
        state,
        [
            {"shop_item_id": 101, "current_num": 4},
            {"shop_item_id": 102, "current_num": 4},
        ],
        58,
    )

    assert bought == 1
    assert manager.recover_after_exchange_error is False
    assert client.calls == [([{"shop_item_id": 101, "current_num": 4}], 58)]


def test_exchange_keeps_valid_items_in_one_batch():
    manager = MantItemManager()
    client = CapCheckingClient()
    state = {
        "data": {
            "chara_info": {"turn": 73},
            "free_data_set": {
                "coin_num": 357,
                "user_item_info_array": [
                    {"item_id": 11001, "num": 2},
                    {"item_id": 11003, "num": 1},
                ],
                "pick_up_item_info_array": [
                    {"shop_item_id": 150, "item_id": 11001, "coin_num": 25, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 153, "item_id": 1103, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 151, "item_id": 11003, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                ],
            },
        }
    }

    _, bought = manager._exchange_batch(
        client,
        state,
        [
            {"shop_item_id": 150, "current_num": 0},
            {"shop_item_id": 153, "current_num": 0},
            {"shop_item_id": 151, "current_num": 0},
        ],
        73,
    )

    assert bought == 3
    assert client.calls == [(
        [
            {"shop_item_id": 150, "current_num": 2},
            {"shop_item_id": 153, "current_num": 0},
            {"shop_item_id": 151, "current_num": 1},
        ],
        73,
    )]


class DuplicateRejectingClient:
    def __init__(self, shop_item_to_item):
        self.shop_item_to_item = shop_item_to_item
        self.calls = []

    def exchange_items(self, exchange_item_info_array, current_turn):
        item_ids = [self.shop_item_to_item[item["shop_item_id"]] for item in exchange_item_info_array]
        if len(item_ids) != len(set(item_ids)):
            raise Exception("API error 205 on single_mode_free/multi_item_exchange")
        self.calls.append((exchange_item_info_array, current_turn))
        return {"data": {}}


class ItemSplitRejectClient:
    """Rejects any exchange batch containing `bad_shop_item_id` (atomic 205), but
    accepts batches without it -- models one item with a stale current_num."""

    def __init__(self, bad_shop_item_id):
        self.bad = int(bad_shop_item_id)
        self.calls = []

    def exchange_items(self, exchange_item_info_array, current_turn):
        ids = [int(item["shop_item_id"]) for item in exchange_item_info_array]
        self.calls.append(ids)
        if self.bad in ids:
            raise Exception("API error 205 on single_mode_free/multi_item_exchange")
        return {"data": {}}


def test_exchange_splits_on_failure_so_good_items_still_buy():
    manager = MantItemManager()
    client = ItemSplitRejectClient(153)  # one item the server keeps rejecting
    state = {
        "data": {
            "chara_info": {"turn": 73},
            "free_data_set": {
                "coin_num": 357,
                "user_item_info_array": [
                    {"item_id": 11001, "num": 2},
                    {"item_id": 11003, "num": 1},
                ],
                "pick_up_item_info_array": [
                    {"shop_item_id": 150, "item_id": 11001, "coin_num": 25, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 153, "item_id": 1103, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 151, "item_id": 11003, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                ],
            },
        }
    }

    _, bought = manager._exchange_batch(
        client,
        state,
        [
            {"shop_item_id": 150, "current_num": 0},
            {"shop_item_id": 153, "current_num": 0},
            {"shop_item_id": 151, "current_num": 0},
        ],
        73,
    )

    # The 3-item round fails once, then each item is retried alone: the two good ones
    # buy, the rejected one is dropped + marked (instead of wasting the whole round).
    assert bought == 2
    assert client.calls[0] == [150, 153, 151]  # failed atomic round
    assert [150] in client.calls and [151] in client.calls and [153] in client.calls
    # 205 (stale current_num) keeps the sid synced -> the rejected item is just dropped,
    # no session reload. (Only a 208 sid-desync sets recover_after_exchange_error.)
    assert manager.recover_after_exchange_error is False
    assert 153 in manager.failed_exchange_this_snapshot
    assert manager.last_buy_result["bought"] == 2


def test_exchange_splits_duplicate_item_ids_across_batches():
    manager = MantItemManager()
    client = DuplicateRejectingClient({101: 2001, 102: 2001, 103: 1105})
    state = {
        "data": {
            "chara_info": {"turn": 43},
            "free_data_set": {
                "coin_num": 304,
                "user_item_info_array": [{"item_id": 2001, "num": 1}],
                "pick_up_item_info_array": [
                    {"shop_item_id": 101, "item_id": 2001, "coin_num": 35, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 44},
                    {"shop_item_id": 102, "item_id": 2001, "coin_num": 35, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                    {"shop_item_id": 103, "item_id": 1105, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
                ],
            },
        }
    }

    _, bought = manager._exchange_batch(
        client,
        state,
        [
            {"shop_item_id": 101, "current_num": 0},
            {"shop_item_id": 102, "current_num": 0},
            {"shop_item_id": 103, "current_num": 0},
        ],
        43,
    )

    assert bought == 3
    assert client.calls == [
        ([
            {"shop_item_id": 101, "current_num": 1},
            {"shop_item_id": 103, "current_num": 0},
        ], 43),
        ([{"shop_item_id": 102, "current_num": 2}], 43),
    ]
    assert manager.recover_after_exchange_error is False
    assert manager.last_buy_result["result"] == "ok"
    assert manager.last_buy_result["bought"] == 3


def _state_with_owned_item(turn=70, item_id=1001, num=1):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "vital": 50,
                "max_vital": 100,
                "motivation": 3,
                "playing_state": 1,
            },
            "free_data_set": {
                "coin_num": 0,
                "user_item_info_array": [{"item_id": item_id, "num": num}],
                "pick_up_item_info_array": [],
            },
        }
    }


class RejectingUseClient:
    def __init__(self, state, code="205"):
        self.state = copy.deepcopy(state)
        self.use_calls = []
        self.load_calls = 0
        self.code = code

    def use_items(self, item_info_array, current_turn):
        self.use_calls.append((copy.deepcopy(item_info_array), current_turn))
        raise Exception(f"API error {self.code} on single_mode_free/multi_item_use")

    def load_career(self):
        self.load_calls += 1
        return copy.deepcopy(self.state)


def test_item_use_recovery_preserves_failed_item_guard_after_refresh():
    state = _state_with_owned_item(turn=70, item_id=1001, num=1)
    client = RejectingUseClient(state)
    runner = CareerRunner(ROOT)
    manager = runner.item_manager

    current, used = manager.use_items(client, state, preset={})

    assert current is state
    assert used == 0
    assert client.use_calls == [([{"item_id": 1001, "use_num": 1, "current_num": 1}], 70)]
    assert manager.failed_use_this_turn == {1001}
    assert manager.current_turn == 70

    refreshed = runner._fresh_career_state(client, preserve_item_failures=True)

    assert client.load_calls == 1
    assert manager.failed_use_this_turn == {1001}
    assert manager.current_turn == 70

    manager.use_items(client, refreshed, preset={})

    assert len(client.use_calls) == 1
    assert manager.last_use_result == {"skip": "no_targets"}


def test_item_use_recovery_cap_blocks_more_than_two_same_turn_attempts():
    state = _state_with_owned_item(turn=70, item_id=1001, num=1)
    # 208 = sid-desync that DOES trigger a session reload, so the recovery-cap path is
    # exercised (a 205 would just skip the item without reloading).
    client = RejectingUseClient(state, code="208")
    runner = CareerRunner(ROOT)

    for _ in range(4):
        state = runner._handle_items(client, state, {"scenario_id": 4}, best_command={})
        runner.item_manager.failed_use_this_turn.clear()

    assert len(client.use_calls) == 2
    assert runner._item_use_blocked_turn == 70
    assert runner.item_manager.last_use_result == {"skip": "item_use_recovery_cap", "turn": 70}
    assert any(row["action"] == "items_use_recovery_cap" for row in runner.status["log"])


class AcceptingUseClient:
    """The mirror of RejectingUseClient: multi_item_use succeeds and answers with a
    fresh server state fragment (which use_items must merge into the career state)."""

    def __init__(self, response=None):
        self.use_calls = []
        self.response = response if response is not None else {"data": {}}

    def use_items(self, item_info_array, current_turn):
        self.use_calls.append((copy.deepcopy(item_info_array), current_turn))
        return copy.deepcopy(self.response)


def test_item_use_success_records_ok_result_and_merges_the_server_state():
    state = _state_with_owned_item(turn=70, item_id=1001, num=1)
    client = AcceptingUseClient({"data": {"chara_info": {"speed": 999}}})
    manager = MantItemManager()

    current, used = manager.use_items(client, state, preset={})

    payload = [{"item_id": 1001, "use_num": 1, "current_num": 1}]
    assert used == 1
    assert client.use_calls == [(payload, 70)]
    assert manager.last_use_result == {"result": "ok", "turn": 70, "payload": payload}
    assert manager.last_use_selected == [{"name": "Speed Notepad", "item_id": 1001, "use_num": 1}]
    assert manager.last_use_attempt == payload
    # the success branch merges the response instead of handing back the stale state
    assert current["data"]["chara_info"]["speed"] == 999
    assert current["data"]["chara_info"]["turn"] == 70


def test_item_use_success_stamps_the_ok_result_onto_the_attempt_event():
    state = _state_with_owned_item(turn=70, item_id=1001, num=1)
    manager = MantItemManager()

    manager.use_items(AcceptingUseClient(), state, preset={})

    assert len(manager.use_attempt_events) == 1
    event = manager.use_attempt_events[0]
    assert event["turn"] == 70
    assert event["result"] == {"result": "ok", "turn": 70,
                               "payload": [{"item_id": 1001, "use_num": 1, "current_num": 1}]}


def test_item_use_success_clears_a_failure_guard_left_by_an_earlier_attempt():
    state = _state_with_owned_item(turn=70, item_id=1001, num=1)
    manager = MantItemManager()
    # A different item failed earlier in the SAME turn (so _set_turn keeps the guard).
    manager.current_turn = 70
    manager.failed_use_this_turn = {1002}

    manager.use_items(AcceptingUseClient(), state, preset={})

    assert manager.failed_use_this_turn == set()


def test_item_use_success_marks_a_one_time_buff_spent_so_it_is_never_re_used():
    # 4001 = Pretty Mirror, a ONE_TIME_BUFF item.
    state = _state_with_owned_item(turn=70, item_id=4001, num=1)
    client = AcceptingUseClient()
    manager = MantItemManager()

    manager.use_items(client, state, preset={})

    assert manager.used_buffs == {"Pretty Mirror"}

    # The server response leaves the row in stock; the spent-buff record is what
    # keeps the second turn from burning the call again.
    manager.use_items(client, _state_with_owned_item(turn=71, item_id=4001, num=1), preset={})

    assert len(client.use_calls) == 1
    assert manager.last_use_result == {"skip": "no_targets"}


def test_item_use_success_clears_the_first_shop_megaphone_reservation():
    # 8001 = Coaching Megaphone; turn 45 is outside every summer hold window.
    state = _state_with_owned_item(turn=45, item_id=8001, num=1)
    manager = MantItemManager()
    manager.first_shop_megaphone_to_use = "Coaching Megaphone"
    training = {"command_type": 1, "command_id": 101,
                "params_inc_dec_info_array": [{"target_type": 1, "value": 5}]}

    _, used = manager.use_items(AcceptingUseClient(), state, preset={}, best_command=training)

    assert used == 1
    assert manager.last_use_selected == [{"name": "Coaching Megaphone", "item_id": 8001, "use_num": 1}]
    assert manager.first_shop_megaphone_to_use is None


def test_summer_hold_reserves_best_two_megaphones_and_lifts_at_camp_start():
    manager = MantItemManager()
    owned = {
        "Coaching Megaphone": 1,
        "Motivating Megaphone": 2,
        "Empowering Megaphone": 1,
        "Reset Whistle": 2,
    }

    reserved = manager._summer_reserved_items(owned, {}, 29)

    assert reserved["Empowering Megaphone"] == 1
    assert reserved["Motivating Megaphone"] == 1
    assert manager._available_to_use("Motivating Megaphone", owned, {}, 29) == 1
    assert manager._available_to_use("Coaching Megaphone", owned, {}, 29) == 1
    assert manager._available_to_use("Reset Whistle", owned, {}, 36) == 0
    assert manager._available_to_use("Reset Whistle", owned, {}, 37) == 2
    assert manager._available_to_use("Reset Whistle", owned, {}, 60) == 0
    assert manager._available_to_use("Reset Whistle", owned, {}, 61) == 2


def test_summer_hold_reserves_charm_vita_value_and_deck_ankles():
    manager = MantItemManager()
    preset = {"_deck_type_counts": [2, 0, 2, 0, 0]}
    owned = {
        "Good-Luck Charm": 3,
        "Vita 20": 3,
        "Speed Ankle Weights": 3,
        "Stamina Ankle Weights": 2,
        "Power Ankle Weights": 1,
    }

    reserved = manager._summer_reserved_items(owned, preset, 53)

    assert reserved["Good-Luck Charm"] == 3
    assert reserved["Vita 20"] == 3
    assert manager._available_to_use("Good-Luck Charm", owned, preset, 53) == 0
    assert manager._available_to_use("Vita 20", owned, preset, 53) == 0
    assert manager._available_to_use("Good-Luck Charm", owned, preset, 61) == 3
    assert manager._available_to_use("Vita 20", owned, preset, 61) == 3
    assert reserved["Speed Ankle Weights"] == 2
    assert reserved["Stamina Ankle Weights"] == 1
    assert reserved["Power Ankle Weights"] == 1
    assert manager._available_to_use("Speed Ankle Weights", owned, preset, 53) == 1


def test_summer_uses_whistle_below_50_and_biggest_mega_at_50_without_active_mega():
    manager = MantItemManager()
    weak = {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": [{"target_type": 1, "value": 49}]}
    strong = {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": [{"target_type": 1, "value": 50}]}
    owned = {"Reset Whistle": 1, "Coaching Megaphone": 1, "Motivating Megaphone": 1, "Empowering Megaphone": 1}
    state = {"data": {"chara_info": {"turn": 37,
        "support_card_array": [{"position": i, "support_card_id": i} for i in range(1, 7)],
        "evaluation_info_array": [{"target_id": i, "evaluation": 80} for i in range(1, 7)],
    }, "free_data_set": {"item_effect_array": []}}}

    assert manager._whistle_target(state, weak, owned, {}, {}, 37) == ("Reset Whistle", 1)
    assert manager._whistle_target(state, strong, owned, {}, {}, 37) is None
    assert manager._megaphone_target(state, strong, owned, {}, {}, 37, None) == ("Empowering Megaphone", 1)

    active = {"data": {"chara_info": {"turn": 38}, "free_data_set": {"item_effect_array": [{"item_id": 8003}]}}}
    assert manager._megaphone_target(active, strong, owned, {}, {}, 38, None) is None


def test_cure_buy_policy_caps_miracle_and_rhc_and_only_buys_active_specific_cures():
    manager = MantItemManager()
    migraine = {"chara_info": {"chara_effect_id_array": [5]}}

    assert manager._skip_buy("Miracle Cure", {"Miracle Cure": 1}, data={}) is False
    assert manager._skip_buy("Miracle Cure", {"Miracle Cure": 2}, data={}) is True
    assert manager._skip_buy("Rich Hand Cream", {"Rich Hand Cream": 1}, data={}) is False
    assert manager._skip_buy("Rich Hand Cream", {"Rich Hand Cream": 1, "Miracle Cure": 1}, data=migraine) is False
    assert manager._skip_buy("Rich Hand Cream", {"Rich Hand Cream": 2}, data={}) is True

    assert manager._skip_buy("Aroma Diffuser", {}, data=migraine) is False
    assert manager._skip_buy("Aroma Diffuser", {"Aroma Diffuser": 1}, data=migraine) is True
    assert manager._skip_buy("Fluffy Pillow", {}, data=migraine) is True
    assert manager._skip_buy("Aroma Diffuser", {"Miracle Cure": 1}, data=migraine) is True
    assert manager._skip_buy("Practice Drills DVD", {}, data={"chara_info": {"chara_effect_id_array": [6]}}) is True


def test_shop_caps_miracle_and_rhc_at_two_across_same_shop():
    manager = MantItemManager()
    client = ExchangeClient()
    state = _shop_state(coin=200, owned={4201: 1, 4103: 1}, pickups=[
        {"shop_item_id": 1, "item_id": 4201, "coin_num": 40, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
        {"shop_item_id": 2, "item_id": 4201, "coin_num": 40, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
        {"shop_item_id": 3, "item_id": 4103, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
        {"shop_item_id": 4, "item_id": 4103, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
    ])

    _, bought = manager.buy_shop_items(client, state, {})

    assert bought == 2
    assert {row["shop_item_id"] for row in client.calls[0][0]} == {1, 3}


def test_shop_prefers_miracle_over_other_active_cure_in_same_buy():
    manager = MantItemManager()
    client = ExchangeClient()
    state = _shop_state(coin=100, pickups=[
        {"shop_item_id": 1, "item_id": 4201, "coin_num": 40, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
        {"shop_item_id": 2, "item_id": 4105, "coin_num": 15, "item_buy_num": 0, "limit_buy_count": 1, "limit_turn": 0},
    ])
    state["data"]["chara_info"]["chara_effect_id_array"] = [5]

    _, bought = manager.buy_shop_items(client, state, {})

    assert bought == 1
    assert client.calls[0][0] == [{"shop_item_id": 1, "current_num": 0}]


def test_items_constants_match_scenarios_mant_source_of_truth():
    # items/data.py imports (not redefines) these from the scenarios layer -- pin
    # equality so a future re-introduced local copy can't silently drift.
    from career_bot.scenarios.mant import items
    from career_bot.scenarios import mant

    assert items.BAD_EFFECT_NAMES == mant.BAD_EFFECT_NAMES
    assert items.BAD_EFFECT_NAMES is mant.BAD_EFFECT_NAMES

    assert items.SUMMER_CAMP_TURNS == mant.SUMMER_CAMP_TURNS
    assert items.SUMMER_CAMP_TURNS is mant.SUMMER_CAMP_TURNS

    assert items.GROUP_SUPPORT_IDS == set(mant.SIRIUS_THRONE_GROUP_IDS)
    assert items.TEAM_SIRIUS_SUPPORT_ID == mant.TEAM_SIRIUS_SUPPORT_ID
    assert items.THRONE_SUPPORT_ID == mant.THRONE_SUPPORT_ID
