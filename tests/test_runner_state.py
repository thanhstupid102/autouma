"""§13.2 B2 final step: the runner/loop state left the transport Session.

`CareerRuntime` + the registry now live in ``backend/app/runner_state.py``;
``uma_api.session.Session`` only exposes them through property shims. This file
pins the four §1.3 hard invariants that the move had to preserve, because a
regression in any of them is an ACCOUNT-SAFETY bug, not a style bug:

1. account isolation -- one runtime per account, never reachable from another;
2. runner lifecycle -- ``SessionManager.remove()`` stops the runner,
   ``discard()`` does not, and no stop signal is ever lost;
3. ``get_session_manager()`` stays the process-wide singleton, and the runtime
   follows it;
4. ``require_idle`` semantics are unchanged by the relocation.
"""
from types import SimpleNamespace

from backend.app.runner_state import (
    CareerRuntime,
    get_career_runtime,
    peek_career_runtime,
    require_idle,
)
from uma_api.session import Session, SessionManager, get_session_manager


BUSY = {"success": False, "detail": "Career is running — stop it first."}


class StopSpy:
    """Stand-in CareerRunner that records lifecycle calls."""

    def __init__(self, running=False, fail_stop=False):
        self.stops = 0
        self.running = running
        self.fail_stop = fail_stop

    def snapshot(self):
        return {"running": self.running}

    def stop(self):
        self.stops += 1
        if self.fail_stop:
            raise RuntimeError("runner refused to stop")
        self.running = False


class QrStopSpy:
    def __init__(self):
        self.stops = 0

    def stop(self):
        self.stops += 1


def _live_thread():
    """A loop_thread stand-in that reports itself alive (no real thread needed)."""
    return SimpleNamespace(is_alive=lambda: True)


# --- construction / ownership ------------------------------------------------

def test_session_binds_its_runtime_at_construction():
    # No lifecycle-order change: the CareerRunner is still built when the Session
    # is built, not lazily on first use.
    session = Session(name="runner-state-construct")

    runtime = peek_career_runtime(session)
    assert isinstance(runtime, CareerRuntime)
    assert runtime.runner is not None
    assert session.runner is runtime.runner


def test_session_has_no_runner_or_loop_fields_of_its_own():
    # The structural half of B2: the state is gone from the transport dataclass.
    import dataclasses

    names = {f.name for f in dataclasses.fields(Session)}
    assert names.isdisjoint({
        "loop", "runner", "loop_thread", "loop_stop", "loop_paused",
        "active_preset", "last_run_req", "last_preset",
    })


def test_shims_read_and_write_through_to_the_runtime():
    session = Session(name="runner-state-shims")
    runtime = get_career_runtime(session)

    session.loop_stop = True
    session.loop_paused = True
    session.active_preset = "preset-a"
    session.last_run_req = {"card_id": 1}
    session.last_preset = {"name": "p"}
    session.loop_thread = _live_thread()

    assert runtime.loop_stop is True
    assert runtime.loop_paused is True
    assert runtime.active_preset == "preset-a"
    assert runtime.last_run_req == {"card_id": 1}
    assert runtime.last_preset == {"name": "p"}
    assert session.loop_active() is True

    runtime.loop_stop = False
    assert session.loop_stop is False


def test_reset_runtime_clears_run_scoped_state_but_not_runner_infrastructure():
    # Unchanged contract: a fresh login must not inherit the previous account's
    # resume target, but the runner/loop infrastructure survives.
    session = Session(name="runner-state-reset")
    runner = session.runner
    session.active_preset = "p"
    session.last_run_req = {"card_id": 1}
    session.last_preset = {"name": "p"}
    session.loop_stop = True
    session.loop_paused = True
    thread = _live_thread()
    session.loop_thread = thread

    session.reset_runtime()

    assert session.active_preset is None
    assert session.last_run_req is None
    assert session.last_preset is None
    assert session.runner is runner
    assert session.loop_thread is thread
    assert session.loop_stop is True
    assert session.loop_paused is True


# --- invariant 1: account isolation ------------------------------------------

def test_each_account_gets_its_own_runtime():
    mgr = SessionManager(base_dir=".")
    a = mgr.get("iso-a")
    b = mgr.get("iso-b")

    assert get_career_runtime(a) is not get_career_runtime(b)
    assert a.runner is not b.runner

    a.loop_stop = True
    a.loop_paused = True
    a.active_preset = "a-preset"
    a.last_run_req = {"card_id": 1}
    a.last_preset = {"name": "a"}
    a.loop_thread = _live_thread()

    assert b.loop_stop is False
    assert b.loop_paused is False
    assert b.active_preset is None
    assert b.last_run_req is None
    assert b.last_preset is None
    assert b.loop_thread is None
    assert b.loop_active() is False


