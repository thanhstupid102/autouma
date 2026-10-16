import logging

import pytest

from career_bot.engine import CareerRunner
from career_bot.scenarios.base import Decision


def _inventory_state(turn):
    return {
        "data": {
            "chara_info": {"turn": turn, "playing_state": 1, "skill_point": 0},
            "free_data_set": {
                "user_item_info_array": [{"item_id": 1001, "num": 2}],
            },
        },
    }


class _InventoryStrategy:
    def __init__(self, handles_shop_items):
        self.handles_shop_items = handles_shop_items

    def next_decision(self, state, preset):
        turn = state["data"]["chara_info"]["turn"]
        if turn == 11:
            return Decision("advance", {"current_turn": turn}, "advance turn")
        return Decision("done", {}, "complete")

    def extra_action_handlers(self):
        return {"advance": self._advance_turn}

    @staticmethod
    def _advance_turn(runner, client, state, preset, payload):
        return _inventory_state(12)


@pytest.mark.parametrize(("handles_shop_items", "expected_turns"), [
    (False, []),
    (True, [11, 12]),
])
def test_turn_advance_inventory_log_respects_scenario_capability(
        monkeypatch, tmp_path, caplog, handles_shop_items, expected_turns):
    import career_bot.engine.runner as runner_module

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(runner_module.notify, "start_live_monitor", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.notify, "stop_live_monitor", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.notify, "send_career_summary", lambda *args, **kwargs: None)

    runner = CareerRunner(tmp_path)
    strategy = _InventoryStrategy(handles_shop_items)
    runner.strategy = strategy
    runner._init_debug_log({}, scenario_id=4 if handles_shop_items else 2)
    runner._debug_turn = lambda *args, **kwargs: None
    runner._buy_skills = lambda client, state, preset, force: state

    runner._run(object(), {}, _inventory_state(11), strategy, max_steps=2)

    inventory_logs = [row for row in runner.status["log"] if row["action"] == "inventory"]
    assert [row["turn"] for row in inventory_logs] == expected_turns
    output = caplog.text
    assert ("T11 Inventory: Speed Notepad 2" in output) is handles_shop_items
    assert ("T12 Inventory: Speed Notepad 2" in output) is handles_shop_items


@pytest.mark.parametrize(("handles_shop_items", "expected_inventory"), [
    (False, None),
    (True, [{"name": "Speed Notepad", "item_id": 1001, "current_num": 2, "failed_scope": None}]),
])
def test_turn_debug_inventory_respects_scenario_capability(
        tmp_path, handles_shop_items, expected_inventory):
    runner = CareerRunner(tmp_path)
    runner.strategy = _InventoryStrategy(handles_shop_items)
    runner._init_debug_log({}, scenario_id=4 if handles_shop_items else 2)

    runner._debug_turn(_inventory_state(12), {})

    turn = runner.report["turns"][0]
    if expected_inventory is None:
        assert "inventory" not in turn
    else:
        assert turn["inventory"] == expected_inventory


def test_record_action_persists_unity_score_detail_and_prints_row(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    runner = CareerRunner(tmp_path)
    score_debug = {
        "score": 8.0,
        "bondable_count": 2,
        "rainbow_count": 2,
        "white_count": 3,
        "blue_count": 3,
        "purple_count": 1,
        "failure_percent": 0,
        "tie_break": None,
    }
    decision = Decision(
        "command",
        {
            "command_type": 1,
            "command_id": 101,
            "command_group_id": 101,
            "select_id": 0,
            "current_turn": 22,
            "current_vital": 100,
            "_facility_label": "Spd",
            "_score_detail": "Score: 8.0 (2B, 2RB, 3Ws, 3Bs, 1Ps, 0F)",
            "_score_debug": score_debug,
        },
        "training Speed 101",
    )
    chara = {
        "turn": 22,
        "vital": 100,
        "max_vital": 100,
        "motivation": 4,
        "speed": 229,
        "stamina": 169,
        "power": 276,
        "guts": 210,
        "wiz": 290,
        "skill_point": 352,
    }

    runner._record_action(decision, chara)

    row = runner.status["action_history"][-1]
    assert row["turn"] == 22
    assert row["action"] == "train"
    assert row["facility"] == "Spd"
    assert row["score_detail"] == "Score: 8.0 (2B, 2RB, 3Ws, 3Bs, 1Ps, 0F)"
    assert row["score_debug"] is score_debug
    assert row["stats"]["hp"] == 100
    assert row["stats"]["speed"] == 229

    out = caplog.text
    assert "22\ttrain\tSpd | Score: 8.0 (2B, 2RB, 3Ws, 3Bs, 1Ps, 0F)\tHP 100/100 | MOOD 4" in out
    assert runner._exec_command_payload(decision.payload) == {
        "command_type": 1,
        "command_id": 101,
        "command_group_id": 101,
        "select_id": 0,
        "current_turn": 22,
        "current_vital": 100,
    }


def test_exec_command_payload_keeps_wire_fields():
    runner = CareerRunner(".")
    wire_payload = {
        "command_type": 3,
        "command_id": 0,
        "command_group_id": 390,
        "select_id": 177,
        "current_turn": 22,
        "current_vital": 100,
        "_facility_label": "Light Hello date",
    }

    assert runner._exec_command_payload(wire_payload) == {
        "command_type": 3,
        "command_id": 0,
        "command_group_id": 390,
        "select_id": 177,
        "current_turn": 22,
        "current_vital": 100,
    }
