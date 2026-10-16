"""GrandLiveStrategy turn loop and the two Grand-Live-only action handlers.

State shapes follow the DTOs in docs/scenarios/grand-live-endpoints.md; the
turn ordering asserted here is the one reconstructed from the 2026-07-26
capture (uma_runtime/captures/gl_flow_01.jsonl).
"""

from types import SimpleNamespace

import pytest

from career_bot.scenarios import STRATEGIES, get_strategy_class
from career_bot.planning.races import RacePlanner
from career_bot.scenarios.grand_live import strategy as strategy_mod
import uma_data
from career_bot.scenarios.grand_live.live_actions import run_live_square, run_live_start
from career_bot.scenarios.grand_live.live_state import LiveState
from career_bot.scenarios.grand_live.strategy import (
    LIVE_TOP_PLAYING_STATE,
    MAX_SQUARE_BUYS_PER_TURN,
    GrandLiveStrategy,
)
from career_bot.scenarios.grand_live.training_policy import score_grand_live_training


SQUARE_ROWS = {
    11001: {"id": 11001, "square_type": 1, "cost": {1: 10}, "cost_total": 10},
    20024: {"id": 20024, "square_type": 2, "cost": {5: 15}, "cost_total": 15},
    40000: {"id": 40000, "square_type": 4, "cost": {2: 21, 4: 21}, "cost_total": 42},
}

LIVE_ROWS = [{"id": i + 1, "live_type": i + 1, "turn_num": t} for i, t in enumerate([24, 36, 48, 60, 72])]


def performance(dance=0, passion=0, vocal=0, visual=0, mental=0):
    return {
        "dance": dance, "max_dance": 100,
        "passion": passion, "max_passion": 100,
        "vocal": vocal, "max_vocal": 100,
        "visual": visual, "max_visual": 100,
        "mental": mental, "max_mental": 100,
    }


def make_strategy(monkeypatch, *, squares=None, lives=None):
    monkeypatch.setattr(
        uma_data,
        "load_live_squares",
        lambda *a, **k: {
            "success": True,
            "squares": SQUARE_ROWS if squares is None else squares,
            "bonuses": {},
            "lives": LIVE_ROWS if lives is None else lives,
        },
    )
    strategy = GrandLiveStrategy()
    strategy.reset_run_state()
    return strategy


def training(command_id, *, failure=0, partners=None):
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": failure,
        "training_partner_array": partners or [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": 10}],
    }


def support_card(slot, support_id, support_type="Speed"):
    return {"position": slot, "support_card_id": support_id, "support_type": support_type}


def evaluation(slot, bond, outings=None, *, is_outing=0):
    return {"target_id": slot, "evaluation": bond, "is_outing": is_outing, "group_outing_info_array": outings or []}


def make_state(
    *,
    turn=10,
    playing_state=1,
    vital=100,
    motivation=3,
    commands=None,
    events=None,
    live_data_set=None,
    extra_data=None,
):
    data = {
        "chara_info": {
            "turn": turn,
            "playing_state": playing_state,
            "vital": vital,
            "motivation": motivation,
            "evaluation_info_array": [],
        },
        "home_info": {"command_info_array": commands if commands is not None else [training(101)]},
        "unchecked_event_array": events or [],
    }
    if live_data_set is not None:
        data["live_data_set"] = live_data_set
    if extra_data:
        data.update(extra_data)
    return {"data": data}


PRESET = {"rest_threshold": 48, "high_failure_rest_threshold": 35}


# --- registration -----------------------------------------------------------


def test_scenario_3_has_a_runner():
    """runner.start raises "No runner for scenario N" without this."""
    assert 3 in STRATEGIES
    assert get_strategy_class(3) is GrandLiveStrategy
    assert GrandLiveStrategy.scenario_id == 3


def test_live_top_is_not_a_blocked_playing_state():
    from career_bot.engine.runner import CareerRunner

    runner = CareerRunner.__new__(CareerRunner)
    runner.strategy = GrandLiveStrategy()
    assert not runner._blocked_playing_state({"playing_state": LIVE_TOP_PLAYING_STATE})


