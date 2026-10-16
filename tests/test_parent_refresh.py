from concurrent.futures import ThreadPoolExecutor

import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point
from backend.app.routers.parents.services.parent_service import ParentService
from core.settings import Settings
from uma_api import game_service
from uma_api.session import Session


def _parent(instance_id, card_id, rank=1, rank_score=100):
    return {
        "trained_chara_id": instance_id,
        "card_id": card_id,
        "rank": rank,
        "rank_score": rank_score,
        "is_locked": 0,
        "succession_chara_array": [],
    }


def _session(name, parents):
    session = Session(name=name, base_dir=str(Settings.BASE_DIR))
    session.client = object()
    session.dashboard_data = {"success": True, "parents": list(parents)}
    return session


def _patch_parent_builder(monkeypatch):
    monkeypatch.setattr(rank_point, "chara_map", {
        "100101": "Parent One",
        "100102": "Parent Two",
        "100103": "Parent Three",
    })
    monkeypatch.setattr(rank_point, "lineage_by_trained_chara_id", lambda data: {})
    monkeypatch.setattr(
        rank_point,
        "merge_chara_lineage",
        lambda chara, lineage: dict(chara),
    )
    monkeypatch.setattr(
        rank_point,
        "build_chara_tree",
        lambda source, card_id: {"self": {"card_id": card_id}},
    )
    monkeypatch.setattr(
        rank_point,
        "parent_shared_g1_bonus",
        lambda source: int(source.get("rank") or 0),
    )


def test_refresh_rebuilds_roster_and_all_owned_parent_caches(monkeypatch):
    _patch_parent_builder(monkeypatch)
    session = _session(
        "parent-refresh-add",
        [{"instance_id": 1, "card_id": "100101"}],
    )
    payload = {
        "trained_chara": [
            _parent(1, 100101, rank=3, rank_score=300),
            _parent(2, 100102, rank=5, rank_score=500),
        ]
    }
    monkeypatch.setattr(game_service, "read_info", lambda current: {"data": payload})
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args: None)
    session.parent_cards = {999: [999999]}
    session.parent_rank_points = {999: {"rank": 99}}
    session.parent_g1_wins = {999: 99}
    session.parent_g1_sources = {999: {"card_id": 999999}}

    result = ParentService(session).refresh()

    assert result["success"] is True
    assert [parent["instance_id"] for parent in result["parents"]] == [1, 2]
    assert session.dashboard_data["parents"] == result["parents"]
    assert session.parent_cards == {1: [100101], 2: [100102]}
    assert session.parent_rank_points == {
        1: {"rank": 3, "rank_score": 300},
        2: {"rank": 5, "rank_score": 500},
    }
    assert session.parent_g1_wins == {1: 3, 2: 5}
    assert set(session.parent_g1_sources) == {1, 2}


def test_refresh_drops_vanished_parent_from_roster_and_remembered_selection(
    monkeypatch,
    tmp_account_store,
):
    _patch_parent_builder(monkeypatch)
    parent_one = {"instance_id": 1, "card_id": "100101"}
    parent_two = {"instance_id": 2, "card_id": "100102"}
    session = _session("parent-refresh-drop", [parent_one, parent_two])
    session.selection = {
        "deck": {"id": 7},
        "veterans": [parent_one, parent_two],
    }
    payload = {"trained_chara": [_parent(1, 100101)]}
    monkeypatch.setattr(game_service, "read_info", lambda current: {"data": payload})
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args: None)

    result = ParentService(session).refresh()

    assert result["success"] is True
    assert [parent["instance_id"] for parent in result["parents"]] == [1]
    assert result["removed_veteran_ids"] == [2]
    assert session.selection == {"deck": {"id": 7}, "veterans": [parent_one]}
    assert account_store.load_selection("parent-refresh-drop") == session.selection


def test_refresh_is_refused_while_career_runner_is_active(monkeypatch):
    session = _session("parent-refresh-running", [])
    monkeypatch.setattr(session.runner, "snapshot", lambda: {"running": True})
    monkeypatch.setattr(
        game_service,
        "read_info",
        lambda current: (_ for _ in ()).throw(AssertionError("game API touched")),
    )

    result = ParentService(session).refresh()

    assert result["success"] is False
    assert result["detail"].startswith("Career is running")


def test_refresh_not_logged_in_and_game_error_are_clean_failures(monkeypatch):
    not_logged_in = Session(name="parent-refresh-no-login", base_dir=str(Settings.BASE_DIR))
    assert ParentService(not_logged_in).refresh() == {
        "success": False,
        "detail": "Not logged in",
    }

    session = _session(
        "parent-refresh-error",
        [{"instance_id": 1, "card_id": "100101"}],
    )
    session.parent_cards = {1: [100101]}
    session.selection = {"veterans": [{"instance_id": 1, "card_id": "100101"}]}
    monkeypatch.setattr(
        game_service,
        "read_info",
        lambda current: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    result = ParentService(session).refresh()

    assert result == {"success": False, "detail": "Refresh failed: network down"}
    assert session.dashboard_data["parents"] == [
        {"instance_id": 1, "card_id": "100101"}
    ]
    assert session.parent_cards == {1: [100101]}
    assert session.selection["veterans"] == [
        {"instance_id": 1, "card_id": "100101"}
    ]


def test_concurrent_refreshes_keep_account_state_isolated(monkeypatch):
    _patch_parent_builder(monkeypatch)
    sessions = {
        "parent-refresh-a": _session("parent-refresh-a", []),
        "parent-refresh-b": _session("parent-refresh-b", []),
    }
    payloads = {
        "parent-refresh-a": {"trained_chara": [_parent(1, 100101)]},
        "parent-refresh-b": {"trained_chara": [_parent(2, 100102)]},
    }
    monkeypatch.setattr(
        game_service,
        "read_info",
        lambda current: {"data": payloads[current.name]},
    )
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args: None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda current: ParentService(current).refresh(), sessions.values()))

    assert all(result["success"] is True for result in results)
    assert sessions["parent-refresh-a"].parent_cards == {1: [100101]}
    assert sessions["parent-refresh-b"].parent_cards == {2: [100102]}
