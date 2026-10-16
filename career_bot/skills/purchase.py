import logging
import re
from typing import TYPE_CHECKING, Any

from career_bot.skills.data import *  # noqa: F401 -- preserve legacy module attributes
from career_bot.skills.data import SkillBuyerState
from career_bot.state_merge import merge_state

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Type-only base: declares the SkillBuyer state / sibling-mixin helpers this
    # mixin borrows. At runtime the base is plain `object`, so the MRO is exactly
    # what `class SkillPurchaseMixin:` would produce.
    _HostState = SkillBuyerState
else:
    _HostState = object


class SkillPurchaseMixin(_HostState):

    def _plan(self, chara, preset, force, allow_force_expansion):
        """Resolve candidates + affordable selection for `chara`/`preset`.

        Shared read-only planning logic behind buy() and preview(). When
        `allow_force_expansion` is True (buy()'s semantics), a hoarding
        override relaxes the threshold gate and, once forced, leftover SP
        is spent by progressively relaxing candidate filters. When False
        (preview()'s semantics), the threshold gate ignores hoarding and no
        candidate-list expansion happens, matching preview()'s original
        (narrower) behaviour exactly.
        """
        points = int(chara.get("skill_point") or 0)
        threshold = int(preset.get("learn_skill_threshold") or 444)

        if allow_force_expansion:
            is_hoarding = points > 1500
            skip_threshold = not force and not is_hoarding and points <= threshold
        else:
            skip_threshold = not force and points <= threshold
        if skip_threshold:
            return {
                "candidates": [], "selected": [], "points": points, "threshold": threshold,
                "skip": "threshold",
            }

        if preset.get("manual_purchase_at_end") and not force:
            return {
                "candidates": [], "selected": [], "points": points, "threshold": threshold,
                "skip": "manual_purchase_at_end",
            }

        candidates = self._candidates(chara, preset)
        if allow_force_expansion and force and preset.get("skill_dump_leftover", True):
            # End of the career: don't waste leftover SP. After the important (priority /
            # user-provided / non-blacklisted) skills, append every OTHER still-available
            # skill -- first relaxing only-user-provided, then dropping the blacklist -- so
            # the greedy purchase below spends remaining SP on ANY buyable skill. Important
            # skills keep their place at the front, so the relaxed ones are reached only
            # once nothing better is left to buy.
            seen = {c["skill_id"] for c in candidates}
            for relaxed in (
                {**preset, "learn_skill_only_user_provided": False},
                {**preset, "learn_skill_only_user_provided": False, "learn_skill_blacklist": []},
            ):
                for extra in self._candidates(chara, relaxed):
                    if extra["skill_id"] not in seen:
                        seen.add(extra["skill_id"])
                        candidates.append(extra)
        elif allow_force_expansion and force and not candidates:
            candidates = self._candidates(chara, {**preset, "learn_skill_only_user_provided": False})

        if not candidates:
            return {
                "candidates": [], "selected": [], "points": points, "threshold": threshold,
                "skip": "no_candidates",
            }

        selected = []
        spent = 0
        for candidate in candidates:
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost > points:
                continue
            selected.append(candidate)
            spent += cost

        if not selected:
            return {
                "candidates": candidates, "selected": [], "points": points, "threshold": threshold,
                "skip": "not_enough_points",
            }

        return {
            "candidates": candidates, "selected": selected, "points": points, "threshold": threshold,
            "skip": None,
        }

    def buy(self, client, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self._sync_fast_learner(chara)
        self.recover_after_error = False
        self.attempt_events = []
        if not chara:
            return state, 0

        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)

        plan = self._plan(chara, preset, force, allow_force_expansion=True)
        self.last_candidates = [dict(item) for item in plan["candidates"]]

        skip = plan["skip"]
        if skip:
            self.last_selected = []
            self.last_attempt = []
            if skip == "threshold":
                self.last_result = {"skip": "threshold", "points": plan["points"], "threshold": plan["threshold"]}
            elif skip == "manual_purchase_at_end":
                self.last_result = {"skip": "manual_purchase_at_end"}
            else:
                self.last_result = {"skip": skip, "points": plan["points"]}
            return state, 0

        self.last_selected = [dict(item) for item in plan["selected"]]

        current_state, total_bought = self._buy_batch(client, state, plan["selected"], turn)

        return current_state, total_bought

    def preview(self, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self._sync_fast_learner(chara)
        if not chara:
            self.last_candidates = []
            self.last_selected = []
            return
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        plan = self._plan(chara, preset, force, allow_force_expansion=False)
        self.last_candidates = [dict(item) for item in plan["candidates"]]
        self.last_selected = [dict(item) for item in plan["selected"]]

    def _build_gain_payload(self, skill_ids, owned_skill_ids, seen_ids=None):
        """Dedup'd gain_skills payload entries for `skill_ids`, skipping any
        already-owned or unobtainable id. `seen_ids`, if given, is a set
        shared/mutated across multiple calls to dedup across a whole batch;
        omit it to dedup only within this single call."""
        payload = []
        seen = seen_ids if seen_ids is not None else set()
        for skill_id in skill_ids:
            skill_id = int(skill_id or 0)
            if skill_id in owned_skill_ids or skill_id in self.unobtainable:
                continue
            if skill_id > 0 and skill_id not in seen:
                payload.append({"skill_id": skill_id, "level": 1})
                seen.add(skill_id)
        return payload

    def _buy_batch(self, client, state, candidates, turn):
        if not candidates:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self._sync_fast_learner(chara)
        current_turn = int(chara.get("turn") or 0)
        
        if current_turn != turn:
            self.last_result = {"skip": "stale_turn_detected", "request_current_turn": turn, "source_state_turn": current_turn}
            return state, 0

        valid_tips = set()
        for tip in chara.get("skill_tips_array") or []:
            group_id = int(tip.get("group_id") or 0)
            valid_tips.update(self.group_to_skill_ids.get(group_id, []))
        owned_skill_ids = {
            int(item.get("skill_id") or 0)
            for item in chara.get("skill_array") or []
            if int(item.get("skill_id") or 0) > 0
        }
        owned_skill_ids |= self.bought  # never re-send a skill already bought this career

        points = int(chara.get("skill_point") or 0)
        selected_total_cost = 0
        valid_candidates = []

        for item in candidates:
            skill_id = item["skill_id"]
            cost = int(item.get("cost") or 0)
            if skill_id <= 0 or item.get("skip_reason"):
                item["preflight_error"] = "invalid_skill"
                continue
            if skill_id in owned_skill_ids:
                item["preflight_error"] = "already_owned"
                continue
            if skill_id in self.unobtainable:
                item["preflight_error"] = "unobtainable"
                continue
            if skill_id not in valid_tips:
                item["preflight_error"] = "not_in_tips"
                continue
            if selected_total_cost + cost > points:
                item["preflight_error"] = "unaffordable"
                continue
            item["preflight_passed"] = True
            selected_total_cost += cost
            valid_candidates.append(item)

        if not valid_candidates:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0

        payload = []
        payload_ids: set[int] = set()
        for item in valid_candidates:
            payload.extend(self._build_gain_payload(
                [item["skill_id"], *(item.get("bundled_skill_ids") or [])],
                owned_skill_ids, payload_ids,
            ))
        if not payload:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0
        self.last_attempt = [dict(item) for item in valid_candidates]
        event = {
            "turn": turn,
            "selected": [dict(item) for item in candidates],
            "attempt": [dict(item) for item in valid_candidates],
            "payload": payload,
            "result": {},
        }
        self.attempt_events.append(event)

        try:
            result = client.gain_skills(payload, turn)
            granted_count = len(payload)
            self.bought.update(int(p["skill_id"]) for p in payload)
            self.last_result = {"result": "ok", "turn": turn, "count": granted_count, "payload": payload}
            response_data = (result.get("data") or {}) if isinstance(result, dict) else {}
            response_chara = (
                response_data.get("chara_info")
                or response_data.get("single_mode_chara_light")
                or {}
            )
            if (
                isinstance(chara, dict)
                and "skill_point" in chara
                and isinstance(response_chara, dict)
                and "skill_point" in response_chara
            ):
                try:
                    actual_cost = int(chara["skill_point"]) - int(response_chara["skill_point"])
                except (TypeError, ValueError):
                    actual_cost = None
                if actual_cost is not None and actual_cost != selected_total_cost:
                    log.warning(
                        f"[skills] cost model drift turn {turn}: estimated {selected_total_cost} "
                        f"actual {actual_cost} payload {payload}"
                    )
                    self.last_result["estimated_cost"] = selected_total_cost
                    self.last_result["actual_cost"] = actual_cost
            event["result"] = self.last_result
            self._failed_for_turn(turn).clear()
            return self._merge_state(state, result), granted_count
        except Exception as exc:
            log.warning(f"Skill Purchase Error at turn {turn}: {exc}")
            # A 205 can be returned even when the batch committed server-side. Force
            # the runner to reconcile after this phase, and reload inside the split
            # fallback before any skill can be sent again.
            if self._error_has_code(exc, 205):
                self.recover_after_error = True
            # When the batch has more than one skill, reconcile ownership first and
            # then buy only missing, affordable skills one at a time so a genuine
            # offender does not waste the rest of the batch.
            if len(valid_candidates) > 1:
                return self._buy_individually(client, state, valid_candidates, turn, event)
            # Buying a skill is OPTIONAL, so a rejected skill is just skipped (marked
            # failed-this-turn below), never crashing the run. 201 = "this career cannot
            # buy this skill" -> remember it for the whole career. Only 208 on this batch
            # endpoint loses the sid (next call would 201 -> cascade), so 208 also needs a
            # session reload. A 205 is already marked above because commit is uncertain.
            if self._error_has_code(exc, 201):
                self._mark_unobtainable(*(int(item["skill_id"]) for item in valid_candidates))
            if self._error_has_code(exc, 208):
                self.recover_after_error = True
            self._failed_for_turn(turn).update(int(item["skill_id"]) for item in valid_candidates)
            self.last_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": payload}
            event["result"] = self.last_result
            return state, 0

    def _buy_individually(self, client, state, candidates, turn, event):
        """Reconcile a failed batch, then buy only missing candidates individually."""
        fresh_chara: dict[str, Any] = {}
        if hasattr(client, "load_career"):
            try:
                fresh = client.load_career()
            except Exception as exc:
                log.warning(f"Skill Purchase Error reloading after batch failure at turn {turn}: {exc}")
                self.recover_after_error = True
                self.last_result = {
                    "result": "failed",
                    "turn": turn,
                    "count": 0,
                    "split_retry": True,
                    "reload_failed": True,
                    "error": str(exc),
                    "results": [],
                }
                event["result"] = self.last_result
                return state, 0
            state = self._merge_state(state, fresh)
            fresh_data = (fresh.get("data") or {}) if isinstance(fresh, dict) else {}
            fresh_chara = (
                fresh_data.get("chara_info")
                or fresh_data.get("single_mode_chara_light")
                or {}
            )
            self._sync_fast_learner(fresh_chara)

        if fresh_chara:
            chara = fresh_chara
        else:
            data = (state.get("data") or {}) if isinstance(state, dict) else {}
            chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}

        owned = {
            int(row.get("skill_id") or 0)
            for row in chara.get("skill_array") or []
            if int(row.get("skill_id") or 0) > 0
        }
        owned |= self.bought
        points = int(chara.get("skill_point") or 0)
        points_from_snapshot = isinstance(chara, dict) and "skill_point" in chara
        bought = 0
        results = []
        for item in candidates:
            primary_id = int(item["skill_id"] or 0)
            if primary_id in owned:
                # Reconcile a batch that committed despite returning an error. Keeping
                # this in bought also protects later passes with stale response state.
                self.bought.add(primary_id)
                results.append({"skill_id": primary_id, "ok": False, "skipped": "already_owned"})
                continue

            # never re-send an owned / already-bought / unbuyable skill
            sub_payload = self._build_gain_payload(
                [primary_id, *(item.get("bundled_skill_ids") or [])], owned,
            )
            if not sub_payload:
                continue

            estimated_cost = 0
            for payload_item in sub_payload:
                sid = int(payload_item["skill_id"])
                is_primary = sid == primary_id
                estimated_cost += self._estimate_cost({
                    "skill_id": sid,
                    "hint_level": item.get("hint_level", 0) if is_primary else 0,
                    "name": item.get("name", "") if is_primary else self.skill_names.get(sid, ""),
                })
            if estimated_cost > points:
                results.append({"skill_id": primary_id, "ok": False, "skipped": "unaffordable"})
                continue

            try:
                points_before = points if points_from_snapshot else None
                res = client.gain_skills(sub_payload, turn)
                state = self._merge_state(state, res)
                sent_ids = {int(payload_item["skill_id"]) for payload_item in sub_payload}
                self.bought.update(sent_ids)
                owned.update(sent_ids)
                bought += len(sub_payload)

                response_data = (res.get("data") or {}) if isinstance(res, dict) else {}
                response_chara = (
                    response_data.get("chara_info")
                    or response_data.get("single_mode_chara_light")
                    or {}
                )
                if response_chara:
                    owned.update(
                        int(row.get("skill_id") or 0)
                        for row in response_chara.get("skill_array") or []
                        if int(row.get("skill_id") or 0) > 0
                    )
                success_result: dict[str, Any] = {"skill_id": primary_id, "ok": True}
                if isinstance(response_chara, dict) and "skill_point" in response_chara:
                    points_after = int(response_chara.get("skill_point") or 0)
                    if points_before is not None:
                        actual_cost = points_before - points_after
                        if actual_cost != estimated_cost:
                            log.warning(
                                f"[skills] cost model drift turn {turn}: estimated {estimated_cost} "
                                f"actual {actual_cost} payload {sub_payload}"
                            )
                            success_result["estimated_cost"] = estimated_cost
                            success_result["actual_cost"] = actual_cost
                    points = points_after
                    points_from_snapshot = True
                else:
                    points -= estimated_cost
                    points_from_snapshot = False
                results.append(success_result)
            except Exception as exc:
                log.warning(f"Skill Purchase Error (single) at turn {turn} skill {item['skill_id']}: {exc}")
                # 201 -> not buyable this career (remember, skip, no reload).
                # 205 -> commit is uncertain; 208 -> sid may need resync.
                if self._error_has_code(exc, 201):
                    self._mark_unobtainable(primary_id)
                if self._error_has_code(exc, 205, 208):
                    self.recover_after_error = True
                self._failed_for_turn(turn).add(primary_id)
                results.append({"skill_id": primary_id, "ok": False, "error": str(exc)})
        self.last_result = {
            "result": "ok" if bought else "failed",
            "turn": turn,
            "count": bought,
            "split_retry": True,
            "results": results,
        }
        event["result"] = self.last_result
        return state, bought

    def _merge_state(self, state, res):
        return merge_state(state, res)

    def reset_scoped_failures(self):
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}

    def _error_has_code(self, exc, *codes):
        text = str(exc or "")
        return any(re.search(rf"\b{int(code)}\b", text) for code in codes)

    def _mark_unobtainable(self, *skill_ids):
        # 201 on gain_skills means this career cannot buy that skill -- not that the
        # turn snapshot is stale. Remember it for the whole career so the finish-time
        # SP drain stops burning later turns/passes retrying the same unbuyable skill.
        # Only the primary resolved id is marked, never bundled white prerequisites
        # (those may be independently buyable on a later pass).
        for skill_id in skill_ids:
            skill_id = int(skill_id or 0)
            if skill_id > 0:
                self.unobtainable.add(skill_id)

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_this_turn = {turn: set()}
        self.failed_this_turn.setdefault(turn, set())

    def _failed_for_turn(self, turn=None):
        turn = int(turn if turn is not None else self.current_turn or 0)
        return self.failed_this_turn.setdefault(turn, set())

