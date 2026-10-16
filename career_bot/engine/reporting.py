"""Career report and finalization methods for CareerRunner, extracted verbatim from runner.py."""

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

import core.operational_time as operational_time
from career_bot.engine.report import flush_report, mark_report_dirty, report_revision
from career_bot.scenarios.base import command_stat_gain
from career_bot.planning.spark.reroll import factor_ids_from_row
from uma_api import diagnostics
from uma_api.log_context import set_log_fields
from core.settings import Settings

log = logging.getLogger(__name__)

TRAINING_LABELS = {
    101: "Speed",
    102: "Power",
    103: "Guts",
    105: "Stamina",
    106: "Wit",
    601: "Speed",
    602: "Stamina",
    603: "Power",
    604: "Guts",
    605: "Wit",
}


def _api_failure_from_report(report):
    error = report.get("error") or {}
    failure = {
        "endpoint": error.get("endpoint"),
        "result_code": error.get("result_code"),
        "turn": report.get("final_turn"),
    }
    turns = sorted(
        report.get("turns") or [],
        key=lambda row: int(row.get("turn") or 0),
        reverse=True,
    )
    for turn in turns:
        for call in reversed(turn.get("api_calls") or []):
            direction = call.get("direction")
            result_code = call.get("result_code")
            if direction != "ERR" and result_code in (None, 1, "1"):
                continue
            failure["endpoint"] = call.get("endpoint") or failure["endpoint"]
            failure["result_code"] = result_code
            failure["turn"] = call.get("turn", turn.get("turn"))
            body = call.get("data")
            if result_code is not None and isinstance(body, dict):
                failure["detail"] = diagnostics.format_api_error(
                    failure["endpoint"] or "",
                    result_code,
                    body,
                )
            break
        if failure.get("endpoint"):
            break
    if not failure.get("endpoint") and failure.get("result_code") is None:
        return None
    return failure


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerReportMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerReportMixin(_HostState):
    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action

    def _mark(self, **values):
        with self.lock:
            self.status.update(values)
        # L2 structured fields: status["turn"] already IS the runner's single
        # notion of "which turn are we on", and _mark is its only writer after
        # start(), so mirroring it here gives every engine log record on this
        # thread a `turn` without touching any of the 20 call sites. Outside the
        # lock on purpose -- contextvars are per-thread state, never shared, so
        # they need no mutual exclusion and must not widen the status lock.
        if "turn" in values:
            set_log_fields(turn=values["turn"])

    def _log_locked(self, action, turn, detail):
        items = self.status.setdefault("log", [])
        items.append({
            "id": len(items) + 1,
            "action": action,
            "turn": int(turn or 0),
            "detail": str(detail or ""),
            "time": operational_time.utc_clock(),
        })
        if len(items) > 120:
            del items[:len(items) - 120]

    def _log(self, action, turn, detail):
        with self.lock:
            self._log_locked(action, turn, detail)

    def _record_action(self, decision, chara=None):
        payload = decision.payload or {}
        action = decision.action
        turn = int(payload["current_turn"])
        stats = self._turn_stats(chara or {})
        detail = self._format_turn_stats(stats) or str(decision.reason or "")
        score_detail = payload.get("_score_detail")
        score_debug = payload.get("_score_debug")
        facility_label = payload.get("_facility_label")
        facility = ""
        if action == "command":
            command_type = int(payload.get("command_type") or 0)
            command_id = int(payload.get("command_id") or 0)
            command_group_id = int(payload.get("command_group_id") or 0)
            if command_type == 1:
                action = "train"
                facility = str(facility_label or TRAINING_LABELS.get(command_id, str(command_id)))
            elif command_type == 8:
                action = "medic"
            elif command_type == 7:
                action = "rest"
                facility = str(command_group_id or command_id)
            elif command_type == 3:
                action = "recreation"
                facility = str(command_group_id or command_id)
            else:
                action = f"command {command_type}"
                facility = str(command_id or command_group_id)
        elif action in {"race", "race_progress"}:
            action = "race"
            program_id = int(payload.get("program_id") or 0)
            if program_id and self.race_planner:
                facility = self.race_planner.label(program_id)
            else:
                facility = str(program_id or "")
        elif payload.get("_facility"):
            facility = str(payload.get("_facility"))
        elif action == "finish":
            action = "finish"
        row = {
            "turn": turn,
            "action": action,
            "facility": facility,
            "detail": detail,
            "stats": stats,
            "time": operational_time.utc_clock(),
        }
        if score_detail:
            row["score_detail"] = str(score_detail)
        if score_debug is not None:
            row["score_debug"] = score_debug
        with self.lock:
            history = self.status.setdefault("action_history", [])
            if history and history[-1].get("turn") == row["turn"] and history[-1].get("action") == row["action"] and history[-1].get("facility") == row["facility"]:
                history[-1] = row
            else:
                history.append(row)
        if score_detail:
            log.info(self._format_action_history_line(row))

    def _flush_report(self, force=False):
        # Best-effort realtime persist of the in-memory report to its fixed path. Throttled
        # to ~once/2s unless forced (turn change / error) so per-step churn doesn't hammer
        # disk. Never raises -- a logging failure must not crash the run.
        if not self.report or not getattr(self, "_report_path", None):
            return
        try:
            revision = report_revision(self.report)
            if (
                revision is not None
                and revision == getattr(self, "_last_flushed_report_revision", None)
            ):
                return
            now = time.monotonic()
            if not force and (now - getattr(self, "_last_flush_ts", 0.0)) < 2.0:
                return
            flush_report(self.report, self._report_path)
            self._last_flush_ts = now
            self._last_flushed_report_revision = revision
        except Exception as e:
            log.warning(f"report flush failed: {type(e).__name__}")

    def _capture_sparks(self, state):
        # The just-finished uma's inheritance factors (sparks) live in the finish
        # response under single_mode_finish_common: the trained_chara entry whose
        # trained_chara_id matches the new trained_chara_id.
        try:
            sfc = ((state or {}).get("data") or {}).get("single_mode_finish_common") or {}
            tcid = sfc.get("trained_chara_id")
            for row in sfc.get("trained_chara") or []:
                if row.get("trained_chara_id") == tcid:
                    self._notify_factor_ids = factor_ids_from_row(row)
                    self._notify_rank = int(row.get("rank") or 0)
                    self._notify_rank_score = int(row.get("rank_score") or 0)
                    return
        # Pure introspection of an untrusted server payload: .get()/.items() on a
        # non-mapping -> AttributeError, int() over untrusted values -> TypeError /
        # ValueError. factor_ids_from_row type-guards its own input.
        except (AttributeError, TypeError, ValueError):
            pass

    def _build_notify_summary(self):
        report = self.report or {}
        turns = sorted(report.get("turns") or [], key=lambda t: int(t.get("turn") or 0))
        last_stats = {}
        races = 0
        for t in turns:
            if t.get("stats"):
                last_stats = t["stats"]
            if t.get("selected_action") == "race":
                races += 1
        duration = "?"
        st, en = report.get("started_at"), report.get("ended_at")
        if st and en:
            try:
                secs = (datetime.fromisoformat(en) - datetime.fromisoformat(st)).total_seconds()
                duration = f"{secs / 60:.1f} mnt"
            # fromisoformat -> ValueError on a malformed stamp, TypeError when the
            # report field is not a string.
            except (TypeError, ValueError):
                pass
        with self.lock:
            skills_bought = int(self.status.get("skills_bought") or 0)
            circuit_tripped = bool(self.status.get("circuit_tripped"))
            abort_reason = (
                str(self.status.get("last_error") or "")
                if circuit_tripped else ""
            )
        return {
            "status": report.get("status") or "",
            "account": (getattr(self, "_account", "")
                        or Settings.SWEEP_ACCOUNT or ""),
            "final_turn": report.get("final_turn") or 0,
            "preset": report.get("preset_name") or "",
            "stats": last_stats,
            "duration": duration,
            "skills_bought": skills_bought,
            "races": races,
            "fans": int(last_stats.get("fans") or 0),
            "card_id": getattr(self, "_notify_card_id", ""),
            "factor_ids": list(getattr(self, "_notify_factor_ids", []) or []),
            "spark_reroll_factor_ids": list(getattr(self, "_notify_spark_reroll_options", []) or []),
            "spark_reroll_choice": int(getattr(self, "_notify_spark_reroll_choice", 0) or 0),
            "rank": int(getattr(self, "_notify_rank", 0) or 0),
            "rank_score": int(getattr(self, "_notify_rank_score", 0) or 0),
            "loop_index": int(getattr(self, "_loop_index", 1) or 1),
            "loop_target": int(getattr(self, "_loop_target", 1) or 0),
            "resume_attempt": int(getattr(self, "_resume_attempt", 0) or 0),
            "resume_attempt_limit": int(
                getattr(self, "_resume_attempt_limit", 0) or 0
            ),
            "error": report.get("error") or None,
            "api_failure": _api_failure_from_report(report),
            "circuit_tripped": circuit_tripped,
            # This is populated only by the runner's fixed auto-backoff message;
            # never expose arbitrary server error text in Discord.
            "abort_reason": abort_reason,
        }

    def _record_final_stats(self, state):
        """The turn-78 snapshot + the 'finish' action_history row are recorded BEFORE
        the finish SP drain, so they hold the pre-drain skill_point. Refresh them from
        the post-drain state so the live webhook (_latest_stats reads action_history)
        and the career summary (_build_notify_summary reads report turn stats) report
        the real leftover SP, not the pre-drain value."""
        chara = (state.get("data") or {}).get("chara_info") or {}
        stats = self._turn_stats(chara)
        if not stats:
            return
        turn = int(chara.get("turn") or 0)
        detail = self._format_turn_stats(stats)
        with self.lock:
            history = self.status.get("action_history") or []
            if history:
                history[-1]["stats"] = stats
                if detail:
                    history[-1]["detail"] = detail
        if self.report:
            for row in self.report.get("turns") or []:
                if int(row.get("turn") or 0) == turn:
                    row["stats"] = stats
                    row["skill_point"] = stats.get("skill_point")
                    mark_report_dirty(self.report)
                    break

    def _maybe_auto_delete_trained(self, client, state):
        """Delete only the just-finished uma when its self-sparks fail the keep-filter."""
        try:
            cfg = getattr(self, "auto_delete_trained", None) or {}
            if not cfg.get("enabled"):
                return
            sfc = ((state or {}).get("data") or {}).get("single_mode_finish_common") or {}
            tcid = sfc.get("trained_chara_id")
            if not tcid:
                return
            factor_ids = list(getattr(self, "_notify_factor_ids", []) or [])
            from career_bot.planning.spark.keep_filter import keep_filter_matches, self_factors
            factors = self_factors(factor_ids)
            if keep_filter_matches(factors, cfg):
                return
            if not hasattr(client, "remove_trained_chara"):
                return
            # Unlock the id too in case it was memo-locked, else remove would 102.
            client.remove_trained_chara([tcid], unlock_ids=[tcid])
            self._log("auto_delete_trained", 0, f"deleted just-trained chara {tcid} (failed keep-filter)")
        except Exception as e:
            self._log("auto_delete_trained_error", 0, f"skipped: {e}")

    def _track_turn_scores(self, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        max_score = 0
        has_training = False
        for cmd in commands:
            if int(cmd.get("command_type") or 0) == 1:
                has_training = True
                score = command_stat_gain(cmd)
                if score > max_score:
                    max_score = score
        if has_training:
            with self.lock:
                dh = self.status.setdefault("date_history", [])
                sh = self.status.setdefault("score_history", [])
                if not dh or dh[-1] != turn:
                    dh.append(turn)
                    sh.append(max_score)
                    if len(dh) > 48:
                        dh.pop(0)
                        sh.pop(0)
