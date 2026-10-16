from uma_api.session import Session, SessionManager


def test_session_defaults():
    s = Session(name="acc1")
    assert s.name == "acc1"
    assert s.client is None
    assert s.account is None
    assert s.dashboard_data is None
    assert s.start_state == {}
    assert s.parent_cards == {}
    assert s.parent_rank_points == {}
    assert s.raw_load_index_response is None
    assert s.selection == {"deck": None, "friend": None, "trainee": None, "veterans": []}
    assert s.runner is not None            # own CareerRunner instance
    assert s.loop_thread is None
    assert s.loop_stop is False
    assert s.active_preset is None
    assert s.pending_game_auth_config == {}
    assert s.pending_transition_config == {}
    assert not hasattr(s, "capture_status")
    assert not hasattr(s, "capture_lock")


def test_manager_get_creates_lazily():
    mgr = SessionManager(base_dir=".")
    s = mgr.get("acc1")
    assert isinstance(s, Session)
    assert mgr.get("acc1") is s          # same instance on second call

def test_manager_list_and_remove():
    mgr = SessionManager(base_dir=".")
    mgr.get("a"); mgr.get("b")
    assert set(mgr.names()) == {"a", "b"}
    mgr.remove("a")
    assert set(mgr.names()) == {"b"}

def test_manager_snapshot_all_shape():
    mgr = SessionManager(base_dir=".")
    s = mgr.get("a")
    s.client = object()  # mark logged in so it appears in the snapshot
    snaps = mgr.snapshot_all()
    assert isinstance(snaps, list)
    a = next(x for x in snaps if x["name"] == "a")
    assert "running" in a
    assert a["logged_in"] is True


def test_manager_snapshot_hides_bare_session():
    # A lazily-created session with no creds, not running, and no on-disk file
    # must NOT appear (otherwise a stray poll resurrects a just-deleted account).
    mgr = SessionManager(base_dir=".")
    mgr.get("ghost")
    snaps = mgr.snapshot_all()
    assert all(s["name"] != "ghost" for s in snaps)


# Moved verbatim out of tests/test_201_resilience.py by the §13.1/A13 by-owner
# carve -- name normalization is SessionManager's contract, not a 201 concern.
def test_get_session_normalizes_account_name_no_duplicate():
    # A name with a space/diacritic/special char must key the SAME in-memory session
    # as its sanitized form -- otherwise the raw-named session + the safe-named disk
    # file both surface in snapshot_all() and the account shows up TWICE.
    from backend.app.deps import get_session

    raw = get_session("dup test")
    safe = get_session("dup_test")
    assert raw is safe
    assert raw.name == "dup_test"
    # already-clean names pass through unchanged (existing accounts unaffected)
    assert get_session("lewpie").name == "lewpie"
