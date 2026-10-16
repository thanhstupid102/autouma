"""Career start/finish lifecycle phases for CareerRunner, extracted verbatim from runner.py.

These are the three whole-career transitions the `_run` loop merely *calls* -- the
forced restart (`restart` decision), the Spark-Reroll factor choice submitted with the
finish, and the finish flow itself (clear an active race -> drain events -> exhaust
leftover SP -> record final stats -> submit finish -> capture sparks / auto-delete).
Moving them out leaves runner.py holding the per-turn state machine and the
start/stop/pause control surface.

`RunFatalError` is imported inside each method (never at module scope): runner.py
imports this module at line-scope *above* the `RunFatalError` definition, so a
top-level import would resolve against a partially initialized module. Same reason,
same shape as `career_bot/engine/recovery.py`.
"""

import json
import logging
from typing import TYPE_CHECKING

from career_bot.engine.report import add_event
from career_bot.planning.spark.reroll import (
    choose_spark_list,
    extract_reroll_option_map,
    extract_reroll_options,
    score_factor_ids,
)
from uma_api.errors import api_error_result_code

log = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerLifecycleMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerLifecycleMixin(_HostState):
    def _restart_career(self, client, strategy, preset, current_turn, reason):
        from career_bot.engine.runner import RunFatalError

        cap = int((preset or {}).get("sirius_throne_restart_cap") or 3)
        if int(getattr(self, "_run_restart_count", 0) or 0) >= cap:
            raise RunFatalError(f"restart cap reached ({cap}) after: {reason}")
        callback = getattr(self, "_restart_callback", None)
        if not callback:
            raise RunFatalError(f"restart requested but no restart callback is configured: {reason}")
        self._run_restart_count = int(getattr(self, "_run_restart_count", 0) or 0) + 1
        self._log("force_restart", current_turn, reason)
        client.finish_career(current_turn=current_turn or 1, is_force_delete=True)
        state = callback()
        if hasattr(strategy, "reset_run_state"):
            strategy.reset_run_state()
        if self.report:
            add_event(self.report, {"event": "force_restart", "turn": int(current_turn or 0), "reason": str(reason or "")})
        return state

    def _choose_finish_factor_lottery_id(self, client, current_turn):
        from career_bot.engine.runner import RunFatalError

        if not self.spark_reroll_enabled:
            return 0
        try:
            select_res = client.factor_select(current_turn, skill_id_array=None)
        except Exception as exc:
            if api_error_result_code(exc) != 102 or not hasattr(client, "load_career"):
                raise RunFatalError(f"Spark Reroll factor_select failed: {exc}") from exc
            self._log("spark_reroll_select", current_turn, "already on factor screen (102); loading resume state")
            select_res = client.load_career()

        options = extract_reroll_options(select_res)
        if options:
            choice = choose_spark_list(options, self.base_dir, self.state_root)
            self._notify_spark_reroll_options = [list(ids or []) for ids in options[:2]]
            self._notify_spark_reroll_choice = choice
            scores = [
                score_factor_ids(ids, self.base_dir, self.state_root)
                for ids in options
            ]
            self._log("spark_reroll_choice", current_turn, f"resume score1={scores[0]} score2={scores[1]} -> finish {choice}")
            return choice

        try:
            info = client.read_info()
            data = (info or {}).get("data", {})
            fresh_tp_info = data.get("tp_info") if isinstance(data, dict) else None
            if not isinstance(fresh_tp_info, dict) or not fresh_tp_info:
                raise ValueError("load/index returned no tp_info")
            if hasattr(client, "refresh_cached_account_state"):
                client.refresh_cached_account_state(data)
            else:
                client.tp_info = fresh_tp_info
        except Exception as refresh_err:
            original = extract_reroll_option_map(select_res).get(1) or []
            self._notify_spark_reroll_options = [list(original), []]
            self._notify_spark_reroll_choice = 1
            self._log(
                "spark_reroll_tp",
                current_turn,
                f"live TP refresh failed ({refresh_err}); finishing original list",
            )
            return 1

        if not self._ensure_spark_reroll_tp(client, 30):
            original = extract_reroll_option_map(select_res).get(1) or []
            self._notify_spark_reroll_options = [list(original), []]
            self._notify_spark_reroll_choice = 1
            self._log("spark_reroll_choice", current_turn, "TP recovery unavailable; finishing original list")
            return 1
        tp_info = dict(getattr(client, "tp_info", {}) or {})
        self._log(
            "spark_reroll_tp",
            current_turn,
            f"factor_lottery request tp_info={json.dumps(tp_info, sort_keys=True)} use_tp=30",
        )
        try:
            lottery_res = client.factor_lottery(lottery_count=1, use_tp=30, tp_info=tp_info)
        except Exception as exc:
            raise RunFatalError(f"Spark Reroll factor_lottery failed after factor_select: {exc}") from exc

        load_res = None
        options = extract_reroll_options(select_res, lottery_res)
        if not options and hasattr(client, "load_career"):
            try:
                load_res = client.load_career()
                options = extract_reroll_options(select_res, lottery_res, load_res)
            except Exception as exc:
                self._log("spark_reroll_load", current_turn, f"resume inspect skipped: {exc}")

        option_map = extract_reroll_option_map(select_res, lottery_res, load_res)
        if options:
            choice = choose_spark_list(options, self.base_dir, self.state_root)
            self._notify_spark_reroll_options = [list(ids or []) for ids in options[:2]]
            self._notify_spark_reroll_choice = choice
            scores = [
                score_factor_ids(ids, self.base_dir, self.state_root)
                for ids in options
            ]
            self._log("spark_reroll_choice", current_turn, f"score1={scores[0]} score2={scores[1]} -> finish {choice}")
            return choice
        if 1 in option_map:
            self._notify_spark_reroll_options = [list(option_map.get(1) or []), list(option_map.get(2) or [])]
            self._notify_spark_reroll_choice = 1
            self._log("spark_reroll_choice", current_turn, "reroll options missing; finishing original list")
            return 1
        raise RunFatalError("Spark Reroll response did not include selectable spark options; manual resolution required")

    def _finish_career_flow(self, client, strategy, state, preset, current_turn):
        from career_bot.engine.runner import RunFatalError

        data = state.get("data") or {}
        if data.get("race_start_info"):
            self._log("race_out", current_turn, "clearing active race")
            try:
                state = client.race_out(current_turn=current_turn)
            except Exception as e:
                if api_error_result_code(e) in (102, 201) or "StateRecoveryError" in str(e):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    state = self._fresh_career_state(client, strategy)
                else:
                    raise

        try:
            state = self._drain_events(client, strategy, state, limit=50)
        except Exception as e:
            if self._is_state_recovery_error(e):
                state = self._recover_state_error(client, strategy, current_turn, "finish_events_recovered", e)
            else:
                raise
        # Exhaustively spend leftover SP at career end. Each force-pass buys every
        # skill that currently fits; buying a white tier can unlock its gold tier
        # (_resolve_buyable_tier needs the previous tier owned), so several passes may
        # be needed. A transient 208 (server busy) makes a pass reload the session
        # (recover_after_error) and buy nothing -- that must NOT end the drain, or the
        # leftover SP is stranded; retry on the freshly-reloaded state instead. Stop
        # only when a pass that did NOT recover buys nothing more (truly drained) or SP
        # is gone. Bounded so a persistent error can't spin forever.
        drained = 0
        for _ in range(8):
            chara = (state.get("data") or {}).get("chara_info") or {}
            sp_before = int(chara.get("skill_point") or 0)
            if sp_before <= 0:
                break
            log.info(f"Draining leftover SP ({sp_before})...")
            state = self._buy_skills(client, state, preset, True)
            recovered = bool(self.skill_buyer.recover_after_error)
            self.skill_buyer.recover_after_error = False
            sp_after = int(((state.get("data") or {}).get("chara_info") or {}).get("skill_point") or 0)
            drained += max(0, sp_before - sp_after)
            if sp_after >= sp_before and not recovered:
                break  # nothing more buyable and no transient to retry -> drained
        if drained:
            self._log("sp_drain", current_turn, f"spent {drained} leftover SP")

        # Capture the real post-drain SP/stats NOW, from the state the drain produced.
        # finish_career below REPLACES `state` with the career-complete response, whose
        # chara_info can carry a stale pre-drain skill_point -- recording after it would
        # report the wrong (pre-drain) leftover SP on the webhook + summary.
        self._record_final_stats(state)

        if self.stop_after_sp_dump:
            self._log("sp_dump_stop", current_turn, "stopped after SP dump; finish submit skipped")
            self._mark(last_action="sp dump stop")
            self.stop()
            return state

        factor_lottery_id = self._choose_finish_factor_lottery_id(client, current_turn)
        try:
            state = client.finish_career(current_turn=current_turn, is_force_delete=False, factor_lottery_id=factor_lottery_id)
        except Exception as e:
            if factor_lottery_id in (1, 2):
                raise RunFatalError(f"finish_career failed after Spark Reroll choice {factor_lottery_id}: {e}") from e
            if api_error_result_code(e) in (102, 201) or "StateRecoveryError" in str(e):
                self._log("finish_reconciled", current_turn, f"graceful exit: {e}")
            else:
                raise
        self._capture_sparks(state)
        self._maybe_auto_delete_trained(client, state)
        self._mark(last_action="finish", finished=True)
        return state
