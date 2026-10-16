"""Career-runner + multi-run-loop state, owned by the application layer.

§13.2 B2 final step. `uma_api/session.py` is the TRANSPORT-side per-account
store; the `CareerRunner` and the multi-career loop it drives are application
concerns (they orchestrate backend services, not the wire). They used to live on
`Session` as a `_LoopState` field, which made the transport layer the owner of
the run lifecycle.

Ownership now lives here:

* `CareerRuntime` -- ONE account's runner + loop flags + resume memo.
* `get_career_runtime(session)` -- the registry that binds a runtime to the
  `Session` that represents that account in this process.

`Session` keeps the seven property shims (`runner`, `loop_thread`, `loop_stop`,
`loop_paused`, `active_preset`, `last_run_req`, `last_preset`) plus
`loop_active()` as thin delegators onto this module, so the ~40 existing call
sites are untouched and can migrate to `get_career_runtime()` later.

**Why the registry is keyed by the Session object and not by the account name.**
A process-wide `{name: runtime}` map would violate two §1.3 invariants:

* account isolation -- `backend.app.context.configure_runtime(tmp_path)` and the
  tests build their own `SessionManager`s; a name-keyed map would hand two
  different managers the SAME runner for the same account name;
* runner lifecycle -- `SessionManager.remove(name)` stops the runner and drops
  the Session; the next `get(name)` builds a FRESH Session, which must get a
  FRESH runner, not inherit the stopped one.

Keying on the Session object reproduces today's "one runtime per Session"
semantics exactly, and the `WeakKeyDictionary` means a dropped Session takes its
runtime with it. Entries are NEVER evicted explicitly: the run-loop thread reads
`session.loop_stop` through the shim, so evicting a live Session's runtime would
resurrect a fresh `loop_stop=False` runtime and strand the loop forever.
"""

import threading
import weakref
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from career_bot.engine import CareerRunner
    from uma_api.session import Session


@dataclass
class CareerRuntime:
    """Runner + loop state for ONE account. Application-owned, Session-scoped."""

    runner: Optional["CareerRunner"] = None
    loop_thread: Optional[threading.Thread] = None
    loop_stop: bool = False
    # Pause = save-and-exit: halts the multi-run loop WITHOUT a hard stop (loop_stop would
    # make the loop call runner.stop(), clobbering the "paused" status). Cleared on every
    # launch/resume.
    loop_paused: bool = False
    active_preset: Optional[str] = None
    # Last career-run request + resolved preset, kept so RESUME (after a pause/save-exit)
    # can re-run the same career from the server's saved state.
    last_run_req: Any = None
    last_preset: Optional[dict] = None

    def loop_active(self) -> bool:
        return bool(self.loop_thread and self.loop_thread.is_alive())

    def reset_run_scoped(self) -> None:
        """Clear the run-scoped fields a fresh login must not inherit.

        Deliberately does NOT touch runner/loop_thread/loop flags -- that is
        runner infrastructure and survives a login/leave-session boundary (see
        `Session.reset_runtime`)."""
        self.active_preset = None
        self.last_run_req = None
        self.last_preset = None


# session object -> its runtime. See the module docstring for why the key is the
# Session and not the account name.
_runtimes: "weakref.WeakKeyDictionary[Session, CareerRuntime]" = weakref.WeakKeyDictionary()
_runtimes_lock = threading.Lock()


def get_career_runtime(session: "Session") -> CareerRuntime:
    """The one CareerRuntime bound to this Session, created on first use.

    Creation is eager in practice: `Session.__post_init__` calls this, so the
    `CareerRunner(base_dir)` construction happens at exactly the same moment it
    did when the runner was a `__post_init__` field (no lifecycle-order change).
    """
    with _runtimes_lock:
        runtime = _runtimes.get(session)
        if runtime is None:
            # Call-time import (§13.2 B2): importing this module must stay cheap
            # enough for the `require_idle` guard callers; only actually binding a
            # runtime drags the decision engine in.
            from career_bot.engine import CareerRunner

            runtime = CareerRuntime(
                runner=CareerRunner(session.base_dir, session.state_root)
            )
            _runtimes[session] = runtime
        return runtime


def peek_career_runtime(session: "Session") -> Optional[CareerRuntime]:
    """The bound runtime, or None -- never creates one. For assertions/diagnostics."""
    with _runtimes_lock:
        return _runtimes.get(session)


def require_idle(session: "Session"):
    """Guard for routes that must not run while this account's career is active.

    Moved verbatim from `uma_api/session.py` (§13.2 B2 final step): the
    `{"success": False, "detail": ...}` envelope is an application response, not
    a transport concern. Deliberately duck-typed on `.runner` / `.loop_active()`
    so the offline route-guard doubles keep working."""
    if session.runner.snapshot().get("running") or session.loop_active():
        return {"success": False, "detail": "Career is running — stop it first."}
    return None
