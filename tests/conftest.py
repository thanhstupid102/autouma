import os

import pytest

from uma_api import secret_store
from uma_api.session import get_session_manager
from uma_data import tp_cost


if os.name == "nt":
    _orig_mkdir = os.mkdir

    def _workspace_accessible_mkdir(path, mode=0o777, *args, **kwargs):
        return _orig_mkdir(path, 0o777, *args, **kwargs)

    os.mkdir = _workspace_accessible_mkdir


@pytest.fixture(autouse=True)
def _drop_tester_session():
    """get_session_manager() is a process-wide singleton, so importlib.reload()
    (used by tests to get a "fresh" module) does NOT give a fresh SessionManager.
    Tests that key off the shared account name "tester" mutate Session state
    (e.g. delay_config) that would otherwise leak into every later test in the
    process. Drop it after each test. In tests the stored runners are never
    actually started, so no runner.stop() is needed -- just discard the entry.
    """
    yield
    get_session_manager().discard("tester")


@pytest.fixture(autouse=True)
def _api_auth_defaults_off(monkeypatch):
    """Keep existing route tests independent of the invoking shell's secrets."""
    monkeypatch.delenv("UMA_API_TOKEN", raising=False)
    monkeypatch.delenv("UMA_API_TOKEN_FILE", raising=False)


@pytest.fixture(autouse=True)
def _default_secret_store_backend(request, monkeypatch):
    """Give non-DPAPI hosts the same portable backend production expects."""
    if request.node.get_closest_marker("no_default_secret_store_backend"):
        return
    if secret_store._dpapi_is_available():
        return

    monkeypatch.setenv(
        "UMA_SECRET_PASSPHRASE",
        "pytest-portable-secret-store-passphrase",
    )
    monkeypatch.setattr(secret_store, "SCRYPT_N", 2 ** 10)
    monkeypatch.setattr(secret_store, "SCRYPT_R", 8)
    monkeypatch.setattr(secret_store, "SCRYPT_P", 1)
    monkeypatch.setattr(secret_store, "SCRYPT_DKLEN", 32)


@pytest.fixture(autouse=True)
def _offline_single_use_tp_campaigns(monkeypatch):
    """Keep the career-start TP campaign policy off the machine's real master.mdb.

    uma_data.tp_cost resolves the career-START TP cost from master.mdb
    via Settings.BASE_DIR, which falls back to the live game install. A *real* half-TP
    campaign being active there would silently turn every career-start test's expected
    30 TP into 15 -- same class of problem as SWEEPY_SKIP_STARTUP_GEN above.

    Default every test to "no campaign" (= full 30 TP) by stubbing the loader, and
    clear the process-wide memo around each test. The real `load_active_campaigns`
    caching logic still runs, so tests can cover it; tests that want an active
    campaign patch `tp_cost.load_active_campaigns` themselves.
    """
    tp_cost._CAMPAIGN_CACHE = None
    monkeypatch.setattr(
        tp_cost, "load_single_use_tp_campaigns",
        lambda base_dir, master_mdb_path=None: [],
    )
    yield
    tp_cost._CAMPAIGN_CACHE = None


@pytest.fixture
def tmp_account_store(tmp_path, monkeypatch):
    """The ``account_store`` module with its runtime base dir redirected at tmp_path.

    Was a byte-identical private ``m`` fixture in both ``test_json_stores.py`` and
    ``test_steam_token.py``; shared from here so neither suite can ever touch the
    machine's real ``uma_runtime/accounts`` files.
    """
    import backend.app.domain.account_store as account_store
    import backend.app.domain.rank_point as rank_point

    monkeypatch.setattr(account_store, "state_root", tmp_path / "uma_runtime")
    monkeypatch.setattr(rank_point, "base_dir", tmp_path)
    monkeypatch.setattr(rank_point, "state_root", tmp_path / "uma_runtime")
    return account_store


@pytest.fixture
def drop_sessions():
    """Return a callable that immediately discards named cached Sessions."""
    manager = get_session_manager()
    discarded = set()

    def drop(*names):
        discarded.update(names)
        for name in names:
            manager.discard(name)

    yield drop

    for name in discarded:
        manager.discard(name)
