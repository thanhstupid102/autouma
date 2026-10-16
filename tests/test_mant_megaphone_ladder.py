"""The NON-summer megaphone ladder -- the branch that governs turns 1-64.

The pre-existing megaphone tests only reach two of the three branches of
``_megaphone_fresh_target``: the summer-camp one (``test_mant_items.py``, turn 37)
and the post-T65 ``_megaphone_priority_pick`` short-circuit
(``test_late_aggressive.py``, turn 71). Everything the ladder does in between --
``_megaphone_score_thresholds`` / ``_megaphone_pressure`` /
``_megaphone_score_pick`` / ``_megaphone_dump_pick`` /
``_megaphone_tier_from_score`` / ``_megaphone_upgrade_pick`` -- had no
assertions at all (§13.6 "known coverage gaps"). This module pins it.

Turn 45 is the reference turn: it is outside every summer hold window
(23-36, 47-60) and below ``SUMMER_ITEM_RELEASE_TURN`` (65), so
``_available_to_use`` reserves nothing and the plain ladder runs.
"""
from career_bot.scenarios.mant.items import MantItemManager


# The stock (small, medium, large) gates -- see test_megaphone_score_thresholds_*.
TIERS = (11.0, 21.0, 35.0)
FULL_TRIO = {"Coaching Megaphone": 1, "Motivating Megaphone": 1, "Empowering Megaphone": 1}
TURN = 45  # non-summer, non-hold, below the T65 release


def _training(stat=0, skill_point=0):
    """A training command worth `stat` raw stat and `skill_point` skill points."""
    rows = []
    if stat:
        rows.append({"target_type": 1, "value": stat})
    if skill_point:
        rows.append({"target_type": 30, "value": skill_point})
    return {"command_type": 1, "command_id": 101, "params_inc_dec_info_array": rows}


def _state(turn=TURN, race_turns=()):
    return {
        "data": {
            "chara_info": {"turn": turn},
            "free_data_set": {"item_effect_array": []},
            "race_condition_array": [{"turn": t, "program_id": 0} for t in race_turns],
        }
    }


# --------------------------------------------------------------------------
# _megaphone_score_thresholds
# --------------------------------------------------------------------------

def test_megaphone_score_thresholds_default_to_11_21_35():
    manager = MantItemManager()

    assert manager._megaphone_score_thresholds(manager._mant_cfg({})) == TIERS


def test_megaphone_score_thresholds_follow_mant_config():
    manager = MantItemManager()
    cfg = manager._mant_cfg({"mant_config": {
        "mega_small_threshold": 5,
        "mega_medium_threshold": 12,
        "mega_large_threshold": 40,
    }})

    assert manager._megaphone_score_thresholds(cfg) == (5.0, 12.0, 40.0)


# --------------------------------------------------------------------------
# _megaphone_score_pick -- spend what the training score earned
# --------------------------------------------------------------------------

def test_megaphone_score_pick_climbs_one_tier_per_threshold():
    manager = MantItemManager()
    pick = [manager._megaphone_score_pick(score, FULL_TRIO, {}, TURN, TIERS, False)
            for score in (10.9, 11, 20.9, 21, 34.9, 35, 100)]

    assert pick == [
        None,
        ("Coaching Megaphone", 1),
        ("Coaching Megaphone", 1),
        ("Motivating Megaphone", 1),
        ("Motivating Megaphone", 1),
        ("Empowering Megaphone", 1),
        ("Empowering Megaphone", 1),
    ]


def test_megaphone_score_pick_burns_the_motivating_first_when_an_upgrade_pair_is_held():
    """Holding mid+large with room for both: spend the Motivating at medium score
    so the Empowering survives for a bigger training later."""
    manager = MantItemManager()

    assert manager._megaphone_score_pick(35, FULL_TRIO, {}, TURN, TIERS, True) == ("Motivating Megaphone", 1)
    assert manager._megaphone_score_pick(35, FULL_TRIO, {}, TURN, TIERS, False) == ("Empowering Megaphone", 1)
    # The pair rung is still gated on the MEDIUM threshold, not on stock alone.
    assert manager._megaphone_score_pick(20.9, FULL_TRIO, {}, TURN, TIERS, True) == ("Coaching Megaphone", 1)


def test_megaphone_score_pick_steps_down_when_the_earned_tier_is_out_of_stock():
    manager = MantItemManager()

    assert manager._megaphone_score_pick(40, {"Coaching Megaphone": 1}, {}, TURN, TIERS, False) == ("Coaching Megaphone", 1)
    assert manager._megaphone_score_pick(40, {}, {}, TURN, TIERS, False) is None


# --------------------------------------------------------------------------
# _megaphone_dump_pick -- more megaphone-turns than training turns left
# --------------------------------------------------------------------------

