import glob
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from dataclasses import dataclass, field

from core.settings import Settings
from core.runtime_paths import resolve_state_root

if TYPE_CHECKING:
    from backend.app.runner_state import CareerRuntime
    from uma_api.steam_auth import QrLoginSession

log = logging.getLogger(__name__)


def _default_selection() -> dict:
    return {"deck": None, "friend": None, "trainee": None, "veterans": []}


def _default_delay_config() -> dict:
    """Per-account pacing, seeded from the delay-module defaults. The Web UI overrides
    these per account (main.set_turn_delay); the live values are pushed onto this
    account's TimingDNA via apply_delay_to_dna so parallel accounts don't share pacing.

    career_bot.delay is imported at call time (§13.2 B2 step 2): the transport-side
    session module must not drag the decision engine in at import; the values were
    already read per-call from the module, so semantics are unchanged."""
    from career_bot import delay as _delay

    return {
        "min": _delay.TURN_DELAY_MIN,
        "max": _delay.TURN_DELAY_MAX,
        "restore_min": _delay.TURN_DELAY_RESTORE_MIN,
        "restore_max": _delay.TURN_DELAY_RESTORE_MAX,
        "disabled": _delay.GLOBAL_DELAYS_DISABLED,
    }


@dataclass
class _LineageCache:
    parent_cards: dict = field(default_factory=dict)
    parent_rank_points: dict = field(default_factory=dict)
    # trained_chara_id -> already-multiplied G1/group-match bonus points for the
    # parent and its 2 direct grandparents. Populated alongside parent_cards.
    parent_g1_wins: dict = field(default_factory=dict)
    # Raw lineage records used for relation triples, the parent-parent G1/group
    # comparison, and reload-safe recomputation when master.mdb is replaced.
    parent_g1_sources: dict = field(default_factory=dict)
    # Friend trained_chara_id values are scoped to the friend's account, so rental
    # parent rank-point data must not share the owned-parent namespace above.
    # Both rental caches are keyed by (viewer_id, trained_chara_id).
    rental_parent_cards: dict = field(default_factory=dict)
    rental_parent_g1_wins: dict = field(default_factory=dict)
    rental_parent_g1_sources: dict = field(default_factory=dict)


