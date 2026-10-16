import logging
import threading
import time
from typing import TYPE_CHECKING, cast

from backend.app.services import game_login
from uma_api import game_service
from backend.app import context
import backend.app.domain.account_status as account_status
import backend.app.domain.account_store as account_store
import backend.app.domain.career_selection as career_selection
from backend.app.domain import preset_runtime
from career_bot.outcomes import career_failed, career_retry_block_reason
from core.settings import Settings

from ..schemas.career import RunCareerRequest
from .career_start import _master_data_preflight_failure

if TYPE_CHECKING:
    from career_bot.planning.presets import PresetStore, RacePresetStore
    # Type-only base: declares the CareerService state / sibling-mixin handlers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class CareerRunMixin:` would produce.
    from .service_state import CareerServiceState
    _HostState = CareerServiceState
else:
    _HostState = object


log = logging.getLogger(__name__)

MAX_RESUME_ATTEMPTS = 3

# The three signals a loop step can hand back. They are exactly the three
# control-flow words the inline loop body used:
#   _NEXT_CYCLE -> `continue` / fall through to the next `while` iteration
#   _STOP       -> `return` out of the loop
#   _BREAK      -> `break` out of the `while`
# _STOP and _BREAK end the run identically (nothing followed the `while`); they
# stay distinct so each step still says which one the original code took.
_NEXT_CYCLE = "next-cycle"
_STOP = "stop"
_BREAK = "break"


