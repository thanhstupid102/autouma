import json
import pathlib

import pytest

import backend.app.domain.career_selection as career_selection
import backend.app.domain.rank_point as rank_point
import uma_data
from backend.app.routers.careers.schemas.career import StartCareerRequest
from tests._helpers import _make_session

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_main_loads_succession_relation_globals(monkeypatch):
    monkeypatch.setattr(uma_data, "load_succession_relations", lambda base_dir: {
        "success": True,
        "points": {101: 2},
        "members": {1004: {101}},
    })
    monkeypatch.setattr(rank_point, "succession_relation_points", {}, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_members", {}, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_loaded", False, raising=False)

    assert rank_point.load_succession_relation_data() is True
    assert rank_point.succession_relation_points == {101: 2}
    assert rank_point.succession_relation_members == {1004: {101}}
    assert rank_point.succession_relation_loaded is True


def test_g1_win_saddle_id_set_is_empty_without_master_data(monkeypatch):
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {101, 102}, raising=False)
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", False, raising=False)

    assert rank_point.g1_win_saddle_id_set([101, 102]) == set()


@pytest.mark.parametrize(("tree_source", "expected_bonus"), [
    (
        {
            "win_saddle_id_array": [101, 102],
            "succession_chara_array": [
                {"position_id": 10, "win_saddle_id_array": [201, 202]},
            ],
        },
        6,
    ),
    (
        {
            "win_saddle_id_array": [101],
            "succession_chara_array": [
                {"position_id": 10, "win_saddle_id_array": [202]},
            ],
        },
        0,
    ),
    (
        {
            "win_saddle_id_array": [104],
            "succession_chara_array": [
                {"position_id": 10, "win_saddle_id_array": [201]},
            ],
        },
        0,
    ),
    (
        {
            "win_saddle_id_array": [101, 102, 103],
            "succession_chara_array": [
                {"position_id": 10, "win_saddle_id_array": [201, 202]},
                {"position_id": 20, "win_saddle_id_array": [202, 203]},
            ],
        },
        12,
    ),
    (
        {
            "win_saddle_id_array": [101, 102],
            "succession_chara_array": [
                {"position_id": 10, "win_saddle_id_array": [201]},
                {"position_id": 11, "win_saddle_id_array": [201, 202]},
                {"position_id": 12, "win_saddle_id_array": [201, 202]},
                {"position_id": 21, "win_saddle_id_array": [201, 202]},
                {"position_id": 22, "win_saddle_id_array": [201, 202]},
            ],
        },
        3,
    ),
], ids=[
    "two-shared-g1-wins",
    "no-parent-grandparent-overlap",
    "shared-non-g1-win",
    "both-direct-grandparents",
    "great-grandparents-ignored",
])
def test_parent_shared_g1_bonus(monkeypatch, tree_source, expected_bonus):
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {101, 102, 103}, raising=False)
    monkeypatch.setattr(rank_point, "win_saddle_groups", {
        101: 10, 102: 20, 103: 30, 104: 10,
        201: 10, 202: 20, 203: 30,
    }, raising=False)
    monkeypatch.setattr(rank_point, "win_saddle_types", {
        101: 3, 102: 3, 103: 3, 104: 2,
        201: 2, 202: 2, 203: 2,
    }, raising=False)
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True, raising=False)

    assert rank_point.parent_shared_g1_bonus(tree_source) == expected_bonus


def test_parent_pair_g1_bonus_is_directional_and_matches_group_not_id(monkeypatch):
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {101}, raising=False)
    monkeypatch.setattr(
        rank_point, "win_saddle_groups", {101: 10, 201: 10}, raising=False
    )
    monkeypatch.setattr(
        rank_point, "win_saddle_types", {101: 3, 201: 2}, raising=False
    )
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True, raising=False)
    parent_1 = {"win_saddle_id_array": [101]}
    parent_2 = {"win_saddle_id_array": [201]}

    assert rank_point.parent_pair_shared_g1_bonus(parent_1, parent_2) == 3
    assert rank_point.parent_pair_shared_g1_bonus(parent_2, parent_1) == 0


def test_selected_succession_rank_point_ignores_rank_score(monkeypatch):
    session = _make_session()
    session.parent_rank_points = {
        4969: {"rank": 14, "rank_score": 14064},
        3991: {"rank": 17, "rank_score": 18732},
    }
    session.parent_cards = {}
    session.start_state = {"succession_rank_point": 2107}
    req = StartCareerRequest(
        card_id=100402,
        support_card_ids=[30078, 30028, 20041, 30097, 30054],
        friend_viewer_id=887798844119,
        friend_card_id=30017,
        parent_id_1=4969,
        parent_id_2=3991,
    )

    assert rank_point.selected_succession_rank_point(session, req) == 2107


