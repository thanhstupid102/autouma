import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point

from tests._helpers import _make_session


def test_reset_runtime_clears_run_scoped_state_but_preserves_auth_staging_and_pacing():
    s = _make_session("reset-scope")

    # run-scoped state that must NOT leak into the next account's login
    s.event_info_cache = {"difficulty_id": 9}
    s.active_preset = "Some Preset"
    s.last_run_req = {"card_id": 100101}
    s.last_preset = {"name": "p"}
    # a couple of the always-reset caches, to confirm the pre-existing behavior holds
    s.dashboard_data = {"account": {}}
    s.rental_parent_cards = {(1, 2): "x"}
    # intentionally-preserved fields
    s.pending_game_auth_config = {"steam_ticket": "abc"}
    s.pending_transition_config = {"udid": "staged-device"}
    s.delay_config = {"min": 3.0, "max": 7.0, "disabled": False}
    runner_before = s.runner

    s.reset_runtime()

    # run-scoped: cleared
    assert s.event_info_cache is None
    assert s.active_preset is None
    assert s.last_run_req is None
    assert s.last_preset is None
    # pre-existing resets still happen
    assert s.dashboard_data is None
    assert s.rental_parent_cards == {}
    # preserved across the auth boundary
    assert s.pending_game_auth_config == {"steam_ticket": "abc"}
    assert s.pending_transition_config == {}
    assert s.delay_config == {"min": 3.0, "max": 7.0, "disabled": False}
    assert s.runner is runner_before


# ---------------------------------------------------------------------------
# event-info must NOT call load/index while a career run is active (it 201s and
# desyncs the running session). It serves the cached event-info instead.
# ---------------------------------------------------------------------------

class _NoLoadIndexClient:
    def call(self, *args, **kwargs):
        raise AssertionError("load/index must NOT be called while a career is running")


def test_event_info_serves_cache_while_running(monkeypatch):
    s = _make_session("ev-running")
    s.client = _NoLoadIndexClient()
    monkeypatch.setattr(s.runner, "snapshot", lambda: {"running": True})
    s.event_info_cache = {"success": True, "available": True, "difficulty_id": 1003, "max_level": 4}

    from backend.app.routers.careers.services.career_service import CareerService

    res = CareerService(s).event_info()

    assert res == {"success": True, "available": True, "difficulty_id": 1003, "max_level": 4}


def test_event_info_empty_while_running_without_cache(monkeypatch):
    s = _make_session("ev-running-nocache")
    s.client = _NoLoadIndexClient()
    monkeypatch.setattr(s.runner, "snapshot", lambda: {"running": True})
    s.event_info_cache = None

    from backend.app.routers.careers.services.career_service import CareerService

    res = CareerService(s).event_info()

    assert res == {"success": True, "available": False, "difficulty_id": 0, "max_level": 0}


def test_event_info_calls_load_index_and_caches_when_idle(monkeypatch):
    s = _make_session("ev-idle")
    monkeypatch.setattr(s.runner, "snapshot", lambda: {"running": False})

    calls = []

    class IdleClient:
        def call(self, ep, payload=None):
            calls.append(ep)
            return {"data": {}, "data_headers": {"servertime": 0}}

    s.client = IdleClient()

    from backend.app.routers.careers.services.career_service import CareerService

    res = CareerService(s).event_info()

    assert calls == ["load/index"]
    assert res["success"] is True
    # The successful result is cached for the next mid-run request.
    assert s.event_info_cache == res


# ---------------------------------------------------------------------------
# Team selection persists per account and restores (remember preset/deck/...).
# ---------------------------------------------------------------------------

def test_selection_persists_and_restores(tmp_path, monkeypatch):
    monkeypatch.setattr(account_store, "state_root", tmp_path / "uma_runtime")
    monkeypatch.setattr(rank_point, "base_dir", tmp_path)

    sel = {
        "deck": {"name": "Speed Deck"},
        "friend": None,
        "trainee": {"id": 100101},
        "veterans": [],
        "event": {"enabled": True, "level": 2, "boost": False},
    }

    assert account_store.save_selection("acc-A", sel) is True
    # Written to a SEPARATE selections/ dir, never the accounts/ dir.
    assert (tmp_path / "uma_runtime" / "selections" / "acc-A.json").exists()
    assert not (tmp_path / "uma_runtime" / "accounts" / "acc-A.json").exists()

    assert account_store.load_selection("acc-A") == sel
    # Distinct accounts don't share, and unknown/blank names are safe.
    assert account_store.load_selection("acc-B") is None
    assert account_store.load_selection("") is None


def test_selection_load_handles_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(account_store, "state_root", tmp_path / "uma_runtime")
    monkeypatch.setattr(rank_point, "base_dir", tmp_path)
    path = tmp_path / "uma_runtime" / "selections" / "acc-C.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")

    assert account_store.load_selection("acc-C") is None  # graceful, no raise
