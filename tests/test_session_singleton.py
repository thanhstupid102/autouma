# ---------------------------------------------------------------------------
# Regression coverage for the multi-SessionManager state-sharing bug: three
# separate SessionManager instantiations (the get_session() FastAPI dependency
# -- now backend/app/deps.py, formerly uma_api/session.py --, backend/app/context.py
# module-level session_manager, backend/app/context.py configure_runtime()) used to
# each own a disjoint pool of per-account Sessions, so state written through
# one (e.g. a posted turn-delay change via the FastAPI dependency) was
# invisible to the others (the live bot session). All three now funnel through
# uma_api.session.get_session_manager(), a lazily-created, lock-guarded
# process-wide singleton.
# ---------------------------------------------------------------------------


def _reconfigure_context():
    """Restore context runtime state to the real repo root after a temporary
    runtime reconfiguration, so assertions do not depend on collection order."""
    from core.settings import Settings
    import backend.app.context as context
    context.configure_runtime(str(Settings.BASE_DIR))
    return context


def test_get_session_manager_is_shared_with_context_module():
    from uma_api.session import get_session_manager
    context = _reconfigure_context()

    assert get_session_manager() is context.session_manager


def test_get_session_returns_same_session_object_across_calls():
    # This is the buggy path: get_session() (backend/app/deps.py) is the
    # FastAPI dependency wired into backend/app/routers/settings/controllers.py.
    # On HEAD it builds a brand-new SessionManager(...) on every call, so two
    # calls for the same account used to return two DIFFERENT Session
    # objects -- a posted setting would land on a Session nobody else could
    # ever see again.
    from backend.app.deps import get_session

    s1 = get_session(x_account="tester")
    s2 = get_session(x_account="tester")

    assert s1 is s2


def test_turn_delay_write_via_get_session_is_visible_on_context_session_manager():
    # End-to-end: write the field the real turn-delay flow writes
    # (backend/app/routers/settings/services/delay.py DelayConfigService
    # .set_turn_delay writes session.delay_config["min"/"max"/"disabled"])
    # through the FastAPI-dependency path, then read it back through the
    # context module's session_manager -- the one the running bot/dashboard
    # actually uses. They must be the SAME Session.
    from backend.app.deps import get_session
    context = _reconfigure_context()

    session = get_session(x_account="tester")
    session.delay_config["min"] = 42

    assert context.session_manager.get("tester").delay_config["min"] == 42
    assert context.session_manager.get("tester") is session


def test_configure_runtime_reuses_singleton_for_the_same_base_dir():
    # configure_runtime() is a dual-purpose app-factory function: main.py
    # calls it (via create_app) with the REAL base dir on every production
    # launch, but tests call it with a throwaway tmp_path for isolation
    # (tests/test_app_routes.py). When the resolved base_dir matches
    # Settings.BASE_DIR -- the production case -- it must reuse the process
    # singleton so the fix actually closes the loop end-to-end; otherwise
    # configure_runtime would keep handing out a manager disconnected from
    # uma_api.session.get_session_manager() every time main.py is imported.
    from core.settings import Settings
    from uma_api.session import get_session_manager
    context = _reconfigure_context()

    result = context.configure_runtime(str(Settings.BASE_DIR))

    assert result["session_manager"] is get_session_manager()
    assert context.session_manager is get_session_manager()


def test_configure_runtime_stays_isolated_for_a_different_base_dir(tmp_path):
    # A genuinely different base_dir (test isolation, or any future
    # standalone/alternate-runtime use) must NOT be forced onto the
    # production singleton -- that would make tests bleed into each other's
    # accounts/ directories.
    from uma_api.session import get_session_manager
    context = _reconfigure_context()

    result = context.configure_runtime(
        str(tmp_path),
        state_root_value=tmp_path / "uma_runtime",
    )

    assert result["session_manager"] is not get_session_manager()
    assert result["session_manager"].base_dir == str(tmp_path)

    # Restore clean production state for any test file collected after this
    # one in the same pytest process.
    _reconfigure_context()
