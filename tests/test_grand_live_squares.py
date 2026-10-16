"""Grand Live (scenario 3) wiring, live_data_set model, and square picker.

Fixtures mirror the shapes captured on 2026-07-26 in
uma_runtime/captures/gl_flow_01.jsonl and the DTOs in
docs/scenarios/grand-live-endpoints.md.
"""

import pytest

from career_bot.scenarios.grand_live import live_state as live_state_mod
from career_bot.scenarios.grand_live import squares as squares_mod
import uma_data
from career_bot.scenarios.grand_live.live_state import LiveState, live_data_set_of
from career_bot.scenarios.grand_live.squares import (
    SquareCatalog,
    choose_square,
    rank_squares,
    resolve_weights,
)
from career_bot.scenarios.grand_live.song_policy import SquarePolicyContext


# Real rows from master.mdb: 11001 is a 10-Dance Parameter square, 20024 a
# 15-Mental Skill square, 40000 the first of the 21 rare song squares.
SQUARE_ROWS = {
    11001: {"id": 11001, "square_type": 1, "cost": {1: 10}, "cost_total": 10, "master_bonus_id": 11001},
    11002: {"id": 11002, "square_type": 1, "cost": {2: 10}, "cost_total": 10, "master_bonus_id": 11002},
    11003: {"id": 11003, "square_type": 1, "cost": {3: 10}, "cost_total": 10, "master_bonus_id": 11003},
    11004: {"id": 11004, "square_type": 1, "cost": {4: 10}, "cost_total": 10, "master_bonus_id": 11004},
    20024: {"id": 20024, "square_type": 2, "cost": {5: 15}, "cost_total": 15, "master_bonus_id": 20004},
    30001: {"id": 30001, "square_type": 3, "cost": {5: 30}, "cost_total": 30, "master_bonus_id": 30001},
    40000: {"id": 40000, "square_type": 4, "cost": {2: 21, 4: 21}, "cost_total": 42, "master_bonus_id": 40000},
    40001: {"id": 40001, "square_type": 4, "cost": {3: 32, 5: 12}, "cost_total": 44, "master_bonus_id": 40001},
    40002: {"id": 40002, "square_type": 4, "cost": {1: 32, 4: 12}, "cost_total": 44, "master_bonus_id": 40002},
    40004: {"id": 40004, "square_type": 4, "cost": {1: 21, 3: 21, 5: 21}, "cost_total": 63, "master_bonus_id": 40004},
    40007: {"id": 40007, "square_type": 4, "cost": {2: 21, 5: 21}, "cost_total": 42, "master_bonus_id": 40007},
    40018: {"id": 40018, "square_type": 4, "cost": {1: 26, 4: 42}, "cost_total": 68, "master_bonus_id": 40018},
    40020: {"id": 40020, "square_type": 4, "cost": {1: 21, 4: 21}, "cost_total": 42, "master_bonus_id": 40020},
}

LIVE_ROWS = [
    {"id": 1, "live_type": 1, "turn_num": 24},
    {"id": 2, "live_type": 2, "turn_num": 36},
    {"id": 3, "live_type": 3, "turn_num": 48},
    {"id": 4, "live_type": 4, "turn_num": 60},
    {"id": 5, "live_type": 10, "turn_num": 72},
]


def make_catalog(monkeypatch, *, success=True, squares=None, lives=None):
    payload = {
        "success": success,
        "squares": SQUARE_ROWS if squares is None else squares,
        "bonuses": {},
        "lives": LIVE_ROWS if lives is None else lives,
    }
    monkeypatch.setattr(uma_data, "load_live_squares", lambda *a, **k: payload)
    return SquareCatalog(".")


def performance(dance=0, passion=0, vocal=0, visual=0, mental=0):
    return {
        "dance": dance, "max_dance": 100,
        "passion": passion, "max_passion": 100,
        "vocal": vocal, "max_vocal": 100,
        "visual": visual, "max_visual": 100,
        "mental": mental, "max_mental": 100,
    }


# --- P0: routing -------------------------------------------------------------


def test_scenario_3_routes_to_single_mode_live():
    """The strategy declares its own prefix; endpoint_prefix_by_id() is what
    ApiRoutes._single_mode_prefix resolves against, so no client-side scenario
    table exists to edit."""
    from career_bot.scenarios import endpoint_prefix_by_id
    from career_bot.scenarios.grand_live import GrandLiveStrategy

    assert GrandLiveStrategy.endpoint_prefix == "single_mode_live"
    assert endpoint_prefix_by_id()[3] == "single_mode_live"


