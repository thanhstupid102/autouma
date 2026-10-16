"""Pins ``_build_parents`` -- the dashboard veteran list AND the 4 lineage caches.

``AuthService.login`` builds the dashboard's ``parents`` list in the same pass that
refills ``session.parent_cards`` / ``parent_rank_points`` / ``parent_g1_wins`` /
``parent_g1_sources`` (the career-start rank-point formula reads those later).
Every other login test feeds ``{"data": {}}``, so none of that pass ran under test
before this module -- flagged as a coverage gap by the §12.4 auth decomposition.

The fakes follow the established style of ``tests/test_login_recovery.py``: a
``UmaClient`` stand-in whose ``login()`` returns a canned payload, plus monkeypatched
``backend.app.domain.rank_point`` lookup tables so the tree/G1 maths is deterministic and offline.
"""
import asyncio

import pytest

from backend.app.routers.auth.schemas.auth import LoginRequest
from backend.app.routers.auth.services.auth_service import AuthService
from uma_api.session import get_session_manager
import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point


VALID_CFG = {
    "app_ver": "1.0.0",
    "res_ver": "1",
    "auth_key_len": 48,
    "viewer_id": 12345,
    "udid": "00000000-0000-0000-0000-000000000000",
    "auth_key": "ab" * 48,
    "steam_id": "steamid-1",
    "steam_session_ticket": "captured-ticket",
}

CHARA_MAP = {
    "100801": "Special Week",
    "100802": "Silence Suzuka",
    "101301": "Gold Ship",
    "100101": "Haru Urara",
    "102001": "Mejiro McQueen",
}

# get_win_summary() grades a win by race_map[str(saddle_id)]["grade"].
RACE_MAP = {
    "1001": {"grade": "G1"},
    "1002": {"grade": "G1"},
    "2001": {"grade": "G2"},
    "3001": {"grade": "G1"},
}

# parse_factor_ids takes the "known factor" branch (no master.mdb lookup) when the
# entry supplies both name and category.
FACTOR_MAP = {
    "10041": {"name": "Speed", "category": "stat", "stars": 3},
}

# shared_g1_group_count() counts a LEFT win when win_saddle_types[id] == 3 (G1) and
# its win_saddle_groups[id] also appears on the RIGHT side.
WIN_SADDLE_TYPES = {1001: 3, 1002: 3, 2001: 1, 3001: 3}
WIN_SADDLE_GROUPS = {1001: 7, 1002: 8, 2001: 7, 3001: 9}
G1_SADDLE_IDS = {1001, 1002, 3001}


# --- the login payload -------------------------------------------------------
# Veteran A: ordinary numeric card_id with its lineage inline on the row.
CHARA_A = {
    "trained_chara_id": 5001,
    "card_id": 100801,
    "rank": 12,
    "rank_score": 17600,
    "is_locked": 1,
    "factor_id_array": [10041],
    "win_saddle_id_array": [1001, 1002],
    "succession_chara_array": [
        {"position_id": 10, "card_id": 101301, "win_saddle_id_array": [2001]},
        {"position_id": 20, "card_id": 100101, "win_saddle_id_array": []},
        {"position_id": 11, "card_id": 102001, "win_saddle_id_array": []},
    ],
}

# Veteran B: the row carries NO lineage and NO rank_score -- both come from the
# separate succession_trained_chara_data block via merge_chara_lineage().
CHARA_B = {
    "trained_chara_id": 5003,
    "card_id": 100802,
    "rank": 9,
    "is_locked": 0,
    "win_saddle_id_array": [3001],
}

# Veteran C: the salvage branch. card_id is an unusable braced/dashed raw id, so the
# builder scans the row's OTHER values and adopts the first digit string >= 4 chars
# in insertion order -- "rank"/"rank_score" are too short, "lineage_card_id" wins
# (note it is scanned BEFORE trained_chara_id, which would also have qualified).
CHARA_C = {
    "card_id": "{5b0a3f2e-0000-4c11-9a77-0b7c1d2e3f40}",
    "rank": 4,
    "rank_score": 800,
    "lineage_card_id": 101301,
    "trained_chara_id": 5004,
    "is_locked": 0,
    "win_saddle_id_array": [1001, 1002, 3001],
    "succession_chara_array": [
        {"position_id": 10, "card_id": 100801, "win_saddle_id_array": [1001, 1002]},
        {"position_id": 20, "card_id": 100802, "win_saddle_id_array": [3001]},
    ],
}