@dataclass(eq=False)
class Session:
    """Per-account TRANSPORT state. One per Uma account.

    eq=False keeps identity semantics (and therefore hashability): a Session IS
    the process's handle for one account, never a value to compare field-by-field
    -- and the application-layer runner registry (backend/app/runner_state.py)
    keys its per-account runtime on this object.
    """
    name: str
    base_dir: str = "."
    state_root: str | None = None
    client: Any = None
    account: Optional[dict] = None
    dashboard_data: Optional[dict] = None
    start_state: dict = field(default_factory=dict)
    user_info_cache: dict = field(default_factory=dict)
    lineage: _LineageCache = field(default_factory=_LineageCache)
    selection: dict = field(default_factory=_default_selection)
    raw_load_index_response: Any = None
    pending_game_auth_config: dict = field(default_factory=dict)
    pending_transition_config: dict = field(default_factory=dict)
    # per-account pacing (turn delay range + No-CD); applied to this account's DNA
    delay_config: dict = field(default_factory=_default_delay_config)
    # last successful event-info (load/index), served while a career run is active so
    # the dashboard never fires a mid-run load/index (which 201s + desyncs the run).
    event_info_cache: Optional[dict] = None
    if TYPE_CHECKING:
        # Lazily stashed by the Steam QR login route
        # (backend/app/routers/steam/services/steam_service.py), which reads it
        # back through `getattr(session, "_qr", None)` -- so at runtime the
        # attribute is genuinely absent until the first qr_start.
        #
        # TYPE-ONLY, with zero runtime effect: the block never executes, so the
        # annotation never reaches `__annotations__` at class-body execution
        # time and @dataclass never sees a new field (no __init__ parameter, no
        # fields() entry, no repr change). `init=False, default=None` is what
        # makes the type-level picture match that runtime reality instead of
        # lying about it -- mypy rejects `Session(_qr=...)` just as runtime
        # would, and reading it yields `None`, exactly like the getattr default
        # the only reader uses.
        _qr: "QrLoginSession | None" = field(init=False, default=None)

    def __post_init__(self):
        if self.state_root is None:
            self.state_root = str(resolve_state_root(self.base_dir).root)
        # Bind this account's runner/loop runtime NOW, so the CareerRunner is built
        # at exactly the moment it used to be (no lifecycle-order change). The
        # runtime itself is owned by the application layer (see _runtime below).
        from backend.app.runner_state import get_career_runtime

        get_career_runtime(self)

    @property
    def _runtime(self) -> "CareerRuntime":
        """This account's application-owned runner/loop state.

        Call-time import (§13.2 B2 final step): the runner + multi-run loop moved
        to backend/app/runner_state.py, and the transport module must not import
        the application layer (nor, transitively, the decision engine) merely to
        be imported. Every shim below is a delegator onto this object; new code
        should call `backend.app.runner_state.get_career_runtime(session)`
        directly instead of reaching through the Session."""
        from backend.app.runner_state import get_career_runtime

        return get_career_runtime(self)

    @property
    def parent_cards(self):
        return self.lineage.parent_cards

    @parent_cards.setter
    def parent_cards(self, v):
        self.lineage.parent_cards = v

    @property
    def parent_rank_points(self):
        return self.lineage.parent_rank_points

    @parent_rank_points.setter
    def parent_rank_points(self, v):
        self.lineage.parent_rank_points = v

    @property
    def parent_g1_wins(self):
        return self.lineage.parent_g1_wins

    @parent_g1_wins.setter
    def parent_g1_wins(self, v):
        self.lineage.parent_g1_wins = v

    @property
    def parent_g1_sources(self):
        return self.lineage.parent_g1_sources

    @parent_g1_sources.setter
    def parent_g1_sources(self, v):
        self.lineage.parent_g1_sources = v

    @property
    def rental_parent_cards(self):
        return self.lineage.rental_parent_cards

    @rental_parent_cards.setter
    def rental_parent_cards(self, v):
        self.lineage.rental_parent_cards = v

    @property
    def rental_parent_g1_wins(self):
        return self.lineage.rental_parent_g1_wins

    @rental_parent_g1_wins.setter
    def rental_parent_g1_wins(self, v):
        self.lineage.rental_parent_g1_wins = v

    @property
    def rental_parent_g1_sources(self):
        return self.lineage.rental_parent_g1_sources

    @rental_parent_g1_sources.setter
    def rental_parent_g1_sources(self, v):
        self.lineage.rental_parent_g1_sources = v

    # --- application-layer runner/loop shims -------------------------------
    # Thin delegators onto the CareerRuntime above (§13.2 B2 final step). They
    # exist so the ~40 existing `session.runner` / `session.loop_*` call sites did
    # not have to churn in the same change that moved the ownership.

    @property
    def runner(self):
        return self._runtime.runner

    @runner.setter
    def runner(self, v):
        self._runtime.runner = v

    @property
    def loop_thread(self):
        return self._runtime.loop_thread

    @loop_thread.setter
    def loop_thread(self, v):
        self._runtime.loop_thread = v

    @property
    def loop_stop(self):
        return self._runtime.loop_stop

    @loop_stop.setter
    def loop_stop(self, v):
        self._runtime.loop_stop = v

    @property
    def loop_paused(self):
        return self._runtime.loop_paused

    @loop_paused.setter
    def loop_paused(self, v):
        self._runtime.loop_paused = v

    @property
    def active_preset(self):
        return self._runtime.active_preset

    @active_preset.setter
    def active_preset(self, v):
        self._runtime.active_preset = v

    @property
    def last_run_req(self):
        return self._runtime.last_run_req

    @last_run_req.setter
    def last_run_req(self, v):
        self._runtime.last_run_req = v

    @property
    def last_preset(self):
        return self._runtime.last_preset

    @last_preset.setter
    def last_preset(self, v):
        self._runtime.last_preset = v

    def reset_runtime(self):
        """Clear logged-in state (mirrors the login() global reset).

        Called only at explicit auth boundaries -- AuthService.login (fresh login)
        and leave_session() -- never during a runner relogin (the runner re-auths via
        client.login(), which does not touch the Session). So every per-account
        runtime field that a NEW login would repopulate must be cleared here, or it
        leaks into the next account. The run-scoped fields below were previously
        omitted -- most importantly last_run_req/last_preset, which made a fresh
        login inherit the PREVIOUS account's resume target (a cross-account RESUME
        footgun).

        Deliberately NOT reset: pending_game_auth_config (login() carries it across
        this reset for the 2FA retry), runner/loop_thread/loop flags (runner
        infrastructure), and delay_config (per-account pacing, re-applied on login).
        """
        self.client = None
        self.account = None
        self.dashboard_data = None
        self.start_state = {}
        self.user_info_cache = {}
        self.parent_cards = {}
        self.parent_rank_points = {}
        self.parent_g1_wins = {}
        self.parent_g1_sources = {}
        self.rental_parent_cards = {}
        self.rental_parent_g1_wins = {}
        self.rental_parent_g1_sources = {}
        self.raw_load_index_response = None
        self.pending_transition_config = {}
        self.selection = _default_selection()
        # run-scoped state — must not survive a login/leave-session boundary
        self.event_info_cache = None
        self._runtime.reset_run_scoped()   # active_preset / last_run_req / last_preset

    def loop_active(self) -> bool:
        return self._runtime.loop_active()

    def apply_delay_to_dna(self):
        """Push this account's delay_config onto its live TimingDNA (after login and on
        every settings change) so the per-account pacing actually takes effect. No-op
        until logged in (the DNA is bound when the GateKeeper wraps the client)."""
        dna = getattr(self.client, "_dna", None)
        if dna is not None and hasattr(dna, "set_delay_config"):
            cfg = self.delay_config
            dna.set_delay_config(
                turn_delay_min=cfg.get("min"),
                turn_delay_max=cfg.get("max"),
                disabled=cfg.get("disabled"),
            )