def test_default_base_dir_is_shared_by_objectives_and_square_catalog(monkeypatch):
    from core.settings import Settings

    seen = []
    monkeypatch.setattr(strategy_mod, "RouteObjectives", lambda base_dir: seen.append(("objectives", base_dir)) or object())
    monkeypatch.setattr(strategy_mod, "SquareCatalog", lambda base_dir: seen.append(("squares", base_dir)) or object())

    strategy = GrandLiveStrategy()

    assert strategy._base_dir == Settings.BASE_DIR
    assert seen == [("objectives", Settings.BASE_DIR), ("squares", Settings.BASE_DIR)]


# --- turn loop --------------------------------------------------------------


def test_trains_when_nothing_else_is_due(monkeypatch):
    strategy = make_strategy(monkeypatch)
    decision = strategy.next_decision(make_state(), PRESET)
    assert decision.action == "command"
    assert decision.payload["command_id"] == 101


def test_events_come_before_everything(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(events=[{"event_id": 1001, "chara_id": 0}])
    assert strategy.next_decision(state, PRESET).action == "event"


def test_buys_an_affordable_square_before_training(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(live_data_set={
        "live_performance_info": performance(dance=50, passion=50, visual=50),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}, {"square_id": 40000, "square_num": 2}],
    })

    decision = strategy.next_decision(state, PRESET)

    assert decision.action == "live_square"
    assert decision.payload["square_id"] == 40000  # song tier wins
    assert "Dance=50" in decision.reason


def test_trains_when_no_square_is_affordable(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(live_data_set={
        "live_performance_info": performance(dance=1),
        "next_square_info_array": [{"square_id": 40000, "square_num": 1}],
    })
    assert strategy.next_decision(state, PRESET).action == "command"


def test_square_purchases_are_capped_per_turn(monkeypatch, caplog):
    strategy = make_strategy(monkeypatch)
    state = make_state(live_data_set={
        "live_performance_info": performance(dance=99),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
    })
    for _ in range(MAX_SQUARE_BUYS_PER_TURN):
        assert strategy.next_decision(state, PRESET).action == "live_square"
        strategy.note_square_bought(10)

    # Cap reached: fall through to the turn's real action instead of looping.
    assert strategy.next_decision(state, PRESET).action == "command"
    assert strategy.next_decision(state, PRESET).action == "command"
    warnings = [record for record in caplog.records if "square-buy cap reached on turn 10" in record.message]
    assert len(warnings) == 1


def test_live_start_fires_on_live_top_playing_state(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=24, playing_state=LIVE_TOP_PLAYING_STATE)

    decision = strategy.next_decision(state, PRESET)

    assert decision.action == "live_start"
    assert decision.payload["current_turn"] == 24


def test_live_start_never_preempts_the_turns_command(monkeypatch, caplog):
    """Regression: the runner re-calls next_decision BEFORE executing a command
    (career_bot/engine/runner.py, the item-handling loop). A turn-number trigger made
    that second call return live_start on turns 24/36/48/60/72, so the training
    was dropped. Only playing_state may trigger the live."""
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=24, playing_state=1)

    assert strategy.next_decision(state, PRESET).action == "command"
    assert strategy.next_decision(state, PRESET).action == "command"
    warnings = [record for record in caplog.records if "Scheduled Grand Live turn 24" in record.message]
    assert len(warnings) == 1
    assert "observed playing_state=1" in warnings[0].message


def test_live_start_is_the_last_resort_instead_of_idling(monkeypatch):
    """A scheduled live turn with no command left must not stop the run."""
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=24, playing_state=1, commands=[])

    decision = strategy.next_decision(state, PRESET)

    assert decision.action == "live_start"
    assert "no other action" in decision.reason


def test_no_action_on_a_normal_turn_still_idles(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=25, playing_state=1, commands=[])
    assert strategy.next_decision(state, PRESET).action == "idle"


def test_live_start_does_not_repeat_for_the_same_turn(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=24, playing_state=LIVE_TOP_PLAYING_STATE)
    assert strategy.next_decision(state, PRESET).action == "live_start"

    strategy.mark_live_done(24)
    assert strategy.next_decision(state, PRESET).action != "live_start"


def test_no_live_on_a_non_scheduled_turn(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=25, playing_state=1)
    strategy.next_decision(state, PRESET)
    assert strategy.next_decision(state, PRESET).action != "live_start"