class _CareerLoop:
    """One multi-career run of the career loop.

    Owns the state the loop body used to carry in locals and in the
    ``_restart_current_run`` closure: the counters (``consecutive_fails``,
    ``runs_done``, ``resume_attempts``), the result the next runner launch is
    seeded with (``current_result``), and the collaborators every step needs.
    Every step returns one of the ``_NEXT_CYCLE`` / ``_STOP`` / ``_BREAK``
    signals above, or ``None`` when the caller should keep going inline.

    Collaborator imports are plain module-level imports (``backend.app.domain``
    sits BELOW ``routers`` in the import graph, so there is no cycle to dodge).
    They stay MODULE imports rather than
    ``from x import y``: every collaborator is reached by attribute at call
    time, which both preserves the monkeypatch seams the tests rely on and
    keeps the §8b stage-6 stale-binding rule (``configure_runtime`` reassigns
    those module globals at runtime).
    """

    def __init__(self, service, req, preset, initial_result):
        session = service.session
        self.service = service
        self.session = session
        self.req = req
        self.preset = preset
        self.runner = session.runner
        self.max_steps = max(1, min(int(req.max_steps or 2500), 3000))
        self.target = max(0, int(getattr(req, "run_count", 1) or 0))  # 0 = run forever
        self.consecutive_fails = 0
        self.current_result = initial_result
        self.runs_done = 0
        self.resume_attempts = 0

    def restart_current_run(self):
        """The runner's force-delete restart hook: refresh load/index, start again."""
        session = self.session
        try:
            load_result = game_service.load_index_live(session, {})
            load_data = load_result.get('data', {})
            account_status.update_start_state(session, load_data)
            session.account = account_status.get_account_status(session, load_data)
        except Exception as refresh_err:
            log.warning(f"[RESTART] load/index refresh after force-delete failed: {refresh_err}")
        started = self.service.start_career_from_request(self.req)
        if not started.get("success"):
            raise RuntimeError(started.get("detail") or "career restart failed")
        result = account_status.unwrap_single_mode_start_common(started["result"])
        account, chara_info = account_status.apply_career_result(session, result)
        session.account = account
        sid = preset_runtime.sync_runtime_preset_scenario(self.preset, result, self.req)
        preset_runtime.apply_runtime_bot_config(self.preset, sid, context.bot_config_store)
        career_selection.apply_deck_type_counts(self.preset, req=self.req, chara_info=chara_info)
        return result

    def _launch_runner(self):
        session = self.session
        set_resume_attempt = getattr(self.runner, "set_resume_attempt", None)
        if callable(set_resume_attempt):
            set_resume_attempt(self.resume_attempts, MAX_RESUME_ATTEMPTS)
        self.runner.set_loop_info(self.runs_done + 1, self.target)
        self.runner.start(
            session.client,
            self.preset,
            self.current_result,
            self.max_steps,
            burn_clocks=self.req.burn_clocks,
            spark_reroll=self.req.spark_reroll,
            dev_mode=True,
            account=session.name,
            restart_callback=self.restart_current_run,
            user_info_cache=session.user_info_cache,
        )

    def _await_runner_exit(self):
        """Poll until the runner stops. True => Stop was pressed (caller returns)."""
        while self.runner.snapshot().get("running"):
            if self.session.loop_stop:
                self.runner.stop()
                return True
            # Orchestration poll, NOT a game-action delay: use a real sleep so it never
            # busy-spins. dna_sleep honors this account's No-CD toggle and would return
            # 0s (pegging a core); the loop thread also isn't bound to the account DNA.
            time.sleep(1.0)
        return False

    def _idle(self, ticks):
        """Sleep ``ticks`` seconds one at a time. True => Stop was pressed."""
        for _ in range(ticks):
            if self.session.loop_stop:
                return True
            time.sleep(1.0)
        return False

    def _handle_runner_error(self, status):
        """Resume ladder for a runner that exited with an error.

        Returns the signal the inline ``continue``/``break`` produced, or
        ``None`` when the loop body falls through to the target check.
        """
        block_reason = career_retry_block_reason(status)
        if block_reason:
            log.warning(
                f"[LOOP] career failure is not retryable -> giving up: "
                f"{block_reason}: {status.get('last_error')}"
            )
            self._set_retry_stage(
                "retry-disabled",
                f"automatic resume disabled: {block_reason}",
            )
            return _BREAK

        if self.resume_attempts >= MAX_RESUME_ATTEMPTS:
            log.warning(
                f"[LOOP] career still stuck after {MAX_RESUME_ATTEMPTS} resume attempts "
                f"-> giving up (manual intervention needed): {status.get('last_error')}"
            )
            self._set_retry_stage(
                "retry-exhausted",
                f"resume attempt {MAX_RESUME_ATTEMPTS}/{MAX_RESUME_ATTEMPTS} "
                "failed; no automatic retries remain",
            )
            return _BREAK

        next_attempt = self.resume_attempts + 1
        if status.get("circuit_tripped"):
            wait_seconds = int(
                Settings.UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS[
                    next_attempt - 1
                ]
            )
            self._set_retry_wait(next_attempt, wait_seconds)
            log.warning(
                f"[LOOP] AUTO-BACKOFF: waiting {wait_seconds}s before resume "
                f"attempt {next_attempt}/{MAX_RESUME_ATTEMPTS}; Stop remains responsive"
            )
            if self._idle(wait_seconds):
                self._set_retry_stage(
                    "retry-cancelled",
                    "automatic resume cancelled by Stop during cooldown",
                )
                return _STOP
        else:
            log.warning(
                f"[LOOP] runner error did not trip the circuit; proceeding to "
                f"session recovery for resume attempt "
                f"{next_attempt}/{MAX_RESUME_ATTEMPTS} without an outer cooldown"
            )

        self._set_retry_stage(
            "retrying",
            f"re-establishing session for resume attempt "
            f"{next_attempt}/{MAX_RESUME_ATTEMPTS}",
        )
        if not self._rerun_session():
            self._set_retry_stage(
                "retry-failed",
                f"session re-run failed before resume attempt "
                f"{next_attempt}/{MAX_RESUME_ATTEMPTS}",
            )
            log.warning(
                f"[LOOP] session re-run failed before resume attempt "
                f"{next_attempt}/{MAX_RESUME_ATTEMPTS} -> giving up without "
                "loading the career against a dead session"
            )
            return _BREAK

        game_service.reset_circuit(self.session)
        if bool(getattr(self.session.client, "circuit_tripped", False)):
            self._set_retry_stage(
                "retry-failed",
                f"circuit reset failed before resume attempt "
                f"{next_attempt}/{MAX_RESUME_ATTEMPTS}",
            )
            log.warning(
                f"[LOOP] circuit remained tripped before resume attempt "
                f"{next_attempt}/{MAX_RESUME_ATTEMPTS} -> giving up"
            )
            return _BREAK

        resumed = self.service._resume_active_career(self.req, self.preset)
        if resumed is not None:
            self.resume_attempts = next_attempt
            self.current_result = resumed
            log.warning(
                f"[LOOP] active career still in progress after error -> RESUMING "
                f"(attempt {self.resume_attempts}/{MAX_RESUME_ATTEMPTS}) instead of starting new: "
                f"{status.get('last_error')}"
            )
            return _NEXT_CYCLE
        self.consecutive_fails += 1
        if self.consecutive_fails >= 3:
            return _BREAK
        return None

    def _record_finished_career(self):
        """The clean-exit book-keeping: counters reset, run counted, career closed."""
        session = self.session
        self.resume_attempts = 0
        self.consecutive_fails = 0
        self.runs_done += 1
        log.info(f"[LOOP] career {self.runs_done}/{self.target if self.target else '∞'} finished")
        if session.account and "career" in session.account and session.account["career"]:
            session.account["career"]["active"] = False

    def _set_retry_wait(self, attempt, wait_seconds):
        setter = getattr(self.runner, "set_retry_wait", None)
        if callable(setter):
            setter(attempt, MAX_RESUME_ATTEMPTS, wait_seconds)

    def _set_retry_stage(self, action, detail):
        setter = getattr(self.runner, "set_retry_stage", None)
        if callable(setter):
            setter(action, detail)

    def _rerun_session(self):
        # EXPERIMENT (user request): RE-RUN THE SESSION before the next loop career so its
        # rental start runs like career-1 of a fresh launch. This is session re-establish
        # (start_session + load/index + read_info) -- NOT a logout / re-auth; with captured
        # auth, the service login wrapper does exactly that (same primitive used by
        # /refresh_session to "re-establish the session ... without a full logout/login").
        session = self.session
        if not session.client or not hasattr(session.client, "login"):
            log.warning("[LOOP] session re-run unavailable: client has no login")
            return False
        try:
            log.info(
                "[LOOP] re-running session "
                "(start_session + load/index + read_info) before continuing"
            )
            res = game_login.login_with_master_refresh(session)
            data = (res or {}).get("data", {})
            game_service.refresh_cached_account_state(session, data)
            account_status.update_start_state(session, data)
            return True
        except Exception as session_rerun_err:
            log.warning(f"[LOOP] pre-career session re-run failed: {session_rerun_err}")
            return False

    def _after_start_failure(self):
        """The failure book-keeping both next-career start paths shared verbatim.

        Returns the signal to hand back, or ``None`` to retry the start.
        """
        self.consecutive_fails += 1
        if self.consecutive_fails >= 5:
            return _BREAK
        if self._idle(15):
            return _STOP
        return None

    def _adopt_started_career(self, started):
        session = self.session
        self.current_result = account_status.unwrap_single_mode_start_common(started["result"])
        account, chara_info = account_status.apply_career_result(session, self.current_result)
        session.account = account
        sid = preset_runtime.sync_runtime_preset_scenario(self.preset, self.current_result, self.req)
        preset_runtime.apply_runtime_bot_config(self.preset, sid, context.bot_config_store)

    def _start_next_career(self):
        """Retry the next career start until it takes, Stop is pressed, or 5 fails."""
        started_ok = False
        while not started_ok and not self.session.loop_stop:
            try:
                started = self.service.start_career_from_request(self.req)
                if not started.get("success"):
                    outcome = self._after_start_failure()
                    if outcome is not None:
                        return outcome
                    continue
                self._adopt_started_career(started)
                started_ok = True
                self.consecutive_fails = 0
            except Exception:
                outcome = self._after_start_failure()
                if outcome is not None:
                    return outcome
        if not started_ok:
            return _BREAK
        return _NEXT_CYCLE

    def _run_cycle(self):
        """One career of the loop: launch, wait, classify the exit, start the next."""
        # Pause = save-and-exit: halt the loop WITHOUT runner.stop() (which would clobber
        # the "paused" status). RESUME re-launches a fresh loop.
        if self.session.loop_paused:
            log.info("[LOOP] paused (save & exit) — loop halted; resume to continue")
            return _STOP
        self._launch_runner()
        if self._await_runner_exit():
            return _STOP

        # The runner exited on its own. If it was a pause/save-exit, stop looping here
        # (do NOT start the next career) — RESUME re-launches the loop.
        if self.session.loop_paused or self.runner.snapshot().get("status") == "paused":
            log.info("[LOOP] career paused (save & exit) — loop halted; resume to continue")
            return _STOP

        status = self.runner.snapshot()
        if career_failed(status):
            outcome = self._handle_runner_error(status)
            if outcome is not None:
                return outcome
        else:
            self._record_finished_career()

        if self.target and self.runs_done >= self.target:
            log.info(f"[LOOP] target reached ({self.runs_done}/{self.target}) — stopping loop")
            return _BREAK

        if self._idle(6):
            return _STOP
        self._rerun_session()
        return self._start_next_career()

    def run(self):
        log.info(f"[LOOP] starting career loop: {'INFINITE (until Stop)' if not self.target else f'{self.target} career(s)'}")
        while not self.session.loop_stop:
            if self._run_cycle() != _NEXT_CYCLE:
                return


