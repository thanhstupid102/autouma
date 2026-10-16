"""Race-flow methods for CareerRunner, extracted verbatim from actions.py.

Two entry points -- `_race` (the normal entry -> start -> clock retries -> end ->
out sequence) and `_race_progress` (resuming a career the server left parked
mid-race) -- plus their read-only helpers: the race-scenario blob parser that
recovers the finish order and the debut/maiden force-clock rule. The clock
(continue) accounting itself lives inline in `_race`.

`dna_gauss`/`dna_sleep` are imported from `career_bot.delay` exactly as actions.py
did, so the clock-retry pacing keeps resolving through the same binding it always
has (the runner-module `dna_sleep` indirection that `recovery.py` uses is a
different, deliberately separate seam).
"""

import logging
from typing import TYPE_CHECKING, Any

from career_bot.delay import dna_gauss, dna_sleep
from uma_api.errors import api_error_result_code, is_blocked_state_error

log = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerRaceMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerRaceMixin(_HostState):
    _RACE_ENTRY_208_RELOAD_LIMIT = 2

    def _parse_race_rank(self, res):
        import base64
        import gzip
        import struct

        data = res.get("data", {})
        headers = res.get("data_headers", {})
        viewer_id = int(headers.get("viewer_id") or 0)

        race_start_info = data.get("race_start_info", {})
        horses = race_start_info.get("race_horse_data", [])

        player = next((horse for horse in horses if int(horse.get("viewer_id") or 0) == viewer_id), None)
        if not player:
            return 99

        frame_order = player.get("frame_order")
        if not frame_order:
            return 99

        result_index = frame_order - 1

        scenario_b64 = data.get("race_scenario")
        if not scenario_b64:
            return 99

        try:
            blob = gzip.decompress(base64.b64decode(scenario_b64))
        except Exception:
            return 99

        offset = 0

        if len(blob) < offset + 4: return 99
        header_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + header_len

        if len(blob) < offset + 16: return 99
        distance_diff_max, horse_num, horse_frame_size, horse_result_size = struct.unpack_from("<fiii", blob, offset)
        offset += 16

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if len(blob) < offset + 8: return 99
        frame_count, frame_size = struct.unpack_from("<ii", blob, offset)
        offset += 8 + frame_count * frame_size

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if not (0 <= result_index < horse_num):
            return 99

        if len(blob) < offset + (result_index + 1) * horse_result_size:
            return 99

        finish_order = struct.unpack_from("<i", blob, offset + result_index * horse_result_size)[0]

        return finish_order + 1

    def _should_force_clocks(self, program_id, preset):
        """Always retry (burn clocks) to win the early mandatory races — the
        Junior Make Debut and the Junior/Classic Maiden races — even if the global
        burn-clocks toggle is off, so a lost early race can't fail the career.
        Matches the same debut/maiden race set as master_data (which treats
        "Make Debut"/"Maiden Race" as the non-regular first races). Controlled by
        preset 'force_clock_debut' (default True)."""
        if not (preset or {}).get("force_clock_debut", True):
            return False
        if not self.race_planner:
            return False
        info = (self.race_planner.program or {}).get(int(program_id or 0)) or {}
        name = str(info.get("name") or "").lower()
        return "make debut" in name or "maiden race" in name

    def _continue_budget_after(self, client, response, total, free, continue_type):
        cont_data = response.get("data") or {}
        new_home_info = cont_data.get("home_info")
        if isinstance(new_home_info, dict):
            total = int(new_home_info.get("available_continue_num", 0))
            free = int(new_home_info.get("available_free_continue_num", 0))
        else:
            total = max(total - 1, 0)
            if continue_type == 1:
                free = max(free - 1, 0)
        if continue_type == 2:
            self._sync_cached_alarm_clock_count(client, response)
        return cont_data, total, free

    def _handle_race_entry_error(self, client, strategy, current_turn, program_id, exc):
        log.warning(f"Race Entry Error at turn {current_turn}: {exc}")
        if self._is_state_recovery_error(exc):
            return self._recover_state_error(client, strategy, current_turn, "race_entry_recovered", exc)
        result_code = api_error_result_code(exc)
        if result_code not in (205, 208):
            raise
        if result_code == 208:
            counters = getattr(self, "_race_entry_208_counts", None)
            if not isinstance(counters, dict):
                counters = {}
                self._race_entry_208_counts = counters
            key = (int(current_turn or 0), int(program_id or 0))
            count = int(counters.get(key) or 0) + 1
            counters[key] = count
            if count <= self._RACE_ENTRY_208_RELOAD_LIMIT:
                self._log(
                    "race_entry_retry",
                    current_turn,
                    f"result_code=208 transient; reload {count}/{self._RACE_ENTRY_208_RELOAD_LIMIT}",
                )
                return self._fresh_career_state(client, strategy)
            self._log(
                "race_entry_retry_exhausted",
                current_turn,
                f"result_code=208 persisted after {count} surfaced failures; rejecting {program_id}",
            )
        else:
            self._log(
                "race_entry_rejected",
                current_turn,
                f"result_code=205 deterministic rejection for {program_id}",
            )
        self.race_planner.reject(current_turn, program_id)
        self._log("race_reject", current_turn, program_id)
        return self._fresh_career_state(client, strategy)

    def _race(self, client, state, preset, payload):
        if getattr(self.strategy, "handles_shop_items", False):
            item_turn = int(payload.get("current_turn") or 0)
            if self._last_race_action_turn is not None and item_turn == self._last_race_action_turn + 1:
                self._consecutive_race_count += 1
            else:
                self._consecutive_race_count = 1
            self.status["consecutive_race_count"] = self._consecutive_race_count
            self.item_manager.recover_after_use_error = False
            self.item_manager.recover_after_exchange_error = False
            state, used = self.item_manager.handle_pre_race(
                client,
                state,
                preset,
                payload,
                self.status,
                self.race_planner,
                skip_use=self._item_use_recovery_blocked(item_turn),
            )
            for event in self.item_manager.use_attempt_events:
                self._debug("items_use_attempt", state, {
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "payload": event.get("payload") or [],
                    "result": self._api_result(event.get("result") or {}),
                })
            if self.item_manager.recover_after_use_error:
                if not self._allow_item_use_recovery(item_turn):
                    self.item_manager.recover_after_use_error = False
                else:
                    state = self._fresh_career_state(client, payload.get("_strategy"), preserve_item_failures=True)
                    self._debug_turn(state, preset)
                    return state
            elif self.item_manager.recover_after_exchange_error:
                state = self._fresh_career_state(client, payload.get("_strategy"))
                self._debug_turn(state, preset)
                return state
            if used > 0:
                with self.lock:
                    self.status["items_used"] += used
                    self._log_locked("items_use", payload["current_turn"], f"pre-race {used}")
                self._log_item_use_text(payload["current_turn"], self.item_manager.last_use_selected + self.item_manager.last_pre_race_use_selected, "Race items used")

        program_id = payload.get("program_id")
        current_turn = payload["current_turn"]
        strategy = payload.get("_strategy")

        # Preset value, unvalidated: absent/None/garbage is caught below.
        running_style: Any = preset.get("running_style") if isinstance(preset, dict) else None
        try:
            running_style = int(running_style)
        except (TypeError, ValueError):
            running_style = 0

        try:
            entry = client.race_entry(program_id=program_id, current_turn=current_turn)
        except Exception as exc:
            return self._handle_race_entry_error(client, strategy, current_turn, program_id, exc)
        getattr(self, "_race_entry_208_counts", {}).pop(
            (int(current_turn or 0), int(program_id or 0)),
            None,
        )
        self._last_race_action_turn = current_turn
        self._log("race_entry", current_turn, program_id)
        entry_data = entry.get("data") or {}
        chara_info = entry_data.get("chara_info") or {}
        if strategy:
            if entry_data.get("unchecked_event_array"):
                entry = self._drain_events(client, strategy, entry)
                entry_data = entry.get("data") or {}
                chara_info = entry_data.get("chara_info") or {}

        try:
            current_running_style = int(chara_info.get("race_running_style") or 0)
        except (TypeError, ValueError):
            current_running_style = 0
        if running_style in (1, 2, 3, 4) and current_running_style != running_style:
            try:
                entry = client.race_entry(
                    program_id=program_id,
                    current_turn=current_turn,
                    running_style=running_style,
                    retry_208=0,
                    retry_205=0,
                )
            except Exception as exc:
                if self._is_state_recovery_error(exc):
                    return self._recover_state_error(client, strategy, current_turn, "race_entry_recovered", exc)
                raise
        is_short = 1
        try:
            res = client.race_start(is_short=is_short, current_turn=current_turn)
        except Exception as exc:
            if self._is_state_recovery_error(exc):
                return self._recover_state_error(client, strategy, current_turn, "race_start_recovered", exc)
            raise
        self._log("race_start", current_turn, f"short {is_short}")

        rank = self._parse_race_rank(res)
        self._log("race_rank", current_turn, f"rank {rank}")

        home_info = (state.get("data") or {}).get("home_info") or {}
        # available_continue_num is the remaining total retry budget (free
        # included); available_free_continue_num is its remaining free subset;
        # free_continue_num is the daily maximum, not a remainder; owned Alarm
        # Clocks are user_item item 95 and are not represented by home_info.
        remaining_retry_budget = int(home_info.get("available_continue_num", 0))
        free_clocks = int(home_info.get("available_free_continue_num", 0))

        # Clock (continue) policy branches on the scenario's free_clock_retry
        # capability (career_bot/scenarios/base.py): MANT (True) keeps the
        # legacy "force clocks until 1st place" behavior unconditionally on any
        # _should_force_clocks-matched or _mandatory race, ORed with the global
        # burn_clocks toggle. Non-MANT scenarios (Unity Cup) instead only clock
        # a route-objective race the trainee just failed -- Decision.payload
        # carries "_required_rank" (the route's required finish rank, set by
        # UnityCupStrategy.next_decision) and clocks retry until that rank is
        # met; a race without "_required_rank" (non-objective, e.g. a preset
        # race) never clocks, and the global burn_clocks toggle is not
        # consulted (R2).
        retry_capable = bool(getattr(self.strategy, "free_clock_retry", False))
        if retry_capable:
            force_clocks = self._should_force_clocks(program_id, preset) or bool(payload.get("_mandatory"))
            target_rank = 1
            clock_gate = self.burn_clocks or force_clocks
        else:
            required_rank = payload.get("_required_rank")
            target_rank = int(required_rank) if required_rank is not None else 1
            force_clocks = required_rank is not None and rank > target_rank
            clock_gate = force_clocks

        if force_clocks and rank > target_rank:
            if retry_capable:
                self._log("race_clock_force", current_turn, f"forcing 1st place on debut (rank {rank})")
            else:
                self._log("race_clock_force", current_turn, f"forcing rank <= {target_rank} (rank {rank})")

        while clock_gate and rank > target_rank and remaining_retry_budget > 0:
            continue_type = 1 if free_clocks > 0 else 2

            self._log(
                "race_clock",
                current_turn,
                f"rank {rank}, retries left total={remaining_retry_budget}, "
                f"free={free_clocks}, type={continue_type}",
            )
            if continue_type == 2:
                if not self._ensure_alarm_clock(client, preset):
                    break
            try:
                cont_res = client.race_continue(current_turn=current_turn, continue_type=continue_type)
            except Exception as e:
                if self._is_state_recovery_error(e):
                    return self._recover_state_error(
                        client,
                        strategy,
                        current_turn,
                        "race_start_recovered",
                        e,
                    )
                result_code = api_error_result_code(e)
                code_text = result_code if result_code is not None else "unknown"
                self._log(
                    "race_clock_failed",
                    current_turn,
                    f"result_code={code_text}: {e}",
                )
                if is_blocked_state_error(e):
                    return self._recover_blocked_state(client, strategy, state)
                break

            try:
                cont_data, remaining_retry_budget, free_clocks = self._continue_budget_after(
                    client,
                    cont_res,
                    remaining_retry_budget,
                    free_clocks,
                    continue_type,
                )

                if strategy:
                    if cont_data.get("unchecked_event_array"):
                        self._drain_events(client, strategy, cont_res)

                dna_gauss(0.166 + client.api_jitter, 0.05)
                dna_sleep(0.1, 0.45, 0.166 + client.api_jitter, 0.05)
                res = client.race_start(is_short=is_short, current_turn=current_turn)
                rank = self._parse_race_rank(res)
                self._log("race_rank_retry", current_turn, f"rank {rank} after clock")
                self._record_clock_used()
            except Exception as e:
                if self._is_state_recovery_error(e):
                    return self._recover_state_error(client, strategy, current_turn, "race_start_recovered", e)
                result_code = api_error_result_code(e)
                code_text = result_code if result_code is not None else "unknown"
                self._log(
                    "race_clock_failed",
                    current_turn,
                    f"result_code={code_text}: {e}",
                )
                break

        if strategy:
            res_data = res.get("data") or {}
            if res_data.get("unchecked_event_array"):
                res = self._drain_events(client, strategy, res)

        if self.strategy is not None:
            recorder = getattr(self.strategy, "record_race_result", None)
            if callable(recorder):
                recorder(program_id, rank)

        out = res
        out_refreshed = False
        try:
            client.race_end(current_turn=current_turn)
            self._log("race_end", current_turn, "")
        except Exception as e:
            if api_error_result_code(e) in (102, 1503):
                self._log("race_end_reconciled", current_turn, "server already done (102)")
            elif self._is_state_recovery_error(e):
                return self._recover_state_error(client, strategy, current_turn, "race_end_recovered", e)
            else:
                raise

        try:
            out_res = client.race_out(current_turn=current_turn)
            out = out_res
            out_refreshed = True
            if strategy:
                out_data = out.get("data") or {}
                if out_data.get("unchecked_event_array"):
                    out = self._drain_events(client, strategy, out)
        except Exception as e:
            if api_error_result_code(e) in (102, 1503):
                self._log("race_out_reconciled", current_turn, "server already done (102)")
            elif self._is_state_recovery_error(e):
                return self._recover_race_out(client, strategy, current_turn, "race_out_recovered", e, program_id=program_id)
            else:
                raise

        # If race_out returned 102 ("already done") we never got a fresh post-race state, so
        # `out` is still the stale race_start state with the race active -- which makes
        # next_decision loop on the same race. Reload the real current state so the turn
        # advances (the common "resume a career mid/just-after a race" case).
        if not out_refreshed:
            try:
                out = self._fresh_career_state(client, strategy)
                self._log("race_reconcile_refresh", current_turn, "reloaded state after 102")
            except Exception as e:
                self._log("race_reconcile_refresh_failed", current_turn, str(e))

        return out

    def _race_progress(self, client, payload, preset=None):
        current_turn = payload["current_turn"]
        phase = payload.get("phase")
        chara = (payload.get("chara_info") or {})
        playing_state = chara.get("playing_state") or 0
        # program_id for the stuck-race re-entry reset in _recover_race_out (race_out 201).
        progress_program_id = (payload.get("race_start_info") or {}).get("program_id") or chara.get("race_program_id")
        if playing_state not in {2, 3, 4, 5}:
            self._log("race_skip", current_turn, f"not in race (state={playing_state})")
            return payload

        if phase == "end":
            if playing_state in {1}:
                self._log("race_end_skip", current_turn, "resume already home")
            else:
                try:
                    client.race_end(current_turn=current_turn)
                    self._log("race_end", current_turn, "resume")
                except Exception as e:
                    if api_error_result_code(e) in (102, 1503):
                        self._log("race_end_reconciled", current_turn, "resume already done (102)")
                    elif self._is_state_recovery_error(e):
                        return self._recover_state_error(client, payload.get("_strategy"), current_turn, "race_end_recovered", e)
                    else:
                        raise
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if api_error_result_code(e) in (102, 1503):
                    self._log("race_out_reconciled", current_turn, f"already done: {e}")
                    # already-done on resume -> reload the real state so the turn
                    # advances, instead of looping on the stale (still-in-race) payload.
                    return self._fresh_career_state(client, payload.get("_strategy"))
                if self._is_state_recovery_error(e):
                    return self._recover_race_out(client, payload.get("_strategy"), current_turn, "race_out_recovered", e, program_id=progress_program_id)
                raise
        if phase == "out":
            self._log("race_out", current_turn, "resume")
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if api_error_result_code(e) in (102, 1503):
                    self._log("race_out_reconciled", current_turn, f"already done: {e}")
                    # already-done on resume -> reload the real state so the turn
                    # advances, instead of looping on the stale (still-in-race) payload.
                    return self._fresh_career_state(client, payload.get("_strategy"))
                if self._is_state_recovery_error(e):
                    return self._recover_race_out(client, payload.get("_strategy"), current_turn, "race_out_recovered", e, program_id=progress_program_id)
                raise
        race_start_info = payload.get("race_start_info") or {}
        program_id = race_start_info.get("program_id")
        # Preset value, unvalidated: absent/None/garbage is caught below.
        running_style: Any = preset.get("running_style") if isinstance(preset, dict) else None
        try:
            running_style = int(running_style)
        except (TypeError, ValueError):
            running_style = 0
        horse = ((race_start_info.get("race_horse_data") or []) + [{}])[0]
        try:
            current_running_style = int(chara.get("race_running_style") or horse.get("running_style") or 0)
        except (TypeError, ValueError):
            current_running_style = 0
        if playing_state in {2, 4} and program_id and running_style in (1, 2, 3, 4) and current_running_style != running_style:
            try:
                client.race_entry(
                    program_id=program_id,
                    current_turn=current_turn,
                    running_style=running_style,
                    retry_208=0,
                    retry_205=0,
                )
            except Exception as e:
                if self._is_state_recovery_error(e):
                    return self._recover_state_error(client, payload.get("_strategy"), current_turn, "race_entry_recovered", e)
                raise
        # On a race_out-201 recovery retry the race is already finished server-side
        # (logs show race_end returning 102 "already done", playing_state stuck at 3).
        # Re-running race_start just re-enters an already-ended race -- pointless churn
        # on every loop. Skip straight to the exit so we don't keep re-racing a done
        # race while trying to clear the stuck result screen. Gated to recovery retries
        # only, so the normal first-pass race flow is unchanged.
        skip_start = (
            self._race_recover_turn == current_turn
            and self._race_recover_count > 0
            and playing_state == 3
        )
        if skip_start:
            self._log("race_start_skip", current_turn, "recovery: race already started (state 3)")
        else:
            try:
                client.race_start(is_short=1, current_turn=current_turn)
            except Exception as e:
                if self._is_state_recovery_error(e):
                    return self._recover_state_error(client, payload.get("_strategy"), current_turn, "race_start_recovered", e)
                raise
            self._log("race_start", current_turn, "resume")
        if playing_state in {1}:
            self._log("race_end_skip", current_turn, "resume already home")
        else:
            try:
                client.race_end(current_turn=current_turn)
                self._log("race_end", current_turn, "resume")
            except Exception as e:
                if api_error_result_code(e) in (102, 1503):
                    self._log("race_end_reconciled", current_turn, "resume already done (102)")
                elif self._is_state_recovery_error(e):
                    return self._recover_state_error(client, payload.get("_strategy"), current_turn, "race_end_recovered", e)
                else:
                    raise
        try:
            return client.race_out(current_turn=current_turn)
        except Exception as e:
            if api_error_result_code(e) in (102, 1503):
                self._log("race_out_reconciled", current_turn, f"already done: {e}")
                return self._fresh_career_state(client, payload.get("_strategy"))
            if self._is_state_recovery_error(e):
                return self._recover_race_out(client, payload.get("_strategy"), current_turn, "race_out_recovered", e, program_id=progress_program_id)
            raise
