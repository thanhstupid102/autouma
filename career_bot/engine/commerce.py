"""Skill/item purchase-phase methods for CareerRunner, extracted verbatim from actions.py.

These are the two "spend the trainee's resources" phases the run loop drives around a
decision: `_buy_skills` (SP -> skills, counted from the server-side skill_array delta,
never from the API return) and `_handle_items` (MANT coins -> shop items + item use).
Both own only their own bookkeeping/debug rows; the buy/use policy lives in
SkillBuyer / MantItemManager, and the 205/208 desync reload is delegated to
`_fresh_career_state`.
"""

import logging
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerCommerceMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerCommerceMixin(_HostState):
    def _owned_skill_ids(self, state):
        chara = (state.get("data") or {}).get("chara_info") or {}
        return {int(r.get("skill_id") or 0) for r in (chara.get("skill_array") or []) if int(r.get("skill_id") or 0) > 0}

    def _buy_skills(self, client, state, preset, force):
        self.skill_buyer.recover_after_error = False
        pre_owned = self._owned_skill_ids(state)
        state, _est = self.skill_buyer.buy(client, state, preset, force)
        attempted_ids = set()
        for event in self.skill_buyer.attempt_events:
            for row in event.get("payload") or []:
                skill_id = int((row or {}).get("skill_id") or 0)
                if skill_id > 0:
                    attempted_ids.add(skill_id)
            self._debug("skills_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if self.skill_buyer.recover_after_error:
            try:
                # 205/208 desync: reload the career in place. client.call already retried
                # the op 3-5x; _fresh_career_state reloads (bare first, escalating to a
                # session relogin internally only if the bare reload also fails).
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                log.warning(f"Skill phase reload failure: {e}")
                pass
        post_owned = self._owned_skill_ids(state)
        bought = len((post_owned - pre_owned) & attempted_ids)
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"skills {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), bought)
        return state

    def _handle_items(self, client, state, preset, best_command, skip_buy=False, skip_use=False):
        # self.strategy is None only for bare CareerRunner instances in unit tests (start() always sets
        # it); that falls through to the legacy MANT item flow below, unlike _race's gate which just skips.
        if self.strategy is not None and not getattr(self.strategy, "handles_shop_items", False):
            return state
        data = state.get("data") or {}
        item_turn = int(((data.get("chara_info") or {}).get("turn")) or 0)
        self.item_manager.recover_after_exchange_error = False
        self.item_manager.recover_after_use_error = False
        state, bought, used = self.item_manager.handle(
            client,
            state,
            preset,
            best_command,
            self.status,
            self.race_planner,
            skip_use=skip_use or self._item_use_recovery_blocked(item_turn),
            skip_buy=skip_buy,
        )
        for event in self.item_manager.buy_attempt_events:
            self._debug("items_buy_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._shop_attempt_cost(event.get("attempt") or [], event.get("selected") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        for event in self.item_manager.use_attempt_events:
            self._debug("items_use_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if self.item_manager.recover_after_use_error:
            if self._allow_item_use_recovery(item_turn):
                try:
                    state = self._fresh_career_state(client, preserve_item_failures=True)
                    self._debug_turn(state, preset)
                except Exception as e:
                    log.warning(f"Item phase reload failure: {e}")
                    pass
            else:
                self.item_manager.recover_after_use_error = False
        elif self.item_manager.recover_after_exchange_error:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                log.warning(f"Item phase reload failure: {e}")
                pass
        if bought or used:
            turn = (state.get("data") or {}).get("chara_info", {}).get("turn", 0)
            with self.lock:
                self.status["items_bought"] += bought
                self.status["items_used"] += used
                if bought:
                    self._log_locked("items_buy", turn, bought)
                if used:
                    self._log_locked("items_use", turn, used)
            if used:
                self._log_item_use_text(turn, self.item_manager.last_use_selected, "Command items used")
        return state