class CareerRunMixin(_HostState):
    def _resume_active_career(self, req, preset):
        """Load and normalize an active server-side career for runner resumption."""
        session = self.session
        try:
            try:
                result = game_service.load_career(session)
            except Exception:
                return None

            state = account_status.unwrap_single_mode_start_common(result)
            data = state.get("data") or {}
            chara_info = next(
                (
                    data.get(key)
                    for key in ("chara_info", "single_mode_chara_light", "single_mode_chara")
                    if isinstance(data.get(key), dict)
                    and (data[key].get("card_id") or data[key].get("turn"))
                ),
                None,
            )
            if chara_info is None:
                return None

            account_status.apply_career_result(session, state)
            sid = preset_runtime.sync_runtime_preset_scenario(preset, state, req)
            preset_runtime.apply_runtime_bot_config(preset, sid, context.bot_config_store)
            try:
                career_selection.apply_deck_type_counts(preset, req=req, chara_info=chara_info)
            except Exception:
                pass
            return state
        except Exception:
            return None

    def manage_career_loop(self, req, preset, initial_result):
        _CareerLoop(self, req, preset, initial_result).run()

    def _launch_career_run(self, req, preset):
        import career_bot.delay as delay

        session = self.session
        """Shared launch core for /career/run and /career/runner/resume.

        Resumes the active career (or starts a fresh one), resets the breaker, then starts
        the runner (single) or the multi-run loop. Stores the run request + preset on the
        session so a later RESUME (after a pause/save-exit) can re-run from the saved state.
        Returns the same dict shape as the /career/run endpoint; may raise (callers wrap)."""
        session.last_run_req = req
        session.last_preset = preset
        # A fresh launch/resume clears any leftover pause flag so a new loop doesn't halt
        # immediately on a stale "paused" from a previous career.
        session.loop_paused = False
        set_resume_attempt = getattr(session.runner, "set_resume_attempt", None)
        if callable(set_resume_attempt):
            set_resume_attempt(0, 0)

        account = session.account or {}
        career = account.get("career") or {}
        load_data = {}
        if career.get("active"):
            index_result = game_service.load_index_live(session, {})
            load_data = index_result.get('data', {})
            account_status.update_start_state(session, load_data)

            account = account_status.get_account_status(session, load_data)
            session.account = account
            career = account.get("career") or {}

        if career.get("active"):
            career_result = game_service.load_career(session)
            career_data = career_result.get('data', {})

            account = account_status.get_account_status(session, load_data, career_result)
            session.account = account

            career_status = account.get("career")
            # `or 0` on every field: a resumed career legitimately has no friend
            # (friend_viewer_id/card_id None) or fewer than 2 parents (parent_id_1/2 None),
            # and int(None) crashes the resume ("int() argument must be ... not 'NoneType'").
            req.card_id = int(career_status.get("card_id") or 0)
            req.support_card_ids = career_status.get("support_card_ids")
            req.friend_viewer_id = int(career_status.get("friend_viewer_id") or 0)
            req.friend_card_id = int(career_status.get("friend_card_id") or 0)
            req.parent_id_1 = int(career_status.get("parent_id_1") or 0)
            req.parent_id_2 = int(career_status.get("parent_id_2") or 0)
            req.deck_id = int(career_status.get("deck_id") or 0)
            req.scenario_id = int((career_data.get('chara_info') or {}).get("scenario_id") or career_status.get("scenario_id") or preset.get("scenario_id", 4))

            master_data_error = _master_data_preflight_failure(
                session, req.scenario_id,
            )
            if master_data_error:
                return master_data_error

            chara_info = career_data.get('chara_info') or {}
            if session.dashboard_data:
                session.dashboard_data["account"] = account
            result = career_result
        else:
            if not req.scenario_id:
                req.scenario_id = preset_runtime.resolve_scenario_id(preset)
            started = self.start_career_from_request(req)
            if not started.get("success"):
                return started
            result = account_status.unwrap_single_mode_start_common(started["result"])
            account, chara_info = account_status.apply_career_result(session, result)
            if not chara_info:
                result_code = (result.get("data_headers") or {}).get("result_code")
                if result_code != 1:
                    raise RuntimeError(
                        "Career start response missing chara_info "
                        f"(result_code={result_code!r})"
                    )
                # single_mode_team/start (post 2026-07-22 auto-train update)
                # returns single_mode_start_common + team_data_set but NOT the
                # home/turn state, so the runner would see turn 0 and exit
                # immediately. Fetch turn 1 with a load, like the resume branch.
                log.warning(
                    "[START] successful start response missing chara_info; "
                    "recovering turn state with load/index + career load"
                )
                try:
                    game_service.load_index_live(session, {})
                    result = game_service.load_career(session)
                    account, chara_info = account_status.apply_career_result(session, result)
                except Exception as recovery_err:
                    log.warning(
                        "[START] successful start response missing chara_info; "
                        "turn-state recovery failed: %s",
                        recovery_err,
                    )
                    raise RuntimeError(
                        "Career start succeeded but response omitted chara_info; "
                        "turn-state recovery failed"
                    ) from recovery_err
                if not chara_info:
                    log.warning(
                        "[START] successful start response missing chara_info; "
                        "turn-state recovery also returned no chara_info"
                    )
                    raise RuntimeError(
                        "Career start succeeded but response omitted chara_info; "
                        "turn-state recovery returned no chara_info"
                    )

        sid = preset_runtime.sync_runtime_preset_scenario(preset, result, req)
        preset_runtime.apply_runtime_bot_config(preset, sid, context.bot_config_store)
        career_selection.apply_deck_type_counts(preset, req=req, chara_info=chara_info)

        # Fresh, deliberate run: clear any prior auto-backoff state so the user gets a
        # clean chance. If the server is still throttling, the breaker re-trips fast.
        game_service.reset_circuit(session)

        # run_count: -1 = run to final SP dump, then stop before finish submit;
        # 0 = run forever, 1 = single career, N = N careers.
        account_store.apply_auto_delete_config(session)
        run_count = int(req.run_count or 0)
        stop_after_sp_dump = run_count == -1
        looping = run_count not in (-1, 1)
        if looping:
            session.loop_stop = False
            session.loop_thread = threading.Thread(target=self.manage_career_loop, args=(req, preset, result), daemon=True)
            session.loop_thread.start()
            delay.dna_sleep(0.5, 0.5)
        else:
            def _restart_current_run():
                try:
                    load_result = game_service.load_index_live(session, {})
                    load_data = load_result.get('data', {})
                    account_status.update_start_state(session, load_data)
                    session.account = account_status.get_account_status(session, load_data)
                except Exception as refresh_err:
                    log.warning(f"[RESTART] load/index refresh after force-delete failed: {refresh_err}")
                started = self.start_career_from_request(req)
                if not started.get("success"):
                    raise RuntimeError(started.get("detail") or "career restart failed")
                new_result = account_status.unwrap_single_mode_start_common(started["result"])
                account, chara_info = account_status.apply_career_result(session, new_result)
                sid = preset_runtime.sync_runtime_preset_scenario(preset, new_result, req)
                preset_runtime.apply_runtime_bot_config(preset, sid, context.bot_config_store)
                career_selection.apply_deck_type_counts(preset, req=req, chara_info=chara_info)
                return new_result

            session.runner.set_loop_info(1, 1)
            session.runner.start(
                session.client,
                preset,
                result,
                max(1, min(int(req.max_steps or 2500), 3000)),
                burn_clocks=req.burn_clocks,
                dev_mode=False,
                account=session.name,
                restart_callback=_restart_current_run,
                stop_after_sp_dump=stop_after_sp_dump,
                spark_reroll=req.spark_reroll,
                user_info_cache=session.user_info_cache,
            )

        return {"success": True, "account": account, "chara_info": chara_info, "runner": session.runner.snapshot()}

    async def run(self, req: RunCareerRequest):
        import career_bot.planning.presets as presets

        session = self.session
        if session.runner.snapshot().get("running") or session.loop_active():
            return {"success": False, "detail": "Career runner loop already active"}
        preset_store = cast("PresetStore", context.preset_store)
        race_preset_store = cast("RacePresetStore", context.race_preset_store)
        preset_name = req.preset_name or "xguri parent"
        preset = preset_store.read_one(preset_name)
        if not preset:
            # Graceful fallback: try first available skill preset, then bare default
            all_presets = preset_store.read_all()
            if all_presets:
                preset = all_presets[0]
            else:
                from career_bot.planning.presets import hydrate_preset
                preset = hydrate_preset({"name": "default"})
        # Apply race preset override when one is selected
        if req.race_preset_name:
            rp = race_preset_store.read_one(req.race_preset_name)
            if rp:
                preset = presets.apply_race_preset(preset, rp)
        preset = dict(preset)
        preset["two_pal_deck"] = bool(req.two_pal_deck)

        try:
            return self._launch_career_run(req, preset)
        except Exception as e:
            return {"success": False, "detail": str(e)}