def test_megaphone_dump_pick_spends_the_biggest_in_stock_on_a_worthless_training():
    """score 0 earns nothing, but dump mode spends anyway -- biggest first."""
    manager = MantItemManager()

    assert manager._megaphone_dump_pick(0, FULL_TRIO, {}, TURN, TIERS, False) == ("Empowering Megaphone", 1)
    assert manager._megaphone_dump_pick(0, {"Coaching Megaphone": 1, "Empowering Megaphone": 1}, {}, TURN, TIERS, False) == ("Empowering Megaphone", 1)
    assert manager._megaphone_dump_pick(0, {"Coaching Megaphone": 1}, {}, TURN, TIERS, False) == ("Coaching Megaphone", 1)
    assert manager._megaphone_dump_pick(0, {"Motivating Megaphone": 1}, {}, TURN, TIERS, False) == ("Motivating Megaphone", 1)
    assert manager._megaphone_dump_pick(0, {}, {}, TURN, TIERS, False) is None


def test_megaphone_dump_pick_prefers_the_motivating_when_an_upgrade_pair_is_held():
    manager = MantItemManager()
    pair = {"Motivating Megaphone": 1, "Empowering Megaphone": 1}

    assert manager._megaphone_dump_pick(0, pair, {}, TURN, TIERS, True) == ("Motivating Megaphone", 1)
    assert manager._megaphone_dump_pick(0, pair, {}, TURN, TIERS, False) == ("Empowering Megaphone", 1)


def test_megaphone_dump_pick_still_honours_the_score_rungs_below_the_big_one():
    """With no Empowering in stock the score rungs decide, exactly as in
    _megaphone_score_pick, before the unconditional 'spend anything' tail."""
    manager = MantItemManager()
    small_stock = {"Coaching Megaphone": 1, "Motivating Megaphone": 1}

    assert manager._megaphone_dump_pick(25, small_stock, {}, TURN, TIERS, False) == ("Motivating Megaphone", 1)
    assert manager._megaphone_dump_pick(15, small_stock, {}, TURN, TIERS, False) == ("Coaching Megaphone", 1)
    assert manager._megaphone_dump_pick(0, small_stock, {}, TURN, TIERS, False) == ("Coaching Megaphone", 1)


# --------------------------------------------------------------------------
# _megaphone_tier_from_score / _megaphone_upgrade_pick
# --------------------------------------------------------------------------

def test_megaphone_tier_from_score_maps_the_three_gates():
    manager = MantItemManager()

    assert [manager._megaphone_tier_from_score(s, TIERS)
            for s in (0, 10.9, 11, 20.9, 21, 34.9, 35, 100)] == [0, 0, 1, 1, 2, 2, 3, 3]


def test_megaphone_upgrade_pick_takes_the_highest_tier_at_or_below_the_target():
    manager = MantItemManager()

    assert manager._megaphone_upgrade_pick(3, 0, FULL_TRIO, {}, TURN) == ("Empowering Megaphone", 1)
    assert manager._megaphone_upgrade_pick(2, 0, FULL_TRIO, {}, TURN) == ("Motivating Megaphone", 1)
    assert manager._megaphone_upgrade_pick(1, 0, FULL_TRIO, {}, TURN) == ("Coaching Megaphone", 1)
    assert manager._megaphone_upgrade_pick(0, 0, FULL_TRIO, {}, TURN) is None


def test_megaphone_upgrade_pick_steps_down_to_what_is_in_stock():
    manager = MantItemManager()

    assert manager._megaphone_upgrade_pick(3, 0, {"Coaching Megaphone": 1}, {}, TURN) == ("Coaching Megaphone", 1)
    assert manager._megaphone_upgrade_pick(3, 0, {}, {}, TURN) is None


def test_megaphone_upgrade_pick_never_re_uses_the_tier_already_active():
    manager = MantItemManager()

    assert manager._megaphone_upgrade_pick(3, 3, FULL_TRIO, {}, TURN) is None
    assert manager._megaphone_upgrade_pick(3, 2, FULL_TRIO, {}, TURN) == ("Empowering Megaphone", 1)
    assert manager._megaphone_upgrade_pick(2, 1, FULL_TRIO, {}, TURN) == ("Motivating Megaphone", 1)


# --------------------------------------------------------------------------
# _megaphone_pressure -- the stock-vs-remaining-slots signals
# --------------------------------------------------------------------------

def test_remaining_megaphone_slots_counts_training_turns_up_to_77():
    manager = MantItemManager()

    # 74 and 76 are finale race turns and never count as megaphone slots.
    assert manager._remaining_megaphone_slots({}, 70, None, {}) == 5
    assert manager._remaining_megaphone_slots({}, 75, None, {}) == 1
    assert manager._remaining_megaphone_slots({}, 76, None, {}) == 0
    assert manager._remaining_megaphone_slots({}, TURN, None, {}) == 30