def test_selected_succession_rank_point_adds_precomputed_shared_g1_bonus(monkeypatch):
    session = _make_session()
    session.parent_cards = {
        4969: [101401, 102602, 102001, 102001, 101401, 100402, 106801],
        3991: [102001, 102602, 101502, 102001, 101401, 101101, 102001],
    }
    session.parent_g1_wins = {4969: 6, 3991: 3}
    monkeypatch.setattr(rank_point, "succession_relation_points", {1: 17, 2: 16, 3: 24}, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_members", {
        1004: {1, 2},
        1014: {1, 3},
        1020: {2, 3},
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_loaded", True, raising=False)
    session.start_state = {"succession_rank_point": 2107}
    req = StartCareerRequest(
        card_id=100402,
        support_card_ids=[30078, 30028, 20041, 30097, 30054],
        friend_viewer_id=887798844119,
        friend_card_id=30017,
        parent_id_1=4969,
        parent_id_2=3991,
    )

    assert rank_point.selected_succession_rank_point(session, req) == 66


def test_succession_rank_point_matches_four_real_20260714_requests(monkeypatch):
    fixture_path = ROOT / "tests" / "fixtures" / "succession_rank_point_20260714.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    saddle_data = {
        int(saddle_id): values
        for saddle_id, values in fixture["win_saddles"].items()
    }
    monkeypatch.setattr(rank_point, "succession_relation_points", {
        int(relation_id): int(points)
        for relation_id, points in fixture["relation_points"].items()
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_members", {
        int(chara_id): set(relation_ids)
        for chara_id, relation_ids in fixture["relation_members"].items()
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_loaded", True, raising=False)
    monkeypatch.setattr(rank_point, "win_saddle_groups", {
        saddle_id: int(values[0]) for saddle_id, values in saddle_data.items()
    }, raising=False)
    monkeypatch.setattr(rank_point, "win_saddle_types", {
        saddle_id: int(values[1]) for saddle_id, values in saddle_data.items()
    }, raising=False)
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {
        saddle_id for saddle_id, values in saddle_data.items()
        if int(values[1]) == 3
    }, raising=False)
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True, raising=False)
    monkeypatch.setattr(
        rank_point, "reload_rank_point_master_data_if_changed", lambda: False
    )
    expected_breakdowns = [
        # pair relations, triple relations, all G1 bonus, P1->P2 G1 bonus
        (83, 79, 189, 51),
        (70, 61, 69, 15),
        (71, 63, 135, 27),
        (45, 25, 87, 12),
    ]

    for case, expected_parts in zip(fixture["cases"], expected_breakdowns):
        session = _make_session()
        for parent_id in case["parent_ids"]:
            source = fixture["parents"][str(parent_id)]
            session.parent_g1_sources[parent_id] = source
            session.parent_cards[parent_id] = [
                int(source["card_id"]),
                *[
                    int(ancestor["card_id"])
                    for ancestor in source["succession_chara_array"]
                ],
            ]
        req = StartCareerRequest(
            card_id=case["trainee_card_id"],
            support_card_ids=[30028, 30074, 20027, 20031, 30066],
            friend_viewer_id=1,
            friend_card_id=30097,
            parent_id_1=case["parent_ids"][0],
            parent_id_2=case["parent_ids"][1],
        )

        components = rank_point.selected_succession_rank_point_components(session, req)

        pair_total, triple_total, g1_total, parent_pair_g1 = expected_parts
        assert sum(components["relation_pairs"].values()) == pair_total
        assert sum(components["relation_triples"].values()) == triple_total
        assert components["g1_bonus_total"] == g1_total
        assert components["parent_pair_g1_bonus"] == parent_pair_g1
        assert components["computed"] == case["expected"]

    # CalcRelationPoint's three-way helper explicitly rejects duplicate IDs.
    assert components["relation_triples"]["t_p2_gp20"] == 0


def test_start_validation_allows_ancestor_lineage_containing_trainee(monkeypatch):
    session = _make_session()
    session.parent_cards = {
        4969: [101401, 102602, 102001, 100402],
        3991: [102001, 102602, 101502],
    }
    monkeypatch.setattr(rank_point, "support_map", {})
    req = StartCareerRequest(
        card_id=100402,
        support_card_ids=[30078, 30028, 20041, 30097, 30054],
        friend_viewer_id=887798844119,
        friend_card_id=30017,
        parent_id_1=4969,
        parent_id_2=3991,
    )

    assert career_selection.validate_start_selection(session, req) is None


def test_start_validation_rejects_direct_parent_same_as_trainee(monkeypatch):
    session = _make_session()
    session.parent_cards = {
        4969: [100402, 102602, 102001],
        3991: [102001, 102602, 101502],
    }
    monkeypatch.setattr(rank_point, "support_map", {})
    req = StartCareerRequest(
        card_id=100402,
        support_card_ids=[30078, 30028, 20041, 30097, 30054],
        friend_viewer_id=887798844119,
        friend_card_id=30017,
        parent_id_1=4969,
        parent_id_2=3991,
    )

    assert career_selection.validate_start_selection(session, req) == "Selected direct parent is same character as trainee"