# Veteran D: salvage finds nothing -> the row is skipped entirely (`continue`).
# trained_chara_id is deliberately < 4 digits so no sibling value qualifies.
CHARA_D = {
    "card_id": "{ghost-row}",
    "trained_chara_id": 999,
    "rank": 0,
    "rank_score": 0,
    "is_locked": 0,
}

LOGIN_PAYLOAD = {
    "user_info": {"name": "Trainer"},
    "tp_info": {"current_tp": 30, "max_tp": 100},
    "coin_info": {"fcoin": 10, "coin": 5},
    "trained_chara": [CHARA_A, CHARA_B, CHARA_C, CHARA_D],
    "succession_trained_chara_data": {
        "succession_trained_chara_array": [
            {
                # A already has its own lineage -> this entry must NOT override it.
                "trained_chara_id": 5001,
                "succession_chara_array": [
                    {"position_id": 10, "card_id": 999999, "win_saddle_id_array": []},
                ],
            },
            {
                "trained_chara_id": 5003,
                "rank_score": 14200,
                "succession_chara_array": [
                    {"position_id": 10, "card_id": 102001, "win_saddle_id_array": [3001]},
                    {"position_id": 20, "card_id": 100101, "win_saddle_id_array": [3001]},
                ],
            },
        ]
    },
}


class PayloadClient:
    """UmaClient stand-in whose login() returns ``LOGIN_PAYLOAD``."""

    instances: list["PayloadClient"] = []

    def __init__(self, cfg, trace_enabled=False):
        self.cfg = dict(cfg)
        self.viewer_id = cfg.get("viewer_id", 1)
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        PayloadClient.instances.append(self)

    def login(self):
        return {"data": LOGIN_PAYLOAD}

    def load_career(self):
        return {"data": {}}

    def call(self, *args, **kwargs):
        return {}

    def bind_api_warehouse(self, base_dir, account):
        return self


@pytest.fixture
def hydrated(monkeypatch):
    import uma_api.client as client_module
    import career_bot.delay as delay_module

    PayloadClient.instances = []
    monkeypatch.setattr(client_module, "UmaClient", PayloadClient)
    monkeypatch.setattr(delay_module, "GateKeeper", lambda client, *a, **k: client)
    monkeypatch.setattr(
        client_module, "get_ticket",
        lambda u="", p="", c="", refresh_token="": ("steamid-1", "captured-ticket", ""),
    )
    # Keep the run hermetic: no accounts/ or selections/ files are touched.
    monkeypatch.setattr(account_store, "load_steam_token", lambda name: None)
    monkeypatch.setattr(account_store, "save_steam_token", lambda *a, **k: True)
    monkeypatch.setattr(account_store, "save_account_config", lambda name, cfg: None)
    monkeypatch.setattr(account_store, "load_selection", lambda name: {})
    monkeypatch.setattr(account_store, "apply_auto_delete_config", lambda session: None)
    # rank_point's mutable module globals are read at CALL time -> patchable seams.
    monkeypatch.setattr(rank_point, "chara_map", CHARA_MAP)
    monkeypatch.setattr(rank_point, "support_map", {})
    monkeypatch.setattr(rank_point, "race_map", RACE_MAP)
    monkeypatch.setattr(rank_point, "factor_map", FACTOR_MAP)
    monkeypatch.setattr(rank_point, "skill_data", {})
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True)
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", set(G1_SADDLE_IDS))
    monkeypatch.setattr(rank_point, "win_saddle_groups", dict(WIN_SADDLE_GROUPS))
    monkeypatch.setattr(rank_point, "win_saddle_types", dict(WIN_SADDLE_TYPES))
    monkeypatch.setenv("SWEEPY_ACCOUNT", "tester")

    session = get_session_manager().get("tester")
    session.pending_game_auth_config = dict(VALID_CFG)
    result = asyncio.run(AuthService(session).login(LoginRequest()))
    assert result.get("success") is True, result
    return session, result


def test_parents_list_rendered_from_trained_chara(hydrated):
    _session, result = hydrated
    parents = result["parents"]

    # Order follows `trained_chara`; the unsalvageable ghost row (D) is dropped.
    assert [p["instance_id"] for p in parents] == [5001, 5003, 5004]
    assert [p["card_id"] for p in parents] == ["100801", "100802", "101301"]
    assert [p["name"] for p in parents] == ["Special Week", "Silence Suzuka", "Gold Ship"]
    assert [p["rank"] for p in parents] == [12, 9, 4]
    assert [p["is_locked"] for p in parents] == [1, 0, 0]