def test_grand_live_is_offered_to_the_frontend_picker():
    """The scenario dropdown renders /api/scenarios -> runnable_scenarios()."""
    from career_bot.scenarios import runnable_scenarios

    assert {"id": 3, "label": "Grand Live"} in runnable_scenarios()


def test_client_builds_grand_live_endpoints():
    from uma_api.client import UmaClient

    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = 3
    assert client._single_mode_ep("exec_command") == "single_mode_live/exec_command"
    assert client._single_mode_ep("master_square") == "single_mode_live/master_square"
    # Live-only routes pin scenario 3 even while another career is loaded.
    client.current_scenario_id = 4
    assert client._single_mode_ep("master_square", 3) == "single_mode_live/master_square"
    assert client._single_mode_ep("exec_command") == "single_mode_free/exec_command"


def test_grand_live_endpoints_are_paced_like_a_human():
    from career_bot.delay import _BASE_DELAYS, _SQUARE_ENDPOINT_DELAY, GateKeeper

    pacing = GateKeeper._pacing_name
    # _pacing_name keys by verb, so the career routes already share MANT's
    # profiles once the prefix changes.
    assert pacing(None, "single_mode_live/start") == "start_career"
    assert pacing(None, "single_mode_live/load") == "load_career"
    assert pacing(None, "single_mode_live/finish") == "finish_career"
    assert pacing(None, "single_mode_live/exec_command") == "exec_command"
    assert pacing(None, "single_mode_live/master_square") == "master_square"
    # Grand Live adds four pacing names; the square verbs share one measured profile.
    for name in ("master_square", "live_start", "reserve_square", "lottery_square"):
        assert name in _BASE_DELAYS
    for name in ("master_square", "reserve_square", "lottery_square"):
        assert _BASE_DELAYS[name] is _SQUARE_ENDPOINT_DELAY


# --- P1: live_data_set model -------------------------------------------------


def test_live_data_set_of_accepts_wrapped_and_bare():
    payload = {"live_performance_info": performance(dance=5)}
    assert live_data_set_of({"data": {"live_data_set": payload}}) == payload
    assert live_data_set_of({"live_data_set": payload}) == payload
    assert live_data_set_of({"data": {}}) == {}
    assert live_data_set_of(None) == {}


def test_update_merges_and_keeps_absent_keys():
    """A response that omits a key must not wipe it -- the dump could not tell
    us whether every response ships a complete live_data_set."""
    state = LiveState({
        "live_performance_info": performance(dance=30, passion=25),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}],
        "reserve_square_id": 40000,
    })
    state.update({"live_performance_info": performance(dance=9)})

    assert state.tokens[live_state_mod.DANCE] == 9
    assert state.tokens[live_state_mod.PASSION] == 0
    assert state.next_square_ids == [11001]
    assert state.reserve_square_id == 40000

    state.update({"next_square_info_array": None, "reserve_square_id": None})
    assert state.next_square_ids == []
    assert state.reserve_square_id == 0


def test_tokens_afford_and_shortfall():
    state = LiveState({"live_performance_info": performance(passion=21, visual=20)})
    assert state.can_afford({2: 21})
    assert not state.can_afford(SQUARE_ROWS[40000]["cost"])
    assert state.shortfall(SQUARE_ROWS[40000]["cost"]) == {4: 1}
    assert state.shortfall({2: 21}) == {}


def test_command_token_gain_reads_command_info_array():
    state = LiveState({
        "command_info_array": [
            {
                "command_type": 1,
                "command_id": 101,
                "performance_inc_dec_info_array": [
                    {"performance_type": 1, "value": 4},
                    {"performance_type": 3, "value": 2},
                ],
            }
        ]
    })
    assert state.command_token_gain(1, 101) == {1: 4, 3: 2}
    assert state.total_token_gain(1, 101) == 6
    assert state.command_token_gain(1, 106) == {}


def test_great_success_and_capped_types():
    state = LiveState({
        "live_result_array": [{"live_type": 1, "result_state": 2}, {"live_type": 2, "result_state": 1}],
        "not_up_parameter_info": {"performance_type_array": [3, 5]},
    })
    assert state.great_success_count == 1
    assert state.capped_types == {3, 5}

    state.update_from({
        "data": {
            "chara_info": {"turn": 10},
            "live_data_set": {},
            "not_up_parameter_info": {"performance_type_array": [1, 4]},
        }
    })
    assert state.capped_types == {1, 4}


# --- P1: square picker -------------------------------------------------------


def test_catalog_exposes_live_schedule(monkeypatch):
    catalog = make_catalog(monkeypatch)
    assert catalog.live_turns == [24, 36, 48, 60, 72]
    assert catalog.is_live_turn(72)
    assert not catalog.is_live_turn(71)


