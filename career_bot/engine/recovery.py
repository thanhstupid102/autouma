"""Career state recovery methods for CareerRunner, extracted verbatim from runner.py."""

import logging
from typing import TYPE_CHECKING, Any, Iterable

from uma_api.errors import UnsupportedScenarioError, api_error_result_code
from uma_api.update_guard import AuthInvalidatedError

log = logging.getLogger(__name__)


def _strategy_endpoint_prefix(strategy):
    return getattr(strategy, "endpoint_prefix", None) or "single_mode_free"


def _active_strategy(host, strategy):
    return strategy or getattr(host, "strategy", None)


def dna_sleep(*args, **kwargs):
    from career_bot.engine import runner
    return runner.dna_sleep(*args, **kwargs)


def backoff_sleep(*args, **kwargs):
    # Same call-time indirection as dna_sleep above: runner.py owns the module-level
    # name that tests rebind, so this must resolve through the runner module on every
    # call instead of freezing career_bot.delay's function at import time.
    from career_bot.engine import runner
    return runner.backoff_sleep(*args, **kwargs)


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerRecoveryMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerRecoveryMixin(_HostState):
    def _is_state_recovery_error(self, exc):
        msg = str(exc)
        return "201" in msg or "StateRecoveryError" in msg

    def _recover_state_error(self, client, strategy, turn, action, exc):
        self._log(action, turn, f"reloaded after {exc}")
        return self._fresh_career_state(client, strategy)

    def _fresh_career_state(self, client, strategy=None, relogin_first=False, preserve_item_failures=False):
        from career_bot.engine.runner import RunFatalError

        strategy = _active_strategy(self, strategy)
        errors = []
        max_retries = 8
        preserved_failed_use = set(self.item_manager.failed_use_this_turn) if preserve_item_failures else None
        preserved_item_turn = self.item_manager.current_turn if preserve_item_failures else None
        for attempt in range(max_retries):
            # relogin_first: the no-relogin load on attempt 0 is doomed (e.g. right
            # after a race_out 201 the session is already dead and the bare load just
            # 201s again -- a wasted breaker-counted error). Skip straight to relogin.
            relogin = attempt > 0 or relogin_first
            try:
                if relogin:
                    if not hasattr(client, "login"):
                        break
                    try:
                        client.login()
                    except Exception as e:
                        if "Network error" in str(e) or api_error_result_code(e) in (102, 201, 208):
                            raise e
                        else:
                            raise
                if hasattr(client, "load_career"):
                    state = client.load_career()
                else:
                    state = client.call(f"{_strategy_endpoint_prefix(strategy)}/load", {})
                if strategy and (state.get("data") or {}).get("unchecked_event_array"):
                    state = self._drain_events(client, strategy, state, recover_on_state_error=False)
                self.skill_buyer.reset_scoped_failures()
                self.item_manager.reset_scoped_failures()
                if preserve_item_failures:
                    self.item_manager.failed_use_this_turn = set(preserved_failed_use or set())
                    self.item_manager.current_turn = preserved_item_turn
                return state
            except Exception as exc:
                if isinstance(exc, (UnsupportedScenarioError, AuthInvalidatedError)):
                    # This cannot improve with a relogin or hard reset; both would
                    # merely repeat an unroutable career-load or dead-auth attempt.
                    raise
                err_str = str(exc)
                errors.append(err_str)
                if attempt < max_retries - 1:
                    backoff_sleep(attempt, base=6.0, cap=20.0)
        if hasattr(client, "hard_reset"):
            return client.hard_reset()
        raise RunFatalError("career recovery failed: " + " | ".join(errors[-2:]))

    def _recover_race_out(self, client, strategy, turn, action, exc, program_id=None):
        """Recover a 201 on race_out.

        Tier 1 -- retry race_out in place (clears a transient desync without the
        reload that corrupts the race state).

        Tier 2 -- if still stuck, the career is parked mid-race-exit at playing_state
        3 (race already ended: race_end returns 102, race_out 201s). The recovery path
        that lands here (scenario `race_progress` for ps3) SKIPS race_entry, but the
        only sequence the server actually completes a race with is the full
        race_entry -> race_start -> race_end -> race_out (proven by successful logs).
        So re-ENTER the race fresh to reset the corrupted half-state and replay the
        full sequence. This recovers the career instead of forcing a delete.

        Tier 3 -- if even a fresh re-entry can't clear it, stop with actionable
        guidance (never spin the circuit breaker).
        """
        from career_bot.engine.runner import RunFatalError

        if self._race_recover_turn != turn:
            self._race_recover_turn = turn
            self._race_recover_count = 0

        # Tier 1: in-place retries.
        for i in range(self._RACE_OUT_INPLACE_RETRIES):
            self._race_recover_count += 1
            delay = min(1.0 * (2 ** i), 8.0)
            self._log(action, turn, f"race_out 201 in-place retry {i + 1}/{self._RACE_OUT_INPLACE_RETRIES}; wait {delay:.0f}s")
            dna_sleep(delay, delay)
            try:
                return client.race_out(current_turn=turn)
            except Exception as e:
                if not self._is_state_recovery_error(e):
                    raise
                exc = e

        # Tier 2: full re-entry reset (once per turn). A genuine stuck race keeps the
        # SESSION alive (only race_out 201s), so race_entry succeeds and the full
        # re-entry sequence clears it. If race_entry ITSELF 201s, the whole session is
        # dead (e.g. the 10:00 daily reset forced a relogin) -- that is NOT a corrupted
        # race, so Tier 2.5 relogins + resumes rather than force-abandoning the career.
        session_dead = False
        if program_id and self._race_reset_turn != turn:
            self._race_reset_turn = turn
            self._log("race_reset", turn, f"re-entering race {program_id} to clear stuck exit")
            try:
                client.race_entry(program_id=program_id, current_turn=turn)
            except Exception as e:
                if not self._is_state_recovery_error(e):
                    raise
                session_dead = True  # re-entry rejected -> session expired, not a stuck race
                exc = e
            if not session_dead:
                try:
                    client.race_start(is_short=1, current_turn=turn)
                    try:
                        client.race_end(current_turn=turn)
                    except Exception as e:
                        if api_error_result_code(e) not in (102, 1503):
                            raise
                    out = client.race_out(current_turn=turn)
                    self._log("race_reset_ok", turn, "stuck race cleared via re-entry")
                    return out
                except Exception as e:
                    self._log("race_reset_failed", turn, str(e))
                    if not self._is_state_recovery_error(e):
                        raise
                    exc = e

        # Tier 2.5: dead session (mass 201 -- daily reset / forced relogin). Relogin to
        # re-establish the session and resume the career from its true server state; the
        # runner then continues normally (clearing the race exit on the LIVE session).
        # Safe ONLY because we reached here via race_entry 201 (session dead), never via
        # the stuck-race path (session alive) which must not reload (corrupts to ps3 lock).
        if session_dead:
            if self._race_relogin_turn != turn:
                self._race_relogin_turn = turn
                self._race_relogin_count = 0
            if self._race_relogin_count < self._RACE_RELOGIN_RETRIES:
                self._race_relogin_count += 1
                self._log("race_out_relogin", turn,
                          f"race_entry 201 (session expired -- daily reset/forced relogin); "
                          f"relogin + resume {self._race_relogin_count}/{self._RACE_RELOGIN_RETRIES}")
                try:
                    state = self._fresh_career_state(client, strategy, relogin_first=True)
                    # Fresh session: let Tier 1/2 run again if the runner re-sticks.
                    self._race_reset_turn = None
                    self._race_recover_turn = None
                    self._log("race_out_resumed", turn, "career resumed after relogin")
                    return state
                except RunFatalError:
                    raise
                except Exception as e:
                    self._log("race_out_relogin_failed", turn, str(e))
                    exc = e

        self._log("race_out_stuck", turn, f"race_out rejected after {self._race_recover_count} attempts + reset ({exc})")
        # RunFatalError: a reload here corrupts the career into a permanent
        # playing_state-3 lock, so the central _run crash-retry must NOT reload --
        # it stops the career with this actionable message instead.
        raise RunFatalError(
            f"race_out rejected by the server on turn {turn} even after a full race "
            f"re-entry. The race result is committed but the game won't leave the result "
            f"screen. If this persists on re-run, the career's server-side state is "
            f"corrupted -- delete this career (force-abandon) and start a new one."
        )

    def _blocked_playing_state(self, chara):
        # Extra scenario states come from the active strategy; Unity Cup uses
        # 7/8/9 for team-race phases (ready/started/ended), not blocked states.
        playing_state = int((chara or {}).get("playing_state") or 1)
        extra: Iterable[Any] = getattr(getattr(self, "strategy", None), "extra_playing_states", frozenset()) or frozenset()
        return playing_state not in ({1, 2, 3, 4, 5} | set(extra))

    def _recover_blocked_state(self, client, strategy, state):
        strategy = _active_strategy(self, strategy)
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        if int(chara.get("playing_state") or 0) == 6:
            turn = chara.get("turn", 1)
            if hasattr(client, "minigame_end"):
                state = client.minigame_end(current_turn=turn)
            else:
                state = client.call(f"{_strategy_endpoint_prefix(strategy)}/minigame_end", {
                    "result": {
                        "result_state": 1,
                        "result_value": 0,
                        "result_detail_array": None,
                    },
                    "current_turn": turn,
                })
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):
                state = self._drain_events(client, strategy, state)
            return state
        try:
            if hasattr(client, "hard_reset"):
                state = client.hard_reset()
            else:
                state = self._fresh_career_state(client, strategy)
        except Exception as e:
            log.warning(f"Blocked State Recovery Failure: {e}")
            return state
        return state

    def _sync_item_use_recovery_turn(self, turn):
        turn = int(turn or 0)
        if self._item_use_recover_turn != turn:
            self._item_use_recover_turn = turn
            self._item_use_recover_count = 0
            if self._item_use_blocked_turn != turn:
                self._item_use_blocked_turn = None
        return turn

    def _item_use_recovery_blocked(self, turn):
        turn = self._sync_item_use_recovery_turn(turn)
        return self._item_use_blocked_turn == turn

    def _allow_item_use_recovery(self, turn):
        turn = self._sync_item_use_recovery_turn(turn)
        self._item_use_recover_count += 1
        if self._item_use_recover_count >= self._ITEM_USE_RECOVERY_CAP:
            self._item_use_blocked_turn = turn
            self._log(
                "items_use_recovery_cap",
                turn,
                f"skipping item use for rest of turn after {self._item_use_recover_count} recoveries",
            )
            return False
        return True