def test_parent_tree_uses_the_rows_own_lineage(hydrated):
    _session, result = hydrated
    tree = result["parents"][0]["tree"]

    assert tree["self"] == {
        "card_id": "100801",
        "name": "Special Week",
        "factors": [{"name": "Speed", "stars": 3, "id": 10041, "category": "stat"}],
        "wins": {"g1": 2, "g2": 0, "g3": 0, "total": 2},
    }
    # The row's INLINE succession array wins over the succession_trained_chara_data
    # entry for the same trained_chara_id (card 999999 must not appear).
    assert tree["p1"]["card_id"] == 101301
    assert tree["p1"]["name"] == "Gold Ship"
    assert tree["p1"]["wins"] == {"g1": 0, "g2": 1, "g3": 0, "total": 1}
    assert tree["p2"]["card_id"] == 100101
    assert tree["gp1"]["card_id"] == 102001
    # Positions the payload never fills stay at the empty defaults.
    assert tree["gp3"] == {
        "card_id": 0, "name": "", "factors": [],
        "wins": {"g1": 0, "g2": 0, "g3": 0, "total": 0},
    }


def test_parent_tree_merges_the_separate_lineage_block(hydrated):
    _session, result = hydrated
    tree = result["parents"][1]["tree"]

    # CHARA_B has no succession_chara_array of its own -- merge_chara_lineage pulled
    # it from succession_trained_chara_data.
    assert tree["self"]["card_id"] == "100802"
    assert tree["p1"]["card_id"] == 102001
    assert tree["p2"]["card_id"] == 100101


def test_salvaged_card_id_drives_the_whole_row(hydrated):
    session, result = hydrated
    salvaged = result["parents"][2]

    # "{5b0a...}" is unusable; the first sibling digit-string of >= 4 chars wins.
    assert salvaged["card_id"] == "101301"
    assert salvaged["tree"]["self"]["card_id"] == "101301"
    # ...and the salvaged id is what lands in the lineage cache, too.
    assert session.parent_cards[5004][0] == 101301


def test_unsalvageable_row_is_skipped_everywhere(hydrated):
    session, result = hydrated

    assert all(p["instance_id"] != 999 for p in result["parents"])
    for cache in (session.parent_cards, session.parent_rank_points,
                  session.parent_g1_wins, session.parent_g1_sources):
        assert 999 not in cache


def test_parent_cards_cache_is_self_then_succession_order(hydrated):
    session, _result = hydrated

    assert session.parent_cards == {
        # self card first, then every succession card in array order.
        5001: [100801, 101301, 100101, 102001],
        5003: [100802, 102001, 100101],
        5004: [101301, 100801, 100802],
    }


def test_parent_rank_points_cache_reads_the_raw_row(hydrated):
    session, _result = hydrated

    # NOTE: rank/rank_score are taken from the RAW trained_chara row, not from the
    # merged tree source -- CHARA_B's rank_score therefore stays 0 even though the
    # succession_trained_chara_data entry carries 14200. Pinning current behavior.
    assert session.parent_rank_points == {
        5001: {"rank": 12, "rank_score": 17600},
        5003: {"rank": 9, "rank_score": 0},
        5004: {"rank": 4, "rank_score": 800},
    }


def test_parent_g1_wins_cache_scores_the_merged_source(hydrated):
    session, _result = hydrated

    # parent_shared_g1_bonus = 3 points per directional G1/group match against a
    # DIRECT grandparent (position 10 / 20).
    #   5001: own [1001,1002] vs p1 [2001] (group 7) -> 1001 matches           -> 3
    #   5003: own [3001] (group 9) vs merged p1 AND p2 [3001] -> 2 matches     -> 6
    #   5004: own [1001,1002,3001] vs p1 [1001,1002] -> 2, vs p2 [3001] -> 1   -> 9
    assert session.parent_g1_wins == {5001: 3, 5003: 6, 5004: 9}


def test_parent_g1_sources_cache_holds_the_merged_tree_source(hydrated):
    session, _result = hydrated

    assert set(session.parent_g1_sources) == {5001, 5003, 5004}
    # 5001 kept its own inline lineage...
    assert [sc["card_id"] for sc in session.parent_g1_sources[5001]["succession_chara_array"]] \
        == [101301, 100101, 102001]
    # ...5003 is the MERGED dict: lineage grafted on, raw row left untouched.
    assert [sc["card_id"] for sc in session.parent_g1_sources[5003]["succession_chara_array"]] \
        == [102001, 100101]
    assert "succession_chara_array" not in CHARA_B
    # The merge also back-fills the scalar the raw row was missing.
    assert session.parent_g1_sources[5003]["rank_score"] == 14200