def test_picks_song_over_cheaper_common_squares(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=50, passion=50, visual=50, mental=50)})

    square_id, reason = choose_square(catalog, state, offered_ids=[11001, 20024, 30001, 40000])

    assert square_id == 40000
    assert "Song" in reason


def test_falls_back_to_best_affordable_tier(monkeypatch):
    """Song unaffordable -> take the Parameter square before Skill."""
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=10, mental=15)})

    square_id, reason = choose_square(catalog, state, offered_ids=[11001, 20024, 40000])

    assert square_id == 11001
    assert "Parameter" in reason


def test_cheapest_wins_inside_a_tier(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(passion=99, visual=99, vocal=99, mental=99)})

    ranked = rank_squares(catalog, state, offered_ids=[40001, 40000])

    assert [item["square_id"] for item in ranked["affordable"]] == [40000, 40001]


def test_no_affordable_square_reports_shortfall(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(passion=21, visual=20)})

    square_id, reason = choose_square(catalog, state, offered_ids=[40000])

    assert square_id is None
    assert "cannot afford" in reason and "4:1" in reason


def test_unknown_square_id_is_reported_not_guessed(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99)})

    ranked = rank_squares(catalog, state, offered_ids=[99999])
    assert ranked["unknown"] == [99999]

    square_id, reason = choose_square(catalog, state, offered_ids=[99999])
    assert square_id is None
    assert "not in master.mdb" in reason


def test_missing_master_mdb_degrades_quietly(monkeypatch):
    catalog = make_catalog(monkeypatch, success=False, squares={}, lives=[])
    state = LiveState({"live_performance_info": performance(dance=99)})

    square_id, reason = choose_square(catalog, state, offered_ids=[11001])

    assert square_id is None
    assert "no square catalog" in reason


def test_no_offer_returns_no_square(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99)})
    assert choose_square(catalog, state, offered_ids=[]) == (None, "no squares offered")


def test_bot_config_can_override_tier_weights(monkeypatch):
    """The scenario-3 bot config is flattened into the preset, so the four
    grand_live_*_square_weight keys arrive top-level."""
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=50, passion=50, visual=50, mental=50)})
    preset = {"grand_live_song_square_weight": 1, "grand_live_hp_square_weight": 900}

    assert resolve_weights(preset)[4] == 1
    square_id, _ = choose_square(catalog, state, offered_ids=[30001, 40000], preset=preset)
    assert square_id == 30001


def test_bot_config_defaults_match_the_picker_defaults():
    """GRAND_LIVE_DEFAULTS and DEFAULT_SQUARE_TYPE_WEIGHTS must not drift."""
    from career_bot.bot_config import GRAND_LIVE_DEFAULTS
    from career_bot.scenarios.grand_live.squares import (
        DEFAULT_SQUARE_TYPE_WEIGHTS,
        PRESET_WEIGHT_KEYS,
    )

    assert set(PRESET_WEIGHT_KEYS.values()).issubset(GRAND_LIVE_DEFAULTS)
    for square_type, preset_key in PRESET_WEIGHT_KEYS.items():
        assert GRAND_LIVE_DEFAULTS[preset_key] == DEFAULT_SQUARE_TYPE_WEIGHTS[square_type]
    assert resolve_weights(GRAND_LIVE_DEFAULTS) == DEFAULT_SQUARE_TYPE_WEIGHTS


def test_grand_live_bot_config_reaches_the_preset():
    from career_bot.bot_config import GRAND_LIVE_SCENARIO_ID, apply_bot_config_to_preset

    preset = apply_bot_config_to_preset({"name": "x"}, scenario_id=GRAND_LIVE_SCENARIO_ID)

    assert preset["grand_live_song_square_weight"] == 400
    assert preset["grand_live_parameter_square_weight"] == 200
    assert preset["grand_live_skill_square_weight"] == 100
    assert preset["grand_live_hp_square_weight"] == 50
    assert preset["grand_live_contextual_square_policy"] is True
    assert preset["grand_live_rest_score"] == 1.05
    # MANT keys must not leak in when scenario 3 is selected.
    assert "score_value" not in preset


def test_grand_live_is_offered_in_bot_config_scenarios():
    from career_bot.bot_config import SCENARIOS, bot_config_field_specs, default_bot_config

    assert SCENARIOS["3"]["scenario_id"] == 3
    assert "3" in default_bot_config()["scenarios"]
    keys = {spec["key"] for spec in bot_config_field_specs()["3"]}
    assert "grand_live_song_square_weight" in keys