def test_bad_status_sends_the_trainee_to_medic(monkeypatch):
    """chara_effect_id_array is a flat id list, not a list of objects."""
    strategy = make_strategy(monkeypatch)
    medic = {"command_type": 8, "command_id": 801, "is_enable": 1}
    state = make_state(vital=60, commands=[training(101), medic])
    state["data"]["chara_info"]["chara_effect_id_array"] = [5]

    assert strategy.next_decision(state, PRESET).payload["command_type"] == 8


def test_no_medic_without_bad_status(monkeypatch):
    strategy = make_strategy(monkeypatch)
    medic = {"command_type": 8, "command_id": 801, "is_enable": 1}
    state = make_state(vital=60, commands=[training(101), medic])
    state["data"]["chara_info"]["chara_effect_id_array"] = [0]

    assert strategy.next_decision(state, PRESET).payload["command_type"] == 1


def test_finish_at_career_end(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=78, extra_data={"single_mode_finish_common": {}})
    assert strategy.next_decision(state, PRESET).action == "finish"


def test_rests_on_low_vital(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    state = make_state(vital=20, commands=[training(101), rest])
    decision = strategy.next_decision(state, PRESET)
    assert decision.payload["command_type"] == 7


def test_date_does_not_replace_rest_for_low_vital_or_high_failure(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    risky = training(101, failure=60)
    state = make_state(vital=10, motivation=3, commands=[risky, outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, outings=[{"select_id": 177, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 7


def test_command_decision_reports_token_gain(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(live_data_set={
        "live_performance_info": performance(),
        "command_info_array": [{
            "command_type": 1,
            "command_id": 101,
            "performance_inc_dec_info_array": [{"performance_type": 1, "value": 4}],
        }],
    })

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["_score_detail"] == "Dance+4"


def test_token_overlay_breaks_a_close_training_tie(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(commands=[training(101), training(102)], live_data_set={
        "live_performance_info": performance(mental=0),
        "command_info_array": [
            {"command_type": 1, "command_id": 101, "performance_inc_dec_info_array": []},
            {
                "command_type": 1,
                "command_id": 102,
                "performance_inc_dec_info_array": [{"performance_type": 5, "value": 10}],
            },
        ],
    })

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_id"] == 102
    assert decision.payload["_score_detail"] == "Mental+10"


def test_token_overlay_can_be_disabled_by_preset(monkeypatch):
    strategy = make_strategy(monkeypatch)
    state = make_state(commands=[training(101), training(102)], live_data_set={
        "live_performance_info": performance(mental=0),
        "command_info_array": [
            {"command_type": 1, "command_id": 101, "performance_inc_dec_info_array": []},
            {
                "command_type": 1,
                "command_id": 102,
                "performance_inc_dec_info_array": [{"performance_type": 5, "value": 10}],
            },
        ],
    })

    decision = strategy.next_decision(state, {**PRESET, "grand_live_token_score_weight": 0})

    assert decision.payload["command_id"] == 101


def test_grand_live_support_bond_stack_scores(monkeypatch):
    strategy = make_strategy(monkeypatch)
    strategy._support_list_cache = {"90001": {"type": "Speed"}, "90002": {"type": "Stamina"}, "90003": {"type": "Power"}}
    chara = make_state()["data"]["chara_info"]
    chara["support_card_array"] = [support_card(1, 90001), support_card(2, 90002), support_card(3, 90003)]
    chara["evaluation_info_array"] = [evaluation(1, 30), evaluation(2, 30), evaluation(3, 30)]

    score = score_grand_live_training(strategy, training(101, partners=[1, 2, 3]), {}, chara, PRESET)

    assert score.bondable_count == 3
    assert score.support_score == pytest.approx(1.8)


def test_grand_live_rainbow_rules_use_matching_type_and_wit_bonus(monkeypatch):
    strategy = make_strategy(monkeypatch)
    strategy._support_list_cache = {"90001": {"type": "Speed"}, "90002": {"type": "Wisdom"}, "90003": {"type": "Power"}}
    chara = make_state()["data"]["chara_info"]
    chara["support_card_array"] = [support_card(1, 90001), support_card(2, 90002), support_card(3, 90003)]
    chara["evaluation_info_array"] = [evaluation(1, 80), evaluation(2, 80), evaluation(3, 80)]

    speed_score = score_grand_live_training(strategy, training(101, partners=[1, 3]), {}, chara, PRESET)
    wit_score = score_grand_live_training(strategy, training(106, partners=[2]), {}, chara, PRESET)

    assert speed_score.rainbow_count == 1
    assert speed_score.support_score == pytest.approx(1.05)  # matching Speed + off-type maxed card.
    assert wit_score.rainbow_count == 1
    assert wit_score.support_score == pytest.approx(1.2)


def test_grand_live_light_hello_training_bonus_and_no_normal_bond(monkeypatch):
    strategy = make_strategy(monkeypatch)
    chara = make_state()["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 80)]

    first = score_grand_live_training(strategy, training(101, partners=[6]), {}, chara, PRESET)
    strategy._light_hello_first_training_done = True
    later_wit = score_grand_live_training(strategy, training(106, partners=[6]), {}, chara, PRESET)

    assert first.light_hello_bonus == pytest.approx(1.25)
    assert first.rainbow_count == 0
    assert later_wit.light_hello_bonus == pytest.approx(1.2)


def test_no_training_turn_updates_light_hello_scoring_turn(monkeypatch):
    strategy = make_strategy(monkeypatch)
    strategy._light_hello_first_training_done = True
    strategy._light_hello_first_training_turn = 10
    strategy._light_hello_scoring_turn = 10
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}

    strategy.next_decision(make_state(turn=11, commands=[rest]), PRESET)

    assert strategy._light_hello_scoring_turn == 11
    assert strategy._light_hello_training_bonus(0) == pytest.approx(1.0)


def test_wit_base_preference_beats_equal_training(monkeypatch):
    strategy = make_strategy(monkeypatch)
    decision = strategy.next_decision(make_state(commands=[training(101), training(106)]), PRESET)

    assert decision.payload["command_id"] == 106


def test_grand_live_wit_full_vitality_penalty_turn_buckets(monkeypatch):
    strategy = make_strategy(monkeypatch)
    vital_by_percent = {97: 194, 98: 196, 99: 198, 100: 200}

    def score_at(turn, percent):
        chara = make_state(turn=turn, vital=vital_by_percent[percent])["data"]["chara_info"]
        chara["max_vital"] = 200
        return round(score_grand_live_training(strategy, training(106), {}, chara, PRESET).score, 2)

    assert [score_at(23, p) for p in (97, 98, 99, 100)] == [1.1, 1.1, 1.1, 1.1]
    assert [score_at(24, p) for p in (97, 98, 99, 100)] == [1.1, 0.9, 0.7, 0.3]


def test_light_hello_date_replaces_rest_when_mood_under_three(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    state = make_state(vital=20, motivation=2, commands=[training(101), outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, outings=[{"select_id": 177, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 3
    assert decision.payload["command_group_id"] == 390
    assert decision.payload["select_id"] == 177
    assert decision.payload["_facility_label"] == "Light Hello date"


def test_light_hello_date_does_not_trigger_at_mood_three(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    state = make_state(vital=20, motivation=3, commands=[training(101), outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, outings=[{"select_id": 177, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 7


def test_light_hello_date_does_not_trigger_before_outing_unlocked(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    state = make_state(vital=20, motivation=2, commands=[training(101), outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(2, 30052), support_card(6, 30101)]
    chara["evaluation_info_array"] = [
        evaluation(2, 27, is_outing=0),
        evaluation(6, 20, is_outing=0),
    ]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 7
    assert decision.payload.get("_facility_label") != "Light Hello date"


def test_light_hello_date_replaces_rest_on_mid_energy_no_good_training(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    weak = training(101)
    weak["params_inc_dec_info_array"] = [{"target_type": 1, "value": 1}]
    state = make_state(vital=50, motivation=4, commands=[weak, outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, outings=[{"select_id": 0, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 3
    assert decision.payload["select_id"] == 9008


def test_light_hello_date_does_not_override_low_vital_rest(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    weak = training(101)
    weak["params_inc_dec_info_array"] = [{"target_type": 1, "value": 1}]
    state = make_state(vital=30, motivation=4, commands=[weak, outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, outings=[{"select_id": 177, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 7


def test_light_hello_date_uses_capture_fallback_when_unlocked_without_select_id(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    state = make_state(vital=20, motivation=2, commands=[training(101), outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(6, 40, is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 3
    assert decision.payload["command_group_id"] == 390
    assert decision.payload["select_id"] == 9008


def test_light_hello_date_does_not_replace_good_training(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    outing = {"command_type": 3, "command_id": 390, "is_enable": 1}
    strong = training(101, partners=[1, 2, 3])
    state = make_state(vital=50, motivation=4, commands=[strong, outing, rest])
    chara = state["data"]["chara_info"]
    chara["support_card_array"] = [support_card(1, 90001), support_card(2, 90002), support_card(3, 90003), support_card(6, 30052)]
    chara["evaluation_info_array"] = [evaluation(1, 30), evaluation(2, 30), evaluation(3, 30), evaluation(6, 40, outings=[{"select_id": 177, "is_outing": 1}], is_outing=1)]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 1


def test_token_overlay_does_not_bypass_rest_safety_gate(monkeypatch):
    strategy = make_strategy(monkeypatch)
    rest = {"command_type": 7, "command_id": 701, "is_enable": 1}
    token_rich = training(105)
    state = make_state(vital=20, commands=[token_rich, rest], live_data_set={
        "live_performance_info": performance(mental=0),
        "command_info_array": [{
            "command_type": 1,
            "command_id": 105,
            "performance_inc_dec_info_array": [{"performance_type": 5, "value": 50}],
        }],
    })

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 7


def test_token_overlay_does_not_bypass_medic_safety_gate(monkeypatch):
    strategy = make_strategy(monkeypatch)
    medic = {"command_type": 8, "command_id": 801, "is_enable": 1}
    state = make_state(vital=60, commands=[training(105), medic], live_data_set={
        "live_performance_info": performance(mental=0),
        "command_info_array": [{
            "command_type": 1,
            "command_id": 105,
            "performance_inc_dec_info_array": [{"performance_type": 5, "value": 50}],
        }],
    })
    state["data"]["chara_info"]["chara_effect_id_array"] = [5]

    decision = strategy.next_decision(state, PRESET)

    assert decision.payload["command_type"] == 8


def test_reset_run_state_clears_career_state(monkeypatch):
    strategy = make_strategy(monkeypatch)
    strategy.mark_live_done(24)
    strategy.note_square_bought(24)
    strategy.live.update({"live_performance_info": performance(dance=9)})

    strategy.reset_run_state()

    assert strategy.squares_bought_this_turn(24) == 0
    assert strategy.live.tokens[1] == 0
    state = make_state(turn=24, playing_state=LIVE_TOP_PLAYING_STATE)
    assert strategy.next_decision(state, PRESET).action == "live_start"


# --- action handlers --------------------------------------------------------


class FakeRunner:
    def __init__(self, reload_state=None):
        self.logs = []
        self.drained = 0
        self.reloaded = 0
        self._reload_state = reload_state or {"data": {"home_info": {"command_info_array": []}}}

    def _log(self, kind, turn, detail):
        self.logs.append((kind, turn, detail))

    def _drain_events(self, client, strategy, state):
        self.drained += 1
        data = dict((state or {}).get("data") or {})
        data["unchecked_event_array"] = []
        return {"data": data}

    def _fresh_career_state(self, client, strategy=None):
        self.reloaded += 1
        return self._reload_state


class FakeClient:
    def __init__(self, square_response=None, live_response=None):
        self.calls = []
        self._square_response = square_response or {"data": {"home_info": {}, "live_data_set": {}}}
        self._live_response = live_response or {"data": {"chara_info": {}, "live_data_set": {}}}

    def master_square(self, square_id, current_turn):
        self.calls.append(("master_square", square_id, current_turn))
        return self._square_response

    def live_start(self, current_turn):
        self.calls.append(("live_start", current_turn))
        return self._live_response


def test_run_live_square_buys_and_records(monkeypatch):
    strategy = make_strategy(monkeypatch)
    runner, client = FakeRunner(), FakeClient(
        square_response={"data": {"home_info": {}, "live_data_set": {"live_performance_info": performance(dance=7)}}}
    )

    result = run_live_square(runner, client, {}, PRESET, {
        "square_id": 40000, "current_turn": 30, "_strategy": strategy,
    })

    assert client.calls == [("master_square", 40000, 30)]
    assert strategy.squares_bought_this_turn(30) == 1
    assert 40000 in strategy._bought_song_ids
    assert strategy._session_song_buys[2] == 1
    assert strategy.live.tokens[1] == 7
    assert result["data"]["live_data_set"]["live_performance_info"]["dance"] == 7


def test_run_live_square_ignores_a_missing_square_id(monkeypatch):
    strategy = make_strategy(monkeypatch)
    runner, client = FakeRunner(), FakeClient()
    state = {"data": {"home_info": {}}}

    assert run_live_square(runner, client, state, PRESET, {"current_turn": 5, "_strategy": strategy}) is state
    assert client.calls == []


def test_run_live_start_marks_done_before_calling(monkeypatch):
    """Marked first so a server error cannot retry-loop the same turn."""
    strategy = make_strategy(monkeypatch)
    runner = FakeRunner()

    class Boom(FakeClient):
        def live_start(self, current_turn):
            raise RuntimeError("API error 102")

    with pytest.raises(RuntimeError):
        run_live_start(runner, Boom(), {}, PRESET, {"current_turn": 24, "_strategy": strategy})

    state = make_state(turn=24, playing_state=LIVE_TOP_PLAYING_STATE)
    assert strategy.next_decision(state, PRESET).action != "live_start"


def test_run_live_start_reloads_when_response_lacks_home_info(monkeypatch):
    """SingleModeLiveLiveStartResponse carries no home_info, so the next turn's
    commands must come from a fresh load."""
    strategy = make_strategy(monkeypatch)
    reload_state = {"data": {"home_info": {"command_info_array": [training(101)]}}}
    runner = FakeRunner(reload_state=reload_state)

    result = run_live_start(runner, FakeClient(), {}, PRESET, {"current_turn": 24, "_strategy": strategy})

    assert runner.reloaded == 1
    assert result is reload_state


def test_run_live_start_keeps_a_response_that_has_home_info(monkeypatch):
    strategy = make_strategy(monkeypatch)
    runner = FakeRunner()
    live_response = {"data": {"home_info": {"command_info_array": []}, "live_data_set": {}}}

    result = run_live_start(runner, FakeClient(live_response=live_response), {}, PRESET, {
        "current_turn": 24, "_strategy": strategy,
    })

    assert runner.reloaded == 0
    assert result is live_response


# --- console token inventory --------------------------------------------------


def test_turn_start_prints_the_five_tokens_and_the_tree(monkeypatch, capsys):
    strategy = make_strategy(monkeypatch)
    # 11001 costs 10 Dance; 40000 costs 21 Passion + 21 Visual, so 10 Visual is
    # 11 short -- the line has to show both the affordable and the blocked one.
    state = make_state(turn=12, live_data_set={
        "live_performance_info": performance(dance=23, passion=32, vocal=27, visual=10),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}, {"square_id": 40000, "square_num": 2}],
    })

    strategy.next_decision(state, PRESET)
    line = capsys.readouterr().out.splitlines()[0]

    assert line.startswith("T12 Tokens ")
    assert "Da=23" in line and "Me=0" in line
    assert "11001(Parameter,10,ok)" in line
    assert "40000(Song,42,short 11 Vi)" in line


def test_turn_start_line_prints_once_per_turn(monkeypatch, capsys):
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=12, live_data_set={"live_performance_info": performance(dance=5)})

    strategy.next_decision(state, PRESET)
    strategy.next_decision(state, PRESET)
    assert len([ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("T12 Tokens")]) == 1

    strategy.next_decision(make_state(turn=13, live_data_set={"live_performance_info": performance(dance=5)}), PRESET)
    assert any(ln.startswith("T13 Tokens") for ln in capsys.readouterr().out.splitlines())


def test_token_delta_reports_what_a_square_cost():
    state = LiveState({"live_performance_info": performance(dance=23, visual=25)})
    before = state.tokens
    state.update({"live_performance_info": performance(dance=9, visual=9)})

    assert state.token_delta(before) == "-14 Da -16 Vi"
    assert LiveState({"live_performance_info": performance(dance=23)}).token_delta({1: 23}) == ""


def test_buying_a_square_prints_the_new_inventory(monkeypatch, capsys):
    strategy = make_strategy(monkeypatch)
    strategy.live.update({"live_performance_info": performance(dance=23, visual=25)})
    runner = FakeRunner()
    client = FakeClient(square_response={"data": {
        "home_info": {"command_info_array": [{"command_type": 1, "command_id": 101, "is_enable": 1}]},
        "live_data_set": {"live_performance_info": performance(dance=9, visual=9)},
    }})

    run_live_square(runner, client, {}, PRESET, {
        "square_id": 40003, "current_turn": 12, "_strategy": strategy,
    })

    out = capsys.readouterr().out
    assert "T12 Tokens Da=9" in out
    assert "bought square 40003 (-14 Da -16 Vi)" in out
    assert ("live_square", 12, "bought square 40003 (-14 Da -16 Vi)") in runner.logs


def test_a_square_that_costs_nothing_is_called_out(monkeypatch, capsys):
    """If tokens never move, the run would buy up to the per-turn cap; say so."""
    strategy = make_strategy(monkeypatch)
    strategy.live.update({"live_performance_info": performance(dance=23)})
    runner = FakeRunner()
    client = FakeClient(square_response={"data": {
        "home_info": {"command_info_array": [{"command_type": 1, "command_id": 101, "is_enable": 1}]},
        "live_data_set": {"live_performance_info": performance(dance=23)},
    }})

    run_live_square(runner, client, {}, PRESET, {
        "square_id": 11001, "current_turn": 12, "_strategy": strategy,
    })

    assert "no token change" in capsys.readouterr().out


# --- the 2026-07-27 self-termination -----------------------------------------

# Exactly the command_info_array the server returned on turns 12/68/78: every
# command disabled except the race. Copied from
# uma_runtime/bot_logs/career_log_new_20260727_010408.json.
FORCED_RACE_COMMANDS = [
    {"command_type": 1, "command_id": 101, "is_enable": 0},
    {"command_type": 1, "command_id": 105, "is_enable": 0},
    {"command_type": 1, "command_id": 102, "is_enable": 0},
    {"command_type": 1, "command_id": 103, "is_enable": 0},
    {"command_type": 1, "command_id": 106, "is_enable": 0},
    {"command_type": 3, "command_id": 301, "is_enable": 0},
    {"command_type": 3, "command_id": 390, "is_enable": 0},
    {"command_type": 4, "command_id": 401, "is_enable": 1},
    {"command_type": 7, "command_id": 701, "is_enable": 0},
    {"command_type": 8, "command_id": 801, "is_enable": 0},
]

# master_square answers with only these five keys -- no race_condition_array and
# no race_start_info (verified across all 52 master_square responses in the run).
def master_square_response(commands=None):
    return {"data": {
        "chara_info": {"turn": 68, "playing_state": 1, "vital": 65},
        "home_info": {"command_info_array": commands if commands is not None else FORCED_RACE_COMMANDS},
        "live_data_set": {"live_performance_info": performance(dance=15)},
        "not_up_parameter_info": {},
        "unchecked_event_array": [],
    }}


def test_detects_the_stranded_forced_race():
    from career_bot.scenarios.grand_live.live_actions import _race_is_stranded

    assert _race_is_stranded(master_square_response())

    # Not stranded once the race is resolvable...
    resolvable = master_square_response()
    resolvable["data"]["race_condition_array"] = [{"program_id": 1001}]
    assert not _race_is_stranded(resolvable)

    # ...nor on an ordinary turn where training is still enabled.
    ordinary = master_square_response(commands=[
        {"command_type": 1, "command_id": 101, "is_enable": 1},
        {"command_type": 4, "command_id": 401, "is_enable": 1},
    ])
    assert not _race_is_stranded(ordinary)


def test_run_live_square_reloads_instead_of_stranding_the_race(monkeypatch):
    """Regression for the 2026-07-27 session: three runs died on turns 12/68/78
    because master_square left a forced race with no race_condition_array, the
    race planner returned 0, no command was enabled, and the strategy idled --
    which stops the runner."""
    strategy = make_strategy(monkeypatch)
    reload_state = {"data": {
        "home_info": {"command_info_array": FORCED_RACE_COMMANDS},
        "race_condition_array": [{"program_id": 1001}],
    }}
    runner = FakeRunner(reload_state=reload_state)
    client = FakeClient(square_response=master_square_response())

    result = run_live_square(runner, client, {}, PRESET, {
        "square_id": 11001, "current_turn": 68, "_strategy": strategy,
    })

    assert runner.reloaded == 1
    assert result is reload_state
    assert any(kind == "live_square_reload" for kind, _turn, _detail in runner.logs)


def test_run_live_square_does_not_reload_on_a_normal_turn(monkeypatch):
    strategy = make_strategy(monkeypatch)
    runner = FakeRunner()
    response = master_square_response(commands=[{"command_type": 1, "command_id": 101, "is_enable": 1}])

    result = run_live_square(runner, client=FakeClient(square_response=response), state={}, preset=PRESET, payload={
        "square_id": 11001, "current_turn": 30, "_strategy": strategy,
    })

    assert runner.reloaded == 0
    assert result is response


def test_forced_race_is_decided_before_buying_squares(monkeypatch):
    """Squares are a free action, but buying first on a mandatory-race turn is
    what produced the stranded state. Race wins the ordering."""
    strategy = make_strategy(monkeypatch)
    strategy.race_planner = SimpleNamespace(
        forced_program=lambda state, preferred=None: 1001,
        choose=lambda state, preset: 0,
        label=lambda pid: f"race {pid}",
        base_dir=None,
    )
    strategy.objectives = SimpleNamespace(
        race_program_candidates_for_turn=lambda chara, turn: [],
        required_rank_for_turn=lambda chara, turn: None,
        reset=lambda: None,
    )
    state = make_state(turn=68, commands=FORCED_RACE_COMMANDS, live_data_set={
        "live_performance_info": performance(dance=99),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
    })

    decision = strategy.next_decision(state, PRESET)

    assert decision.action == "race"
    assert decision.payload["program_id"] == 1001


def test_grand_live_exhausted_forced_race_idles_but_normal_turn_plays_square(
    monkeypatch,
    tmp_path,
):
    strategy = make_strategy(monkeypatch)
    planner = RacePlanner(tmp_path)
    planner.reject(68, 1001)
    planner.reject(68, 1002)
    strategy.race_planner = planner
    forced_state = make_state(
        turn=68,
        commands=FORCED_RACE_COMMANDS,
        live_data_set={
            "live_performance_info": performance(dance=99),
            "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
        },
        extra_data={
            "race_condition_array": [
                {"program_id": 1001},
                {"program_id": 1002},
            ],
        },
    )
    normal_state = make_state(
        turn=69,
        commands=[training(101)],
        live_data_set={
            "live_performance_info": performance(dance=99),
            "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
        },
    )

    exhausted = strategy.next_decision(forced_state, PRESET)
    normal = strategy.next_decision(normal_state, PRESET)

    assert exhausted.action == "idle"
    assert exhausted.reason == (
        "forced race turn 68: server rejected every offered program"
    )
    assert normal.action == "live_square"


def test_idle_reason_names_the_unresolvable_race(monkeypatch):
    """`idle` stops the run; the old reason was the useless string "no action"."""
    strategy = make_strategy(monkeypatch)
    state = make_state(turn=68, commands=FORCED_RACE_COMMANDS)

    decision = strategy.next_decision(state, PRESET)

    assert decision.action == "idle"
    assert "4:401" in decision.reason
    assert "race_condition_array" in decision.reason


def test_idle_description_treats_missing_is_enable_as_enabled(monkeypatch):
    strategy = make_strategy(monkeypatch)
    detail = strategy._describe_commands({
        "home_info": {"command_info_array": [{"command_type": 1, "command_id": 101}]}
    })

    assert "1:101" in detail
    assert "disabled" not in detail


def test_handlers_are_registered_under_their_action_names(monkeypatch):
    handlers = make_strategy(monkeypatch).extra_action_handlers()
    assert handlers["live_square"] is run_live_square
    assert handlers["live_start"] is run_live_start


def test_decision_payloads_carry_current_turn(monkeypatch):
    """runner._record_action does payload["current_turn"] -- a KeyError there
    kills the run."""
    strategy = make_strategy(monkeypatch)
    live = strategy.next_decision(make_state(turn=24, playing_state=LIVE_TOP_PLAYING_STATE), PRESET)
    assert live.payload["current_turn"] == 24

    square = strategy.next_decision(make_state(turn=11, live_data_set={
        "live_performance_info": performance(dance=99),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
    }), PRESET)
    assert square.payload["current_turn"] == 11