def test_megaphone_pressure_is_all_clear_when_stock_fits_the_remaining_slots():
    manager = MantItemManager()

    # 1 Empowering = 2 buffed turns against 5 remaining training turns.
    assert manager._megaphone_pressure({}, {"Empowering Megaphone": 1}, 70, None, {}) == (False, False, False)


def test_megaphone_pressure_flags_dump_mode_when_buff_turns_outlast_the_career():
    manager = MantItemManager()

    # Coaching(4 turns) + Motivating(3) = 7 buffed turns for 5 training turns left.
    assert manager._megaphone_pressure(
        {}, {"Coaching Megaphone": 1, "Motivating Megaphone": 1}, 70, None, {}) == (True, False, False)


def test_megaphone_pressure_flags_inventory_pressure_when_count_reaches_the_slots():
    manager = MantItemManager()
    crowded = {"Coaching Megaphone": 2, "Motivating Megaphone": 2, "Empowering Megaphone": 1}

    # 5 megaphones for 5 slots -> dump mode AND inventory pressure AND the pair.
    assert manager._megaphone_pressure({}, crowded, 70, None, {}) == (True, True, True)


def test_megaphone_pressure_upgrade_pair_needs_both_tiers_and_room_for_two():
    manager = MantItemManager()
    pair = {"Motivating Megaphone": 1, "Empowering Megaphone": 1}

    assert manager._megaphone_pressure({}, pair, 70, None, {})[2] is True
    # Only one training turn left -> no room to spend both, so no pair.
    assert manager._megaphone_pressure({}, pair, 75, None, {})[2] is False
    # Empowering missing -> no pair either.
    assert manager._megaphone_pressure({}, {"Motivating Megaphone": 2}, 70, None, {})[2] is False


# --------------------------------------------------------------------------
# _megaphone_target end-to-end on a turn 1-64 (the whole gap in one place)
# --------------------------------------------------------------------------

def test_megaphone_target_mid_career_follows_the_score_ladder():
    owned = {"Coaching Megaphone": 1, "Empowering Megaphone": 1}  # no upgrade pair
    picks = [MantItemManager()._megaphone_target(_state(), _training(stat=score), owned, {}, {}, TURN, None)
             for score in (10, 11, 21, 35)]

    assert picks == [
        None,                            # under the small gate: hold everything
        ("Coaching Megaphone", 1),
        ("Coaching Megaphone", 1),       # earned the mid tier, but none in stock
        ("Empowering Megaphone", 1),
    ]


def test_megaphone_target_mid_career_holds_the_empowering_while_the_pair_lasts():
    picks = [MantItemManager()._megaphone_target(_state(), _training(stat=score), FULL_TRIO, {}, {}, TURN, None)
             for score in (11, 21, 35)]

    assert picks == [
        ("Coaching Megaphone", 1),
        ("Motivating Megaphone", 1),
        ("Motivating Megaphone", 1),     # upgrade-pair rung, NOT the Empowering
    ]


def test_megaphone_target_mid_career_counts_skill_points_at_half_weight():
    """Outside summer the megaphone score weights skill points 0.5 -- 70 SP is a
    35-point training, i.e. exactly the large gate."""
    owned = {"Coaching Megaphone": 1, "Empowering Megaphone": 1}

    assert MantItemManager()._megaphone_target(
        _state(), _training(skill_point=70), owned, {}, {}, TURN, None) == ("Empowering Megaphone", 1)
    assert MantItemManager()._megaphone_target(
        _state(), _training(skill_point=68), owned, {}, {}, TURN, None) == ("Coaching Megaphone", 1)


def test_megaphone_target_mid_career_dumps_a_megaphone_once_the_slots_run_out():
    """Same weak training, same single Coaching Megaphone: held when there are 30
    training turns left, spent when the race calendar leaves only one."""
    owned = {"Coaching Megaphone": 1}
    weak = _training(stat=5)
    packed_calendar = range(TURN + 1, 77)

    assert MantItemManager()._megaphone_target(_state(), weak, owned, {}, {}, TURN, None) is None
    assert MantItemManager()._megaphone_target(
        _state(race_turns=packed_calendar), weak, owned, {}, {}, TURN, None) == ("Coaching Megaphone", 1)


def test_megaphone_target_mid_career_ignores_non_training_commands():
    """A race command can carry a fat stat payload; a megaphone still buffs only
    TRAINING (command_type 1), so the ladder must never fire on it."""
    fat_race = dict(_training(stat=60), command_type=4, command_id=401)

    assert MantItemManager()._megaphone_target(_state(), fat_race, FULL_TRIO, {}, {}, TURN, None) is None
    # ...the same payload on a training command does earn the top tier.
    assert MantItemManager()._megaphone_target(
        _state(), _training(stat=60), {"Empowering Megaphone": 1}, {}, {}, TURN, None) == ("Empowering Megaphone", 1)