def test_offered_ids_default_to_live_state(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({
        "live_performance_info": performance(dance=50, passion=50, visual=50, mental=50),
        "next_square_info_array": [{"square_id": 11001, "square_num": 1}, {"square_id": 40000, "square_num": 2}],
    })

    square_id, _ = choose_square(catalog, state)

    assert square_id == 40000


@pytest.mark.parametrize("turn", [24, 36, 48, 60, 72])
def test_live_turns_match_the_capture(monkeypatch, turn):
    """live_start fired on exactly these turns in gl_flow_01.jsonl."""
    assert make_catalog(monkeypatch).is_live_turn(turn)


# --- tuned contextual square policy -----------------------------------------


def test_contextual_policy_buys_cheapest_common_path_square(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=20, mental=20)})

    square_id, reason = choose_square(
        catalog,
        state,
        offered_ids=[11001, 20024],
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 11001
    assert "cheap common" in reason


@pytest.mark.parametrize("disabled", [False, 0, 0.0, "", "false", "0", "no", "off"])
def test_false_like_values_disable_contextual_policy(monkeypatch, disabled):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=20, mental=20)})
    monkeypatch.setattr(
        squares_mod,
        "choose_contextual_square",
        lambda *_args: (_ for _ in ()).throw(AssertionError("contextual policy should be off")),
    )

    square_id, _ = choose_square(
        catalog,
        state,
        offered_ids=[11001, 20024],
        preset={"grand_live_contextual_square_policy": disabled},
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 11001


def test_contextual_policy_defaults_to_on_when_key_is_absent(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=20)})
    calls = []
    monkeypatch.setattr(
        squares_mod,
        "choose_contextual_square",
        lambda affordable, *_args: (calls.append(affordable), (affordable[0], "contextual"))[1],
    )

    square_id, reason = choose_square(
        catalog,
        state,
        offered_ids=[11001],
        preset={},
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 11001
    assert calls
    assert "contextual" in reason


def test_contextual_common_tiebreak_spends_larger_inventory(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=10, vocal=50)})

    square_id, _ = choose_square(
        catalog,
        state,
        offered_ids=[11001, 11003],
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 11003


def test_contextual_common_close_tiebreak_preserves_da_and_vi(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=10, passion=10, vocal=10, visual=10, mental=10)})

    square_id, _ = choose_square(
        catalog,
        state,
        offered_ids=[11002, 11003, 11004],
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 11003  # Vo > Pa > Me > Da > Vi when inventories are close.


def test_contextual_session_1_chases_friendship_targets_before_40000(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99, passion=99, vocal=99, visual=99, mental=99)})

    square_id, reason = choose_square(
        catalog,
        state,
        offered_ids=[40000, 40002],
        context=SquarePolicyContext(turn=13),
    )

    assert square_id == 40002
    assert "unique song" in reason


def test_contextual_tier1_sp_only_when_no_tier0_offer(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99, passion=99, vocal=99, visual=99, mental=99)})

    with_tier0, _ = choose_square(catalog, state, offered_ids=[40007, 40018], context=SquarePolicyContext(turn=50))
    no_tier0, _ = choose_square(catalog, state, offered_ids=[40007, 40020], context=SquarePolicyContext(turn=50))

    assert with_tier0 == 40018
    assert no_tier0 == 40007


def test_contextual_panic_buy_prefers_cheaper_unique_near_concert(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99, passion=99, vocal=99, visual=99, mental=99)})

    square_id, reason = choose_square(
        catalog,
        state,
        offered_ids=[40004, 40000],
        context=SquarePolicyContext(turn=22, session_song_counts={1: 1}),
    )

    assert square_id == 40000
    assert "panic unique" in reason


def test_contextual_session_1_holds_after_targets_plus_one_other(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99, passion=99, vocal=99, visual=99, mental=99)})
    context = SquarePolicyContext(turn=20, bought_song_ids={40001, 40002, 40003, 40000}, session_song_counts={1: 4})

    square_id, reason = choose_square(catalog, state, offered_ids=[11001, 20024], context=context)

    assert square_id is None
    assert "holding" in reason


def test_contextual_finale_prefers_parameter_common_dump(monkeypatch):
    catalog = make_catalog(monkeypatch)
    state = LiveState({"live_performance_info": performance(dance=99, passion=99, visual=99, mental=99)})

    square_id, reason = choose_square(
        catalog,
        state,
        offered_ids=[11001, 40000],
        context=SquarePolicyContext(turn=74),
    )

    assert square_id == 11001
    assert "finale" in reason