def test_two_session_managers_do_not_share_runner_state():
    # The reason the registry keys on the Session and NOT on the account name:
    # configure_runtime(tmp_path) and the tests build their own managers, and a
    # name-keyed registry would hand both the same runner for "shared-name".
    left = SessionManager(base_dir=".")
    right = SessionManager(base_dir=".")

    a = left.get("shared-name")
    b = right.get("shared-name")

    assert a is not b
    assert a.runner is not b.runner
    a.loop_stop = True
    assert b.loop_stop is False


def test_readded_account_does_not_inherit_the_removed_runtime():
    # remove() + get() must rebuild from scratch: inheriting the stopped runner
    # (or a stale loop_stop=True) would break the very next run of that account.
    mgr = SessionManager(base_dir=".")
    first = mgr.get("recycled")
    first_runner = first.runner
    first.loop_stop = True
    first.active_preset = "stale"
    first.last_run_req = {"card_id": 1}

    mgr.remove("recycled")
    second = mgr.get("recycled")

    assert second is not first
    assert second.runner is not first_runner
    assert second.loop_stop is False
    assert second.active_preset is None
    assert second.last_run_req is None


# --- invariant 2: runner lifecycle -------------------------------------------

def test_remove_stops_the_runner():
    mgr = SessionManager(base_dir=".")
    session = mgr.get("lifecycle-remove")
    spy = StopSpy(running=True)
    session.runner = spy

    mgr.remove("lifecycle-remove")

    assert spy.stops == 1
    assert session.loop_stop is True
    assert mgr.names() == []


def test_remove_stops_the_qr_child_process():
    mgr = SessionManager(base_dir=".")
    session = mgr.get("lifecycle-remove-qr")
    qr = QrStopSpy()
    session._qr = qr

    mgr.remove("lifecycle-remove-qr")

    assert qr.stops == 1
    assert mgr.names() == []


def test_discard_does_not_stop_the_runner():
    mgr = SessionManager(base_dir=".")
    session = mgr.get("lifecycle-discard")
    spy = StopSpy(running=True)
    session.runner = spy

    mgr.discard("lifecycle-discard")

    assert spy.stops == 0
    assert session.loop_stop is False
    assert mgr.names() == []


def test_stop_signal_survives_removal_from_the_manager():
    # The run-loop thread keeps its own reference to the Session and polls
    # session.loop_stop. Dropping the Session from the manager must NOT make the
    # registry mint a fresh loop_stop=False runtime underneath the loop -- that
    # would strand the thread forever.
    mgr = SessionManager(base_dir=".")
    session = mgr.get("lifecycle-signal")
    spy = StopSpy(running=True)
    session.runner = spy
    runtime = get_career_runtime(session)

    mgr.remove("lifecycle-signal")

    assert session.loop_stop is True
    assert session.runner is spy
    assert get_career_runtime(session) is runtime


def test_remove_survives_a_runner_that_refuses_to_stop():
    # A raising runner must not abort the removal (the account is still dropped)
    # and must not propagate out of SessionManager.
    mgr = SessionManager(base_dir=".")
    session = mgr.get("lifecycle-raises")
    spy = StopSpy(running=True, fail_stop=True)
    session.runner = spy

    mgr.remove("lifecycle-raises")

    assert spy.stops == 1
    assert session.loop_stop is True
    assert mgr.names() == []


# --- invariant 3: the process-wide singleton ---------------------------------

def test_runtime_follows_the_session_manager_singleton(drop_sessions):
    drop_sessions("runner-state-singleton")
    from core.settings import Settings
    import backend.app.context as context
    context.configure_runtime(str(Settings.BASE_DIR))

    assert get_session_manager() is context.session_manager

    via_singleton = get_session_manager().get("runner-state-singleton")
    via_context = context.session_manager.get("runner-state-singleton")

    assert via_context is via_singleton
    assert get_career_runtime(via_context) is get_career_runtime(via_singleton)

    via_singleton.active_preset = "written-through-the-singleton"
    assert via_context.active_preset == "written-through-the-singleton"
    assert via_context.runner is via_singleton.runner


# --- invariant 4: require_idle semantics -------------------------------------

def test_require_idle_blocks_a_running_runner():
    session = Session(name="require-idle-running")
    session.runner = StopSpy(running=True)

    assert require_idle(session) == BUSY


def test_require_idle_blocks_an_active_loop_even_when_the_runner_is_idle():
    session = Session(name="require-idle-loop")
    session.runner = StopSpy(running=False)
    session.loop_thread = _live_thread()

    assert require_idle(session) == BUSY


def test_require_idle_allows_an_idle_session():
    session = Session(name="require-idle-idle")
    session.runner = StopSpy(running=False)

    assert require_idle(session) is None


def test_require_idle_still_accepts_duck_typed_sessions():
    # The offline route-guard doubles (tests/test_session_guarded_routes.py) are
    # not Sessions; the move must not have tightened the guard onto the class.
    duck = SimpleNamespace(runner=StopSpy(running=True), loop_active=lambda: False)

    assert require_idle(duck) == BUSY
