from types import SimpleNamespace

import backend.app.domain.career_selection as career_selection
import backend.app.domain.rank_point as rank_point


def test_parse_rental_parent_full():
    utc = {"viewer_id": 887798844119, "trained_chara_id": 4662, "card_id": 102001,
           "rank": 17, "rarity": 4, "talent_level": 5, "factor_id_array": [303, 2102]}
    rp = career_selection.parse_rental_parent(utc)
    assert rp["trained_chara_id"] == 4662
    assert rp["card_id"] == 102001
    assert rp["rank"] == 17


def test_parse_rental_parent_empty():
    assert career_selection.parse_rental_parent({}) is None
    assert career_selection.parse_rental_parent(None) is None
    assert career_selection.parse_rental_parent({"card_id": 1}) is None  # no trained_chara_id


def test_build_chara_tree_preserves_grandparents(monkeypatch):
    monkeypatch.setattr(rank_point, "get_factors", lambda ids, owner_card_id=None: [
        {"name": f"factor-{ids[0]}", "stars": 3}
    ] if ids else [])

    tree = rank_point.build_chara_tree({
        "factor_id_array": [1],
        "succession_chara_array": [
            {"position_id": 10, "card_id": 200001, "factor_id_array": [10]},
            {"position_id": 20, "card_id": 200002, "factor_id_array": [20]},
            {"position_id": 11, "card_id": 300001, "factor_id_array": [11]},
            {"position_id": 12, "card_id": 300002, "factor_id_array": [12]},
            {"position_id": 21, "card_id": 300003, "factor_id_array": [21]},
            {"position_id": 22, "card_id": 300004, "factor_id_array": [22]},
        ],
    }, 100001)

    assert tree["p1"]["card_id"] == 200001
    assert tree["p2"]["card_id"] == 200002
    for key, card_id, factor_id in [
        ("gp1", 300001, 11),
        ("gp2", 300002, 12),
        ("gp3", 300003, 21),
        ("gp4", 300004, 22),
    ]:
        assert tree[key]["card_id"] == card_id
        assert tree[key]["factors"] == [{"name": f"factor-{factor_id}", "stars": 3}]


def test_merge_chara_lineage_adds_separate_succession_array(monkeypatch):
    monkeypatch.setattr(rank_point, "get_factors", lambda ids, owner_card_id=None: [
        {"name": f"factor-{ids[0]}", "stars": 3}
    ] if ids else [])
    owned = {"trained_chara_id": 123, "card_id": 100001, "factor_id_array": [1]}
    data = {
        "succession_trained_chara_data": {
            "succession_trained_chara_array": [{
                "trained_chara_id": 123,
                "card_id": 999999,
                "factor_id_array": [99],
                "succession_chara_array": [
                    {"position_id": 10, "card_id": 200001, "factor_info_array": [{"factor_id": 10}]},
                    {"position_id": 20, "card_id": 200002, "factor_info_array": [{"factor_id": 20}]},
                    {"position_id": 11, "card_id": 300001, "factor_info_array": [{"factor_id": 11}]},
                    {"position_id": 12, "card_id": 300002, "factor_info_array": [{"factor_id": 12}]},
                ],
            }]
        }
    }

    merged = rank_point.merge_chara_lineage(owned, rank_point.lineage_by_trained_chara_id(data)["123"])
    tree = rank_point.build_chara_tree(merged, owned["card_id"])

    assert merged is not owned
    assert "succession_chara_array" not in owned
    assert tree["self"]["card_id"] == "100001"
    assert tree["self"]["factors"] == [{"name": "factor-1", "stars": 3}]
    for key, card_id, factor_id in [
        ("p1", 200001, 10),
        ("p2", 200002, 20),
        ("gp1", 300001, 11),
        ("gp2", 300002, 12),
    ]:
        assert tree[key]["card_id"] == card_id
        assert tree[key]["factors"] == [{"name": f"factor-{factor_id}", "stars": 3}]


def test_normalize_friend_cards_initial_merges_top_level_rental_parent(monkeypatch):
    monkeypatch.setattr(rank_point, "support_map", {"30107": {"name": "Borrow Speed", "rarity": "SSR", "type": "Speed"}})
    monkeypatch.setattr(rank_point, "chara_map", {"100601": "Rental Uma", "100701": "Parent One"})

    data = {
        "friend_support_card_data": {
            "summary_user_info_array": [
                {
                    "viewer_id": 659806586934,
                    "support_card_id": 30107,
                    "name": "rental friend",
                    "user_support_card": {"exp": 100, "limit_break_count": 4},
                }
            ],
            "support_card_data_array": [],
        },
        "summary_user_info_array": [
            {
                "viewer_id": 659806586934,
                "user_trained_chara": {
                    "trained_chara_id": 987654321,
                    "card_id": 100601,
                    "rank": 13,
                    "factor_id_array": [],
                },
            }
        ],
        "succession_trained_chara_data": {
            "succession_trained_chara_array": [
                {
                    "viewer_id": 659806586934,
                    "trained_chara_id": 987654321,
                    "card_id": 100601,
                    "factor_id_array": [],
                    "succession_chara_array": [
                        {"position_id": 10, "card_id": 100701, "factor_id_array": []},
                    ],
                }
            ]
        },
    }

    friends, exclude_viewer_ids, source = career_selection.normalize_friend_cards(data)

    assert source == "initial"
    assert exclude_viewer_ids == [659806586934]
    assert friends[0]["rental_parent"]["trained_chara_id"] == 987654321
    assert friends[0]["rental_parent"]["tree"]["self"]["card_id"] == "100601"
    assert friends[0]["rental_parent"]["tree"]["p1"]["card_id"] == 100701


