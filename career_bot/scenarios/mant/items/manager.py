import logging

from career_bot.scenarios.mant.items.data import *
from career_bot.state_merge import merge_state
from uma_api.errors import api_error_result_code
from career_bot.scenarios.mant.items.shop import MantShopMixin
from career_bot.scenarios.mant.items.summer import MantSummerMixin
from career_bot.scenarios.mant.items.use import MantUseMixin

log = logging.getLogger(__name__)


class MantItemManager(MantShopMixin, MantSummerMixin, MantUseMixin):
    def __init__(self):
        self.used_buffs = set()
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.shop_snapshot_key = None
        self.recover_after_exchange_error = False
        self.recover_after_use_error = False
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []
        self.first_shop_megaphone_done = False
        self.first_shop_megaphone_to_use = None

    def reset_scoped_failures(self):
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.shop_snapshot_key = None
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_use_this_turn = set()

    def _set_shop_snapshot(self, rows):
        key = tuple(
            (
                int(row.get("shop_item_id") or 0),
                int(row.get("item_id") or 0),
                int(row.get("coin_num") or 0),
                int(row.get("item_buy_num") or 0),
                int(row.get("limit_buy_count") or 0),
                int(row.get("limit_turn") or 0),
            )
            for row in rows or []
        )
        if self.shop_snapshot_key != key:
            self.shop_snapshot_key = key
            self.failed_exchange_this_snapshot = set()

    def handle(self, client, state, preset, best_command=None, status=None, race_planner=None, skip_use=False, skip_buy=False):
        current = state
        self.recover_after_exchange_error = False
        bought = 0
        if not skip_buy:
            current, bought = self.buy_shop_items(client, current, preset, race_planner)

        self.recover_after_use_error = False
        if skip_use:
            turn = int(((current.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
            self.last_use_result = {"skip": "item_use_recovery_cap", "turn": turn}
            self.last_use_attempt = []
            self.use_attempt_events = []
            return current, bought, 0
        current, used = self.use_items(client, current, preset, best_command, status, race_planner)

        return current, bought, used

    def handle_pre_race(self, client, state, preset, payload, status=None, race_planner=None, skip_use=False):
        self.recover_after_exchange_error = False
        current, bought = self.buy_shop_items(client, state, preset, race_planner)

        self.recover_after_use_error = False
        if skip_use:
            turn = int(((current.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
            self.last_use_result = {"skip": "item_use_recovery_cap", "turn": turn}
            self.last_pre_race_use_result = {"skip": "item_use_recovery_cap", "turn": turn}
            self.last_use_attempt = []
            self.last_pre_race_use_attempt = []
            self.use_attempt_events = []
            return current, 0
        current, instant_used = self.use_items(client, current, preset, {"command_type": 4}, status, race_planner)
        data = current.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}

        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        program_id = int((payload or {}).get("program_id") or 0)

        if not owned:
            self.last_pre_race_use_result = {"skip": "no_owned"}
            return current, instant_used

        targets = []

        vital = int(chara.get("vital") or 0)
        consecutive = int((status or {}).get("consecutive_race_count") or 1)
        if consecutive < 3 and vital == 0 and int(owned.get("Energy Drink MAX", 0) or 0) > 0:
            targets.append(("Energy Drink MAX", 1))

        is_g1 = self._is_g1_program(program_id, race_planner)
        is_climax = turn in CLIMAX_RACE_TURNS
        # Cleat Hammer (Artisan 20% / Master 35%) is reserved for G1 races only
        # (the climax finale is itself G1, so it is covered here).
        cleat_choice = self._old_ui_cleat_before_race(owned, turn, program_id, race_planner) if (is_g1 or is_climax) else None
        if cleat_choice:
            targets.append((cleat_choice, 1))
        targets = self._merge_targets(targets, owned)
        self.last_pre_race_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in targets]
        if not targets:
            self.last_pre_race_use_result = {"skip": "no_targets"}
            return current, instant_used

        use_payload = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            item_count = int(owned.get(name) or 0)
            if item_count <= 0:
                continue
            use_payload.append({"item_id": item_id, "use_num": min(count, item_count), "current_num": item_count})

        if use_payload:
            self.last_pre_race_use_attempt = list(use_payload)
            event = {
                "turn": turn,
                "selected": list(self.last_pre_race_use_selected),
                "attempt": list(use_payload),
                "payload": list(use_payload),
                "result": {},
            }
            self.use_attempt_events.append(event)
            try:
                self.last_pre_race_use_result = client.use_items(use_payload, turn)
                current = self._merge_state(current, self.last_pre_race_use_result)
                self.last_pre_race_use_result = {"result": "ok", "turn": turn, "payload": use_payload}
                event["result"] = self.last_pre_race_use_result
                return current, instant_used + len(use_payload)
            except Exception as exc:
                log.warning(f"Pre-Race Item Use Error at turn {turn}: {exc}")
                if api_error_result_code(exc) in (201, 205, 208):
                    # Optional item: skip the offender (mark failed-this-turn) and carry
                    # on. Only 208 loses the sid on this batch endpoint -> reload to
                    # resync; 201/205 keep the sid synced and are safely skipped.
                    for item in use_payload:
                        self.failed_use_this_turn.add(item["item_id"])
                    if api_error_result_code(exc) == 208:
                        self.recover_after_use_error = True
                self.last_pre_race_use_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": use_payload}
                event["result"] = self.last_pre_race_use_result
                return current, instant_used

        return current, instant_used

    def _merge_state(self, state, res):
        return merge_state(state, res)
