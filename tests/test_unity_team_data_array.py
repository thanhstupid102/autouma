import json
from pathlib import Path

import pytest

from career_bot.scenarios.unity_cup.team_roster import TeamRosterBuilder
import uma_data


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "unity_cup_team_edit_state.json"

# Trainee (chara_id 1051, derived from chara_info.card_id 105101) + the 9
# evaluation_info_array entries with member_state == 1, from a real client
# capture right before single_mode_team/team_edit (raw.jsonl line 186,
# 2026-07-08).
EXPECTED_CHARA_IDS = {1051, 1010, 1057, 1009, 1056, 1022, 1060, 1068, 1030, 1052}

# Running styles the real client sent for these chara_ids on the very same
# team_edit call (verified via the opponent_list echo a few requests later,
# raw.jsonl line 190).
RUNNING_STYLE_EXPECTATIONS = {
    1057: 4,
    1068: 1,
    1056: 3,
    1030: 2,
    1052: 3,
    1009: 2,
}


def load_state():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def master_mdb_available():
    return uma_data.default_master_mdb_path().exists()


def test_team_data_array_roster_and_distance_bounds(tmp_path):
    team = TeamRosterBuilder(tmp_path).build(load_state())

    assert len(team) == 10
    assert {row["chara_id"] for row in team} == EXPECTED_CHARA_IDS

    by_distance = {}
    for row in team:
        by_distance.setdefault(row["distance_type"], []).append(row)

    assert set(by_distance) == {1, 2, 3, 4, 5}
    for distance_type, rows in by_distance.items():
        assert 1 <= len(rows) <= 6
        member_ids = sorted(row["member_id"] for row in rows)
        assert member_ids == list(range(1, len(rows) + 1))

    for row in team:
        assert row["running_style"] in (1, 2, 3, 4)


@pytest.mark.skipif(not master_mdb_available(), reason="requires local master.mdb")
def test_team_data_array_dirt_specialist_goes_to_distance_5(tmp_path):
    # chara 1052 has proper_ground_dirt=7 / proper_ground_turf=1 in
    # single_mode_scout_chara -- the only dirt specialist on the roster.
    team = TeamRosterBuilder(tmp_path).build(load_state())

    by_chara = {row["chara_id"]: row for row in team}
    assert by_chara[1052]["distance_type"] == 5


@pytest.mark.skipif(not master_mdb_available(), reason="requires local master.mdb")
def test_team_data_array_running_styles_match_captured_client(tmp_path):
    team = TeamRosterBuilder(tmp_path).build(load_state())

    by_chara = {row["chara_id"]: row for row in team}
    for chara_id, expected_style in RUNNING_STYLE_EXPECTATIONS.items():
        assert by_chara[chara_id]["running_style"] == expected_style


TRAINEE_APTITUDE = {
    "proper_distance_short": 4,
    "proper_distance_mile": 4,
    "proper_distance_middle": 4,
    "proper_distance_long": 4,
    "proper_running_style_nige": 4,
    "proper_running_style_senko": 4,
    "proper_running_style_sashi": 4,
    "proper_running_style_oikomi": 4,
    "proper_ground_turf": 4,
    "proper_ground_dirt": 4,
}

TRAINEE_CARD_ID = 105100  # -> chara_id 1051 via the card_id // 100 fallback
TRAINEE_CHARA_ID = TRAINEE_CARD_ID // 100


def overflow_state(scout_chara_ids):
    # Mirrors turn 48 of career_log_lewpie_20260709_182004.json: trainee +
    # 15 scouted (member_state == 1) evaluation_info_array rows == 16 total,
    # one more than the team-edit screen's 15 slots (5 distance_type x
    # MAX_MEMBERS_PER_DISTANCE=3). Before the fix, TeamRosterBuilder's
    # overflow fallback put a 4th member on one distance and
    # single_mode_team/team_edit rejected the payload with result_code 205
    # (retried 40+ times, career stuck).
    return {
        "data": {
            "chara_info": {"card_id": TRAINEE_CARD_ID, "turn": 48, **TRAINEE_APTITUDE},
            "team_data_set": {
                "evaluation_info_array": [
                    {"target_id": i, "chara_id": chara_id, "member_state": 1}
                    for i, chara_id in enumerate(scout_chara_ids, start=1)
                ],
            },
        },
    }


def bare_builder(tmp_path, scout_aptitudes=None):
    builder = TeamRosterBuilder(tmp_path)
    # Force _scout_aptitude_map()/_card_chara_map() to behave as if
    # master.mdb is unavailable, so these tests are deterministic
    # regardless of whether this machine has a real master.mdb installed.
    builder._scout_aptitude_cache = scout_aptitudes or {}
    builder._card_chara_map_cache = {}
    return builder


def test_team_roster_overflow_benches_down_to_fifteen(tmp_path):
    scout_chara_ids = list(range(2001, 2016))  # 15 scouts + trainee == 16
    team = bare_builder(tmp_path).build(overflow_state(scout_chara_ids))

    assert len(team) == 15
    chara_ids = {row["chara_id"] for row in team}
    assert TRAINEE_CHARA_ID in chara_ids  # trainee is never benched
    assert chara_ids <= {TRAINEE_CHARA_ID, *scout_chara_ids}

    by_distance = {}
    for row in team:
        by_distance.setdefault(row["distance_type"], []).append(row)
    assert set(by_distance) == {1, 2, 3, 4, 5}
    for rows in by_distance.values():
        assert 1 <= len(rows) <= 3
        member_ids = sorted(row["member_id"] for row in rows)
        assert member_ids == list(range(1, len(rows) + 1))
        assert all(row["member_id"] <= 3 for row in rows)


def test_team_roster_overflow_benches_weakest_scout(tmp_path):
    scout_chara_ids = list(range(2001, 2016))  # 15 scouts + trainee == 16
    weakest_id = 2007
    scout_aptitudes = {
        chara_id: ({key: 1 for key in TRAINEE_APTITUDE} if chara_id == weakest_id
                   else {key: 7 for key in TRAINEE_APTITUDE})
        for chara_id in scout_chara_ids
    }
    team = bare_builder(tmp_path, scout_aptitudes).build(overflow_state(scout_chara_ids))

    chara_ids = {row["chara_id"] for row in team}
    assert len(team) == 15
    assert weakest_id not in chara_ids
    assert chara_ids == {TRAINEE_CHARA_ID, *scout_chara_ids} - {weakest_id}