def test_normalize_friend_cards_refresh_keeps_rental_parent(monkeypatch):
    monkeypatch.setattr(rank_point, "support_map", {"30107": {"name": "Borrow Speed", "rarity": "SSR", "type": "Speed"}})

    data = {
        "summary_user_info_array": [
            {
                "viewer_id": 659806586934,
                "support_card_id": 30107,
                "name": "rental friend",
                "user_trained_chara": {
                    "trained_chara_id": 987654321,
                    "card_id": 100601,
                    "rank": 13,
                    "factor_id_array": [],
                },
            }
        ],
        "support_card_data_array": [],
    }

    friends, exclude_viewer_ids, source = career_selection.normalize_friend_cards(data)

    assert source == "refresh"
    assert exclude_viewer_ids == [659806586934]
    assert friends[0]["rental_parent"]["trained_chara_id"] == 987654321


def test_normalize_friend_cards_refreshes_isolated_rental_rank_point_cache(monkeypatch):
    monkeypatch.setattr(rank_point, "support_map", {
        "30107": {"name": "Borrow Speed", "rarity": "SSR", "type": "Speed"},
    })
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {101, 102}, raising=False)
    monkeypatch.setattr(
        rank_point,
        "win_saddle_groups",
        {101: 10, 102: 20, 201: 10, 202: 20},
        raising=False,
    )
    monkeypatch.setattr(
        rank_point,
        "win_saddle_types",
        {101: 3, 102: 3, 201: 2, 202: 2},
        raising=False,
    )
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True, raising=False)
    rental_key = (659806586934, 987654321)
    owned_cards = [100201, 100301, 100401]
    session = SimpleNamespace(
        parent_cards={987654321: owned_cards.copy()},
        parent_g1_wins={987654321: 9},
        rental_parent_cards={},
        rental_parent_g1_wins={},
    )
    data = {
        "summary_user_info_array": [{
            "viewer_id": 659806586934,
            "support_card_id": 30107,
            "user_trained_chara": {
                "trained_chara_id": 987654321,
                "card_id": 100601,
                "factor_id_array": [],
            },
        }],
        "support_card_data_array": [],
        "succession_trained_chara_data": {
            "succession_trained_chara_array": [{
                "viewer_id": 659806586934,
                "trained_chara_id": 987654321,
                "card_id": 100601,
                "win_saddle_id_array": [101, 102],
                "succession_chara_array": [
                    {"position_id": 10, "card_id": 100701, "win_saddle_id_array": [201]},
                    {"position_id": 20, "card_id": 100801, "win_saddle_id_array": [202]},
                ],
            }],
        },
    }

    career_selection.normalize_friend_cards(data, session=session)

    assert session.parent_cards[987654321] == owned_cards
    assert session.parent_g1_wins[987654321] == 9
    assert session.rental_parent_cards[rental_key] == [100601, 100701, 100801]
    assert session.rental_parent_g1_wins[rental_key] == 6

    lineage = data["succession_trained_chara_data"]["succession_trained_chara_array"][0]
    lineage["succession_chara_array"][0]["win_saddle_id_array"] = []
    lineage["succession_chara_array"][1]["win_saddle_id_array"] = []
    career_selection.normalize_friend_cards(data, session=session)

    assert session.parent_cards[987654321] == owned_cards
    assert session.parent_g1_wins[987654321] == 9
    assert session.rental_parent_g1_wins[rental_key] == 0


def test_read_rental_quota_full():
    data = {"single_mode_rental_succession_num": 2,
            "common_define": {"single_mode_trained_chara_rental_max_num": 5}}
    q = career_selection.read_rental_quota(data)
    assert q == {"used": 2, "max": 5, "remaining": 3}


def test_read_rental_quota_missing_used_defaults_zero():
    data = {"common_define": {"single_mode_trained_chara_rental_max_num": 5}}
    q = career_selection.read_rental_quota(data)
    assert q["used"] == 0 and q["max"] == 5 and q["remaining"] == 5


def test_read_rental_quota_missing_max_defaults_five():
    q = career_selection.read_rental_quota({"single_mode_rental_succession_num": 1})
    assert q["max"] == 5 and q["remaining"] == 4


def test_read_rental_quota_empty_safe():
    q = career_selection.read_rental_quota({})
    assert q["used"] == 0 and q["max"] == 5 and q["remaining"] == 5


def test_read_rental_quota_used_over_max_clamps_remaining():
    q = career_selection.read_rental_quota({"single_mode_rental_succession_num": 9,
                                "common_define": {"single_mode_trained_chara_rental_max_num": 5}})
    assert q["remaining"] == 0


FRIENDS = [
    {"viewer_id": 111, "rental_parent": {"trained_chara_id": 4662}},
    {"viewer_id": 222, "rental_parent": None},
    {"viewer_id": 333},  # no rental_parent key
]


def test_decide_rental_opted_out():
    assert career_selection.decide_rental(0, FRIENDS, {"remaining": 5}) == (0, 0)


def test_decide_rental_quota_exhausted():
    assert career_selection.decide_rental(111, FRIENDS, {"remaining": 0}) == (0, 0)


def test_decide_rental_friend_missing():
    assert career_selection.decide_rental(999, FRIENDS, {"remaining": 5}) == (0, 0)


def test_decide_rental_friend_has_no_parent():
    assert career_selection.decide_rental(222, FRIENDS, {"remaining": 5}) == (0, 0)
    assert career_selection.decide_rental(333, FRIENDS, {"remaining": 5}) == (0, 0)


def test_decide_rental_happy_path():
    assert career_selection.decide_rental(111, FRIENDS, {"remaining": 3}) == (111, 4662)