class SessionManager:
    """Owns every Session. Serializes add-account operations."""

    def __init__(self, base_dir: str = ".", state_root: str | None = None):
        self.base_dir = base_dir
        self.state_root = str(
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(base_dir).root
        )
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self.add_lock = threading.Lock()   # Steam QR add-account serialization

    def accounts_dir(self) -> str:
        return os.path.join(self.state_root, "accounts")

    def known_account_names(self) -> list[str]:
        """Account names persisted on disk (<name>.json, excluding .steam.json)."""
        pattern = os.path.join(self.accounts_dir(), "*.json")
        names = []
        for path in glob.glob(pattern):
            base = os.path.basename(path)
            if base.endswith(".steam.json"):
                continue
            names.append(base[:-len(".json")])
        return sorted(names)

    def get(self, name: str) -> Session:
        with self._lock:
            s = self._sessions.get(name)
            if s is None:
                s = Session(
                    name=name,
                    base_dir=self.base_dir,
                    state_root=self.state_root,
                )
                self._sessions[name] = s
            return s

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions.keys())

    def discard(self, name: str) -> None:
        """Drop a cached Session without touching its runner.

        remove() is the lifecycle-aware variant that also stops the runner.
        """
        with self._lock:
            self._sessions.pop(name, None)

    def remove(self, name: str):
        with self._lock:
            s = self._sessions.pop(name, None)
        if s is not None:
            self._stop_session(name, s)

    def shutdown(self) -> None:
        """Stop every live per-account worker before the application exits."""
        with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        for name, session in sessions:
            self._stop_session(name, session)

    @staticmethod
    def _stop_session(name: str, session: Session) -> None:
        session.loop_stop = True
        qr = getattr(session, "_qr", None)
        if qr is not None:
            try:
                qr.stop()
            except Exception as exc:
                log.warning(f"[SessionManager] QR stop failed for {name}: {exc}")
        try:
            session.runner.stop()
        except Exception as exc:
            log.warning(f"[SessionManager] runner.stop() failed for {name}: {exc}")

    def snapshot_all(self) -> list[dict]:
        with self._lock:
            sessions = dict(self._sessions)
        disk_names = set(self.known_account_names())
        out = []
        # Union of in-memory sessions and on-disk accounts not yet loaded.
        names = set(sessions) | disk_names
        for name in sorted(names):
            s = sessions.get(name)
            if s is None:
                out.append({"name": name, "logged_in": False, "running": False,
                            "loop_active": False, "account": None, "runner": None})
                continue
            # Read outside _lock: GIL makes these field reads safe; a slightly
            # stale/cross-inconsistent status is acceptable for a display snapshot.
            snap = s.runner.snapshot()
            logged_in = s.client is not None
            running = bool(snap.get("running"))
            loop_active = s.loop_active()
            # Skip bare, lazily-created sessions with no persisted file and no live
            # state: get_session() creates one for ANY X-Account header, so a stray
            # poll after an account was deleted would otherwise resurrect it here.
            if name not in disk_names and not logged_in and not running and not loop_active:
                continue
            out.append({
                "name": name,
                "logged_in": logged_in,
                "running": running,
                "loop_active": loop_active,
                "account": s.account,
                "runner": snap,
            })
        return out


_session_manager: Optional[SessionManager] = None
_session_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """Process-wide singleton SessionManager. Every consumer of per-account Session
    state (FastAPI dependency, legacy app, CLI) MUST go through this accessor --
    constructing SessionManager(...) directly elsewhere creates a second, isolated
    pool of Sessions that silently diverges from the "real" one (e.g. a turn-delay
    change written to a throwaway Session that the running bot never sees)."""
    global _session_manager
    if _session_manager is None:
        with _session_manager_lock:
            if _session_manager is None:
                paths = resolve_state_root(Settings.BASE_DIR)
                _session_manager = SessionManager(
                    base_dir=str(Settings.BASE_DIR),
                    state_root=str(paths.root),
                )
    return _session_manager
