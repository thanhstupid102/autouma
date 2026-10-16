import logging
import threading
import json
from pathlib import Path

import core.operational_time as operational_time
from career_bot.scenarios import get_strategy_class, resolve_scenario_id
from career_bot.planning.races import RacePlanner
from career_bot.skills import SkillBuyer
from career_bot.scenarios.mant.items import MantItemManager
from career_bot.outcomes import career_failed


from career_bot.engine.report import new_report, add_api_call, add_decision, finish_report, write_report, set_error, begin_report_path
from career_bot.delay import backoff_sleep, dna_sleep as _runner_dna_sleep, use_dna
from integrations.discord import notify
from career_bot.engine.debug import RunnerDebugMixin
from career_bot.engine.recovery import RunnerRecoveryMixin
from career_bot.engine.reporting import RunnerReportMixin, TRAINING_LABELS as _REPORT_TRAINING_LABELS
from career_bot.engine.lifecycle import RunnerLifecycleMixin
from career_bot.engine.events import RunnerEventMixin
from career_bot.engine.racing import RunnerRaceMixin
from career_bot.engine.commerce import RunnerCommerceMixin
from career_bot.engine.resources import RunnerResourceMixin
from career_bot.engine.actions import RunnerActionMixin
from uma_api.errors import UnsupportedScenarioError, api_error_result_code, is_blocked_state_error
from uma_api.log_context import log_context, set_log_fields
from uma_api.trace import TraceLog, release_trace_file
from uma_api.update_guard import AuthInvalidatedError, ClientVersionError
from core.runtime_paths import append_private_text, resolve_state_root

from core.settings import Settings

log = logging.getLogger(__name__)

dna_sleep = _runner_dna_sleep
TRAINING_LABELS = _REPORT_TRAINING_LABELS

# What _dispatch_decision tells _run's loop to do next. These are the four things
# the dispatch ladder used to do inline (fall through / continue / break /
# continue-and-forget-last_turn); nothing else about the loop changed.
_LOOP_NEXT = "next"
_LOOP_CONTINUE = "continue"
_LOOP_BREAK = "break"
_LOOP_RESTART = "restart_loop"


class RunFatalError(RuntimeError):
    """A bounded recovery already exhausted itself -- the run must STOP, not retry.

    Reloading/re-running these only makes it worse (e.g. a race_out-201 stuck career
    is permanently corrupted by a reload). The central _run crash-retry re-raises
    these straight to the crash handler instead of reloading + continuing."""


def _redacted_api_response(data):
    from uma_api.client import redact_for_console
    return redact_for_console(data)


def _response_turn(data, fallback=0):
    root = (data or {}).get("data") if isinstance(data, dict) else {}
    chara = (root or {}).get("chara_info") or (root or {}).get("single_mode_chara_light") or {}
    return int(chara.get("turn") or fallback or 0)


def _format_verbose_response_log(ep, data, fallback_turn=0):
    return f"[Unity Cup T{_response_turn(data, fallback_turn)}] {ep} server_response: {json.dumps(_redacted_api_response(data), ensure_ascii=False, default=str)}"


def _response_result_code(data):
    """The game result_code carried by an api_log RES payload, or None.

    ERR payloads (transport failures) have no data_headers, so they resolve to
    None -- which is the honest answer: the call never reached a game result."""
    headers = (data or {}).get("data_headers") if isinstance(data, dict) else None
    return (headers or {}).get("result_code")


def _slim_api_data(direction, ep, data, verbose=False):
    """Compact form of an API REQ/RES for the career report's per-turn api_calls.

    The full payloads are huge (one load/index response is hundreds of KB) and nothing
    reads them back -- storing them bloated bot_logs/ career reports to tens of MB each
    (GBs total). This remains useful for targeted display/log callers; the production
    report path now relies on its 16 KiB cap while the run-scoped gzip sidecar keeps the
    full payload."""
    if verbose and direction == "RES":
        headers = (data or {}).get("data_headers") if isinstance(data, dict) else {}
        return {
            "result_code": (headers or {}).get("result_code"),
            "server_response": _redacted_api_response(data),
        }
    if not isinstance(data, dict):
        return {}
    if direction == "REQ":
        pl = data.get("payload") or {}
        out = {"current_turn": pl.get("current_turn")}
        # Keep the skill ids on a skill purchase so the log shows WHAT was bought
        # (essential for diagnosing SP spent vs skills actually gained).
        if "gain_skill" in ep:
            out["skill_ids"] = [
                int((s or {}).get("skill_id") or 0)
                for s in (pl.get("gain_skill_info_array") or [])
            ]
        # Keep the chosen option on an event check so the api log shows WHICH
        # choice was sent (event_id + 1-based wire choice_number).
        if "check_event" in ep:
            out["event_id"] = pl.get("event_id")
            out["chara_id"] = pl.get("chara_id")
            out["choice_number"] = pl.get("choice_number")
        return out
    dh = data.get("data_headers") or {}
    out = {"result_code": dh.get("result_code")}
    if data.get("http_status") is not None:
        out["http_status"] = data.get("http_status")
    if data.get("error"):
        out["error"] = str(data.get("error"))[:200]
    return out


def runtime_output_root(base_dir):
    return resolve_state_root(base_dir).root

class CareerRunner(
    RunnerDebugMixin,
    RunnerRecoveryMixin,
    RunnerReportMixin,
    RunnerLifecycleMixin,
    RunnerEventMixin,
    RunnerRaceMixin,
    RunnerCommerceMixin,
    RunnerResourceMixin,
    RunnerActionMixin,
):
    _ITEM_USE_RECOVERY_CAP = 2
    # Full request/response captures show count=1 consistently deducts 10 jewels.
    _CARAT_TP_RECOVERY_COST = 10

    def __init__(self, base_dir, state_root=None):
        self.base_dir = Path(base_dir)
        self.state_root = (
            Path(state_root).resolve()
            if state_root is not None
            else resolve_state_root(self.base_dir).root
        )
        self.report = None
        self.lock = threading.Lock()
        self.thread = None
        self.strategy = None
        self.stop_requested = False
        self.pause_requested = False
        self.pause_exit_requested = False
        self.burn_clocks = False
        self.spark_reroll_enabled = False
        self.stop_after_sp_dump = False
        self.auto_delete_trained = {"enabled": False}
        self._account = ""
        self._loop_index = 1
        self._loop_target = 1
        self._resume_attempt = 0
        self._resume_attempt_limit = 0
        self._report_path = None
        self._last_flush_ts = 0.0
        self._last_flushed_report_revision = None
        self._career_trace_log = None
        self._career_trace_path = None
        self._career_trace_client = None
        self._previous_trace_log = None
        self._previous_trace_file = None
        self._pending_trace_resume = None
        self._trace_upload_attempted = False
        self.race_planner = RacePlanner(base_dir, self.state_root)
        self.skill_buyer = SkillBuyer(base_dir, self.state_root)
        self.item_manager = MantItemManager()
        self.user_info_cache = {}
        self._live_monitor = None
        # A 201 on race_out leaves the career stuck on the race screen
        # (playing_state 3). Reloading returns that same state, next_decision picks
        # race_progress again, race_out 201s again -- an infinite loop that only the
        # client circuit breaker stops (6 errors/90s), which then misreports the
        # cause as "server throttling". Bound recovery attempts per-turn so we stop
        # cleanly with an honest message long before the breaker trips.
        self._race_recover_turn = None
        self._race_recover_count = 0
        self._race_reset_turn = None
        # New-day / forced-relogin recovery: when race_entry itself 201s the whole
        # session is dead (not a stuck race), so relogin + resume. Bounded per turn.
        self._race_relogin_turn = None
        self._race_relogin_count = 0
        self._item_use_recover_turn = None
        self._item_use_recover_count = 0
        self._item_use_blocked_turn = None
        self._last_race_action_turn = None
        self._consecutive_race_count = 0
        self.status = {
            "running": False,
            "paused": False,
            "preset": "",
            "scenario_id": 0,
            "turn": 0,
            "steps": 0,
            "last_action": "",
            "last_error": "",
            "error_type": "",
            "error_result_code": None,
            "finished": False,
            "circuit_tripped": False,
            "skills_bought": 0,
            "items_bought": 0,
            "items_used": 0,
            "clocks_used": 0,
            "clocks_bought": 0,
            "spark_reroll_enabled": False,
            "log": [],
            "action_history": [],
        }

    def start(self, client, preset, initial_result, max_steps=2500, burn_clocks=False, dev_mode=False, account=None, restart_callback=None, stop_after_sp_dump=False, spark_reroll=False, user_info_cache=None):
        self._account = account if account is not None else Settings.SWEEP_ACCOUNT or ""
        self._trace_upload_attempted = False
        with self.lock:
            if self.status["running"]:
                raise RuntimeError("Career runner already active")
            scenario_id = resolve_scenario_id(preset)
            strategy_cls = get_strategy_class(scenario_id)
            if not strategy_cls:
                raise RuntimeError(f"No runner for scenario {scenario_id}")
            self.stop_requested = False
            self.pause_requested = False
            self.pause_exit_requested = False
            self.burn_clocks = burn_clocks
            self.spark_reroll_enabled = bool(spark_reroll)
            self.stop_after_sp_dump = bool(stop_after_sp_dump)
            self.user_info_cache = user_info_cache if isinstance(user_info_cache, dict) else {}
            self.dev_mode = dev_mode
            resume_same_career = self._resume_attempt > 0
            clocks_bought = (
                max(int(self.status.get("clocks_bought") or 0), 0)
                if resume_same_career else 0
            )
            rejected_races = (
                set(getattr(self.race_planner, "rejected", set()) or set())
                if resume_same_career else set()
            )
            if not resume_same_career:
                self._race_entry_208_counts = {}
            self.race_planner = RacePlanner(self.base_dir, self.state_root)
            self.race_planner.rejected.update(rejected_races)
            self.skill_buyer = SkillBuyer(self.base_dir, self.state_root)
            strategy = strategy_cls(self.race_planner)
            self.strategy = strategy
            # Item/shop handler comes from the scenario strategy (factory), not a
            # hardcoded class -- MANT + Unity both yield MantItemManager today.
            self.item_manager = strategy.create_item_manager()
            self._item_use_recover_turn = None
            self._item_use_recover_count = 0
            self._item_use_blocked_turn = None
            self._last_race_action_turn = None
            self._consecutive_race_count = 0
            self._restart_callback = restart_callback
            self._run_restart_count = 0
            self.status = {
                "running": True,
                "paused": False,
                "preset": preset.get("name", ""),
                "scenario_id": scenario_id,
                "turn": 0,
                "steps": 0,
                "last_action": "started",
                "last_error": "",
                "error_type": "",
                "error_result_code": None,
                "finished": False,
                "circuit_tripped": False,
                "skills_bought": 0,
                "items_bought": 0,
                "items_used": 0,
                "clocks_used": 0,
                "clocks_bought": clocks_bought,
                "spark_reroll_enabled": self.spark_reroll_enabled,
                "total_turns": 78,
                "log": [],
                "action_history": [],
                "consecutive_race_count": 0,
                "retry_attempt": self._resume_attempt,
                "retry_limit": self._resume_attempt_limit,
                "retry_waiting": False,
                "retry_wait_seconds": 0,
            }
            self.report = new_report(preset, scenario_id)
            if client:
                client.report = self.report
                def _on_api_log(direction, ep, data, req_id=None):
                    body_bytes = None
                    if self.report:
                        import time
                        event = {
                            "ts": time.time(),
                            "direction": direction,
                            "endpoint": ep,
                            "data": data,
                            "req_id": req_id,
                            "turn": self.status.get("turn", 0)
                        }
                        result_code = _response_result_code(data)
                        if result_code is not None:
                            event["result_code"] = result_code
                        body_bytes = add_api_call(self.report, event)
                    # L2 structured fields: this callback is the ONE funnel every
                    # game call passes through, on the calling (runner) thread, so
                    # it gives `endpoint`/`result_code` to every later log record
                    # with zero per-call-site boilerplate. REQ arms the endpoint and
                    # clears the previous code; RES/ERR record what came back --
                    # client.call() emits RES *before* it raises on rc != 1, so the
                    # engine's `except` handlers log with the real code in context.
                    # Deliberately AFTER the report block so the report row is
                    # written first (client.api_log swallows anything we raise).
                    if direction == "REQ":
                        set_log_fields(endpoint=ep, result_code=None)
                    else:
                        set_log_fields(endpoint=ep, result_code=_response_result_code(data))
                    return body_bytes
                client.on_api_log = _on_api_log
            self._log_locked("started", 0, f"preset {preset.get('name', '')} (burn_clocks={burn_clocks}, spark_reroll={self.spark_reroll_enabled}, stop_after_sp_dump={self.stop_after_sp_dump})")
            self.thread = threading.Thread(target=self._run, args=(client, preset, initial_result, strategy, max_steps), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_requested = True

    def pause(self):
        # Pause = save-and-exit: flag the run to break at its next safe boundary and exit
        # the career (resumable). The career stays active server-side; RESUME re-runs it.
        with self.lock:
            if self.status.get("running"):
                self.pause_requested = True
                self.pause_exit_requested = True
                self.status["paused"] = True
                self._log_locked("pause", self.status.get("turn", 0), "save & exit career requested")

    def resume(self):
        with self.lock:
            self.pause_requested = False
            self.pause_exit_requested = False
            self.status["paused"] = False
            self._log_locked("resume", self.status.get("turn", 0), "career resumed")

    def _pause_exit_requested(self):
        with self.lock:
            return self.pause_exit_requested


    def set_loop_info(self, index, target):
        # Which career this is within a loop (index) and the loop size (target,
        # 0 = infinite). Used only for the Discord notification.
        self._loop_index = int(index or 1)
        self._loop_target = int(target or 0)

    def set_resume_attempt(self, attempt, limit):
        """Attach loop-owned resume metadata to the next runner notification."""
        self._resume_attempt = max(0, int(attempt or 0))
        self._resume_attempt_limit = max(0, int(limit or 0))

    def set_retry_wait(self, attempt, limit, wait_seconds):
        """Expose an interruptible pending retry through the normal runner status."""
        detail = (
            f"waiting {int(wait_seconds)}s before resume attempt "
            f"{int(attempt)}/{int(limit)}"
        )
        with self.lock:
            self.status.update({
                "status": "waiting-retry",
                "last_action": detail,
                "retry_attempt": int(attempt),
                "retry_limit": int(limit),
                "retry_waiting": True,
                "retry_wait_seconds": int(wait_seconds),
            })
            self._log_locked(
                "retry_wait",
                self.status.get("turn", 0),
                detail,
            )

    def set_retry_stage(self, action, detail):
        """Move a pending retry to its next visible orchestration stage."""
        with self.lock:
            self.status.update({
                "status": str(action),
                "last_action": str(detail),
                "retry_waiting": False,
                "retry_wait_seconds": 0,
            })
            self._log_locked(action, self.status.get("turn", 0), detail)

    def snapshot(self):
        with self.lock:
            data = dict(self.status)
            data["burn_clocks"] = self.burn_clocks
            data["spark_reroll_enabled"] = self.spark_reroll_enabled
            data["account"] = (getattr(self, "_account", "") or Settings.SWEEP_ACCOUNT or "")
            data["loop_index"] = int(getattr(self, "_loop_index", 1) or 1)
            data["loop_target"] = int(getattr(self, "_loop_target", 1) or 0)
            data["card_id"] = getattr(self, "_notify_card_id", "") or ""
            return data

    def set_burn_clocks(self, value):
        with self.lock:
            self.burn_clocks = value
            self._log_locked("update_setting", 0, f"burn_clocks set to {value}")

    def _run(self, client, preset, result, strategy, max_steps):
        """Runner-thread entry point: bind this career's log context, then run.

        The bind lives HERE, not in start(), and that placement is load-bearing.
        contextvars are per-thread and a freshly started threading.Thread begins
        with an EMPTY context -- it does not inherit the creating thread's values.
        Binding in start() would therefore (a) never reach this thread and (b)
        leave the caller's thread (a web request worker, or the CLI thread that
        drives every account in turn) permanently tagged with one account.

        Scoping it with `with` rather than a bare set means the fields are also
        released when the career ends, so this stays correct if a runner is ever
        driven from a pooled thread -- a pool worker keeps its context between
        tasks, and would otherwise hand one account's fields to the next.
        `turn` / `endpoint` / `result_code` are then updated in place inside this
        scope and are undone with it.
        """
        with log_context(account=self._account, scenario_id=self.status.get("scenario_id")):
            self._run_career(client, preset, result, strategy, max_steps)

    def _run_career(self, client, preset, result, strategy, max_steps):
        state = self._prime_run(client, result)
        last_turn = -1
        try:
            self._start_live_monitor()
            for i in range(max_steps):
                if self._run_break_requested(client):
                    break
                data = state.get("data") or {}
                chara = data.get("chara_info") or {}
                turn = int(chara.get("turn") or 0)
                # Ambient `turn` for L2, set at the TOP of the iteration rather
                # than left to the _mark() mirror below: _begin_turn already logs
                # the inventory snapshot for THIS turn, and _mark(turn=...) does
                # not run until after it. (_mark still mirrors later moves, e.g.
                # when a Reset Whistle rerun lands the loop on a new turn.)
                set_log_fields(turn=turn)

                if turn != last_turn:
                    self._begin_turn(client, state, turn)
                    last_turn = turn

                self._mark(turn=turn)
                self._track_turn_scores(state)

                if turn == 77 and not getattr(self, "dev_mode", False) and not preset.get("play_full_career", True):
                    log.info("Turn 77 reached terminating")
                    self.stop()
                    break

                self._reset_turn_attempt_trackers()

                try:
                    state, chara, decision = self._decide_turn(client, strategy, state, preset, data, chara, turn)
                    if decision is None:
                        break

                    if decision.action == "command":
                        state, chara, decision = self._rerun_after_items(client, strategy, state, preset, decision)

                    self._log(decision.action, chara.get("turn", 0), decision.reason)
                    state, control = self._dispatch_decision(client, strategy, state, preset, decision, chara)
                    if control == _LOOP_RESTART:
                        last_turn = -1
                        continue
                    if control == _LOOP_CONTINUE:
                        continue
                    if control == _LOOP_BREAK:
                        break

                    if decision.action not in {"finish"}:
                        state = self._buy_skills(client, state, preset, False)

                    self._advance(decision.action)
                    self._flush_report()
                except Exception as exc:
                    state = self._handle_turn_error(client, strategy, state, exc)
                    continue
        except Exception as exc:
            self._handle_run_crash(exc)
        finally:
            self._finalize_run()

    # --- _run phases -------------------------------------------------------
    # _run_career is a single state machine; the helpers below are its phases, split out
    # verbatim so the loop reads as setup -> per-turn work -> retry ladder ->
    # teardown. They stay methods on CareerRunner (not a new mixin) so the MRO is
    # byte-identical, and they stay in THIS module so the module-level
    # `backoff_sleep` / `dna_sleep` names tests rebind keep resolving at call time.

    def _prime_run(self, client, result):
        """Setup phase: bind the pacing DNA, reset per-career notify/report state.

        Returns the initial career state the loop starts from."""
        dna = getattr(client, "_dna", None)
        if dna is not None:
            use_dna(dna)

        state = result or {}
        self._run_crash_retries = 0
        self._notify_card_id = str(((state.get("data") or {}).get("chara_info") or {}).get("card_id") or "")
        self._notify_factor_ids = []
        self._notify_rank = 0
        self._notify_rank_score = 0
        self._notify_spark_reroll_options = []
        self._notify_spark_reroll_choice = 0
        # Realtime report path: fixed for this career so every per-turn flush rewrites the
        # SAME file (crash-safe), instead of only writing once at career end.
        self._report_path = None
        self._last_flush_ts = 0.0
        self._last_flushed_report_revision = None
        self._begin_career_trace(client)
        try:
            self._report_path = begin_report_path(self.state_root / "bot_logs", self._account)
        except Exception:
            self._report_path = None
        return state

    def _begin_career_trace(self, client):
        """Install one compressor for this run, replacing any debug trace writer."""
        self._career_trace_log = None
        self._career_trace_path = None
        self._career_trace_client = None
        self._previous_trace_log = None
        self._previous_trace_file = None
        self._pending_trace_resume = None
        if not Settings.UMA_CAREER_API_TRACE or client is None:
            return None
        trace_log = None
        previous = None
        previous_trace_file = None
        attached = False
        try:
            trace_log = TraceLog(self.state_root / "trace_logs")
            path = trace_log.initialize()
            if path is None:
                return None
            previous = getattr(client, "_trace_log", None)
            previous_trace_file = getattr(client, "trace_file", None)
            client._trace_log = trace_log
            attached = True
            client.trace_file = path
            self._career_trace_log = trace_log
            self._career_trace_path = path
            self._career_trace_client = client
            self._previous_trace_log = previous
            self._previous_trace_file = previous_trace_file
            return path
        except Exception as exc:
            if attached:
                try:
                    client._trace_log = previous
                    client.trace_file = previous_trace_file
                except Exception:
                    pass
            if trace_log is not None:
                try:
                    trace_log.close()
                except Exception:
                    pass
            log.warning("failed to start career API trace: %s", exc)
            return None

    @staticmethod
    def _restore_trace_writer(client, trace_log, trace_file):
        if client is None:
            return
        try:
            client._trace_log = trace_log
            client.trace_file = trace_file
        except Exception as exc:
            log.warning("failed to restore previous API trace: %s", exc)

    def _close_career_trace(self, resume=True, reserve=False):
        trace_log = self._career_trace_log
        client = self._career_trace_client
        previous_trace_log = self._previous_trace_log
        previous_trace_file = self._previous_trace_file
        self._career_trace_log = None
        self._career_trace_client = None
        self._previous_trace_log = None
        self._previous_trace_file = None
        if trace_log is not None:
            try:
                path = trace_log.close(reserve=reserve)
                if path is not None:
                    self._career_trace_path = path
            except Exception as exc:
                log.warning("failed to close career API trace: %s", exc)
            try:
                if client is not None and getattr(client, "_trace_log", None) is trace_log:
                    client._trace_log = None
            except Exception as exc:
                log.warning("failed to detach career API trace: %s", exc)
        if client is not None and not resume:
            self._pending_trace_resume = (
                client,
                previous_trace_log,
                previous_trace_file,
            )
        elif client is not None:
            self._restore_trace_writer(
                client,
                previous_trace_log,
                previous_trace_file,
            )
        return self._career_trace_path

    def _resume_debug_trace(self, client=None):
        pending = self._pending_trace_resume
        self._pending_trace_resume = None
        if pending is not None:
            pending_client, trace_log, trace_file = pending
            self._restore_trace_writer(
                client or pending_client,
                trace_log,
                trace_file,
            )

    def _start_live_monitor(self):
        try:
            self._live_monitor = notify.start_live_monitor(
                self.base_dir,
                self.state_root,
                self.snapshot,
            )
        except Exception as exc:
            log.warning(f"live monitor start failed: {type(exc).__name__}")
            self._live_monitor = None

    def _run_break_requested(self, client):
        """Top-of-loop safe boundary: should the career loop stop right now?

        True on an explicit stop, on the client's tripped circuit breaker, and on a
        pause (save & exit). Each case owns its own logging/marking, exactly as when
        these three guards sat inline at the top of _run."""
        if self._should_stop():
            return True
        # Auto-backoff: the API client tripped its circuit breaker (too many
        # server errors in a short window -- the server is likely throttling).
        # Stop this career cleanly instead of continuing to hammer the server.
        if getattr(client, "circuit_tripped", False):
            msg = ("Auto-backoff: too many server errors in a short time "
                   "(server likely throttling). Stopped to avoid hammering -- "
                   "wait a while before running again.")
            log.warning(f"AUTO-BACKOFF: stopping career -- {msg}")
            self._log("auto_backoff", self.snapshot().get("turn", 0), msg)
            self._mark(last_error=msg, last_action="auto-backoff", circuit_tripped=True)
            self.stop_requested = True
            return True
        # Pause = SAVE-AND-EXIT the career (user request): Uma auto-saves the
        # career server-side after every action, so "exit" just stops the bot
        # cleanly at this safe boundary (top of loop, nothing mid-flight) and
        # leaves the career active/resumable. We do NOT call finish_career (that
        # would grade/end it). RESUME (main.py) re-runs the career from the
        # server's saved state.
        if self._pause_exit_requested():
            self._log("pause_exit", self.snapshot().get("turn", 0), "save & exit career (resumable)")
            return True
        return False

    def _begin_turn(self, client, state, turn):
        """First iteration on a NEW turn: pace the request, snapshot, flush."""
        if hasattr(client, "wait_turn_delay"):
            client.wait_turn_delay()
        self._log_inventory_snapshot(state, turn)
        # Advanced to a new turn => real progress => reset the crash-retry
        # counter, so the 3-try limit means 3 reloads WITHOUT progress.
        self._run_crash_retries = 0
        self._flush_report(force=True)

    def _reset_turn_attempt_trackers(self):
        """Clear the per-iteration skill/item attempt scratchpads the report reads."""
        self.skill_buyer.last_attempt = []
        self.skill_buyer.last_result = {}
        self.item_manager.last_buy_attempt = []
        self.item_manager.last_buy_result = {}
        self.item_manager.last_use_attempt = []
        self.item_manager.last_use_result = {}
        self.skill_buyer.attempt_events = []
        self.item_manager.buy_attempt_events = []
        self.item_manager.use_attempt_events = []

    def _decide_turn(self, client, strategy, state, preset, data, chara, turn):
        """Bring the turn to a decidable state, then ask the strategy what to do.

        Drains pending events, unsticks a blocked playing_state, emits the debug
        dump, and records the decision on the report. Returns
        (state, chara, decision); `decision is None` means the career is still
        blocked after recovery and the run loop must stop."""
        if data.get("unchecked_event_array"):

            state = self._drain_events(client, strategy, state)
            data = state.get("data") or {}
            chara = data.get("chara_info") or {}
            self._track_turn_scores(state)

        if self._blocked_playing_state(chara):

            state = self._recover_blocked_state(client, strategy, state)
            data = state.get("data") or {}
            chara = data.get("chara_info") or {}
            if self._blocked_playing_state(chara):

                self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                return state, chara, None

        self._debug_turn(state, preset)
        debug_schedule = getattr(strategy, "debug_scheduled_recreation", None)
        if debug_schedule:
            schedule_info = debug_schedule((data.get("home_info") or {}).get("command_info_array") or [], turn, chara, preset)
            if schedule_info:
                self._debug("scheduled_recreation_debug", state, schedule_info)
        decision = strategy.next_decision(state, preset)

        if self.report:
            add_decision(self.report, state, decision)
        return state, chara, decision

    def _rerun_after_items(self, client, strategy, state, preset, decision):
        """Buy/use items for a command turn, re-deciding after a Reset Whistle.

        A whistle rerolls the training board, so the decision taken before it is
        stale -- loop (bounded) until the board settles or the strategy stops
        asking for a command. Returns (state, chara, decision); `chara` is the one
        the last pass observed, which is what the caller logs and dispatches on."""
        skip_item_buy = False
        for _ in range(6):
            command = self._command_from_decision(state, decision)
            skip_item_use = int((decision.payload or {}).get("command_type") or 0) == 3
            state = self._handle_items(client, state, preset, command, skip_buy=skip_item_buy, skip_use=skip_item_use)
            used_whistle = any(row.get("name") == "Reset Whistle" for row in self.item_manager.last_use_selected)
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):

                state = self._drain_events(client, strategy, state)
            data = state.get("data") or {}
            chara = data.get("chara_info") or {}
            self._mark(turn=chara.get("turn", 0))
            decision = strategy.next_decision(state, preset)

            if self.report:
                add_decision(self.report, state, decision)
            if not used_whistle or decision.action != "command":
                break
            skip_item_buy = True
        return state, chara, decision

    def _dispatch_decision(self, client, strategy, state, preset, decision, chara):
        """Execute one strategy decision. Returns (state, loop-control).

        The control value is exactly what the inline ladder used to do to the run
        loop: _LOOP_BREAK, _LOOP_CONTINUE, _LOOP_RESTART (continue AND forget
        last_turn, because the career restarted at an arbitrary turn) or
        _LOOP_NEXT (fall through to the post-action skill buy + bookkeeping)."""
        if decision.action == "idle":
            self._mark(last_action=decision.reason)
            return state, _LOOP_BREAK
        if decision.action == "done":
            self._mark(last_action=decision.reason, finished=True)
            return state, _LOOP_BREAK
        if decision.action == "restart":
            state = self._restart_career(client, strategy, preset, decision.payload.get("current_turn", chara.get("turn", 0)), decision.reason)
            return state, _LOOP_RESTART

        if decision.action == "event":
            try:
                state = self._event(client, strategy, decision.payload)
            except Exception as exc:
                if "Network error" in str(exc) or api_error_result_code(exc) in (201, 205, 208):
                    state = self._fresh_career_state(client, strategy)
                    return state, _LOOP_CONTINUE
                raise
        elif decision.action == "command":
            return self._exec_command_action(client, strategy, state, decision, chara)
        elif decision.action == "race":

            self._record_action(decision, chara)
            state = self._race(client, state, preset, decision.payload)
        elif decision.action == "race_progress":

            self._record_action(decision, chara)
            state = self._race_progress(client, decision.payload, preset)
        elif decision.action == "finish":

            self._record_action(decision, chara)
            state = self._finish_career_flow(client, strategy, state, preset, decision.payload["current_turn"])
            return state, _LOOP_BREAK
        else:
            extra_handler = (strategy.extra_action_handlers() or {}).get(decision.action)
            if extra_handler:
                self._record_action(decision, chara)
                state = extra_handler(self, client, state, preset, decision.payload)
            else:
                self._mark(last_action=decision.action)
                return state, _LOOP_BREAK
        return state, _LOOP_NEXT

    def _exec_command_action(self, client, strategy, state, decision, chara):
        """Send the chosen training/rest command, then drain what it triggered.

        A transient (network / 201 / 205 / 208) reloads the career and retries the
        turn; a 102/1503 means the career is parked in a blocked playing_state and
        gets the same unstick pass the top of the turn does."""
        self._log("command_exec", decision.payload["current_turn"], f"{decision.payload.get('command_type')}:{decision.payload.get('command_id')}:{decision.payload.get('command_group_id')}")
        self._record_action(decision, chara)
        try:
            executed_command = self._command_from_decision(state, decision)
            state = client.exec_command(**self._exec_command_payload(decision.payload))
            if hasattr(strategy, "_mark_early_group_card_command"):
                strategy._mark_early_group_card_command(executed_command, chara)
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):
                state = self._drain_events(client, strategy, state)
        except Exception as exc:
            if "Network error" in str(exc) or api_error_result_code(exc) in (201, 205, 208):
                state = self._fresh_career_state(client, strategy)
                return state, _LOOP_CONTINUE
            if not is_blocked_state_error(exc):
                raise
            state = self._recover_blocked_state(client, strategy, state)
            data = state.get("data") or {}
            chara = data.get("chara_info") or {}
            if self._blocked_playing_state(chara):
                self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                return state, _LOOP_BREAK
            return state, _LOOP_CONTINUE
        return state, _LOOP_NEXT

    def _handle_turn_error(self, client, strategy, state, exc):
        """Retry ladder for one failed turn. Returns the state the loop continues on.

        Called from _run's per-turn `except Exception as exc:` handler, so `exc` is
        still the ACTIVE exception here: the bare `raise`s below re-raise it
        unchanged (original traceback) straight to the crash handler, exactly as
        when this ladder was inline."""
        # Always persist the latest report before recovering/crashing so a
        # mid-career failure leaves a debuggable log on disk.
        self._flush_report(force=True)
        if isinstance(exc, (
            UnsupportedScenarioError,
            AuthInvalidatedError,
            ClientVersionError,
        )):
            raise
        if self._is_state_recovery_error(exc):
            return self._recover_state_error(client, strategy, self.snapshot().get("turn", 0), "turn_recovered", exc)
        if is_blocked_state_error(exc):
            return self._recover_blocked_state(client, strategy, state)
        # Terminal failures (a bounded recovery already gave up) must NOT
        # be reloaded -- reloading corrupts the career. Stop cleanly.
        if isinstance(exc, RunFatalError):
            raise
        # Unexpected error: don't crash the run. Retry IN PLACE first --
        # reload the career without a full relogin (cheap) -- for the first
        # _RUN_INPLACE_RETRIES attempts. Only if those keep failing do we KILL
        # the session (relogin) + reload the career. Crash only after
        # _RUN_CRASH_RETRIES total failed attempts (counter resets on real
        # progress). A stop request mid-error ends the run now.
        if self._should_stop():
            raise
        self._run_crash_retries += 1
        if self._run_crash_retries > self._RUN_CRASH_RETRIES:
            raise
        cur_turn = self.snapshot().get("turn", 0)
        relogin = self._run_crash_retries > self._RUN_INPLACE_RETRIES
        mode = "kill session + reload" if relogin else "reload in place"
        log.warning(f"RUN RETRY {self._run_crash_retries}/{self._RUN_CRASH_RETRIES} ({mode}) after error: {exc}")
        self._log("run_retry", cur_turn,
                  f"{mode} + continue ({self._run_crash_retries}/{self._RUN_CRASH_RETRIES}): {exc}")
        try:
            state = self._fresh_career_state(client, strategy, relogin_first=relogin)
        except (RunFatalError, AuthInvalidatedError, ClientVersionError):
            raise
        except Exception as reload_exc:
            log.warning(f"RUN RETRY reload failed: {reload_exc}")
            backoff_sleep(self._run_crash_retries, base=2.0, cap=15.0)
        return state

    def _handle_run_crash(self, exc):
        """Crash phase: the run died. Persist a debuggable trace + mark the error."""
        import traceback
        trace_str = traceback.format_exc()
        traceback.print_exc()
        log.error(f"RUNNER CRASH: {exc}")

        crash_log_path = self.state_root / "crash_trace.txt"
        try:
            append_private_text(
                crash_log_path,
                f"--- CRASH AT {operational_time.utc_log_stamp()} ---\n"
                f"{trace_str}\n\n",
            )
        # mkdir/open/write -> OSError, or UnicodeEncodeError(ValueError) when the
        # traceback text carries an unencodable code point.
        except (OSError, ValueError):
            pass

        self._log("error", self.snapshot().get("turn", 0), str(exc))
        self._mark(
            last_error=str(exc),
            error_type=type(exc).__name__,
            error_result_code=api_error_result_code(exc),
        )
        if self.report:
            set_error(self.report, exc)
            self._flush_report(force=True)

    def _finalize_run(self):
        """Teardown phase: grade the run's outcome, stop the monitor, write + notify."""
        should_stop = self._should_stop()
        circuit_tripped = bool(self.status.get("circuit_tripped"))
        paused_exit = self._pause_exit_requested() and not should_stop
        if should_stop:
            final_status = "stopped"
        elif paused_exit:
            final_status = "paused"
        elif self.status.get("finished"):
            final_status = "finished"
        else:
            final_status = "error"
        try:
            if should_stop:
                if not circuit_tripped:
                    self._log("stop", self.snapshot().get("turn", 0), "stop requested")
            elif paused_exit:
                self._log("pause_exit", self.snapshot().get("turn", 0), "career suspended (save & exit)")
            if self.report:
                finish_report(self.report, final_status)
        finally:
            try:
                if paused_exit:
                    self._mark(status=final_status, paused=True)
                else:
                    self._mark(status=final_status)
            finally:
                try:
                    self._emit_run_outputs()
                finally:
                    # Completion is the handoff signal for loop orchestration. Keep it
                    # true until every run-owned output and writer has been torn down.
                    self._mark(running=False)

    def _emit_run_outputs(self):
        """Teardown tail: stop the live monitor, write the report, notify Discord."""
        trace_path = None
        try:
            try:
                notify.stop_live_monitor(self._live_monitor, self.snapshot())
            except Exception as e:
                log.warning(f"live monitor stop failed: {type(e).__name__}")
            finally:
                self._live_monitor = None
            trace_path = self._close_career_trace(resume=False, reserve=True)
            if self.report:
                try:
                    root_trace_dir = self.state_root / "bot_logs"
                    out = write_report(self.report, root_trace_dir, account=getattr(self, "_account", ""),
                                       path=getattr(self, "_report_path", None))
                    log.info(f"career report written: {out}")
                except Exception as e:
                    log.warning(f"failed to write report: {e}")
                try:
                    summary = self._build_notify_summary()
                    if career_failed(summary) and not self._trace_upload_attempted:
                        self._trace_upload_attempted = True
                        notify.send_career_summary(
                            self.base_dir,
                            self.state_root,
                            summary,
                            attachment_path=trace_path,
                        )
                    else:
                        notify.send_career_summary(
                            self.base_dir,
                            self.state_root,
                            summary,
                        )
                except Exception as e:
                    log.warning(f"discord notify failed: {e}")
        finally:
            if self._career_trace_log is not None:
                trace_path = self._close_career_trace(
                    resume=False,
                    reserve=True,
                )
            try:
                release_trace_file(trace_path)
            finally:
                self._resume_debug_trace()

    def _should_stop(self):
        with self.lock:
            return self.stop_requested



    # race_out 201 is usually a transient desync while the rest of the session is
    # healthy (training/events still succeed). FIRST retry race_out IN PLACE -- same
    # session, fresh sid (the server advances sid even on the 201) -- rather than
    # relogging + reloading. A reload mid-race-exit was observed to drop the career
    # into a stuck playing_state 3 (race_end then returns 102 "already done" and
    # race_out 201s forever). Staying in place clears a pure transient.
    _RACE_OUT_INPLACE_RETRIES = 2

    # When the race re-entry itself 201s the session is dead (daily reset / forced
    # relogin), not a stuck race -- relogin + resume the career this many times per
    # turn before giving up.
    _RACE_RELOGIN_RETRIES = 2

    # On an UNEXPECTED mid-run error (one not already handled as a transient
    # state-recovery), retry instead of crashing the run. The first
    # _RUN_INPLACE_RETRIES attempts reload the career IN PLACE (no forced relogin --
    # cheap, fixes transient blips); only after those keep failing do we KILL the
    # session (relogin) + reload the career. Crash only after _RUN_CRASH_RETRIES total
    # failed attempts (the counter resets on real progress).
    _RUN_INPLACE_RETRIES = 3
    _RUN_CRASH_RETRIES = 5
