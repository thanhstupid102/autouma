"""Charm / energy-item rescue decisions -- mirrors the item-spend half of the
same rule in career_bot/scenarios/mant/items/use.py."""

from typing import TYPE_CHECKING, Any

from career_bot.scenarios.base import LATE_AGGRESSIVE_TURN, LATE_UNCOVERED_FAILURE_REST

ENERGY_ITEM_VALUES = {2001: 20, 2002: 40, 2003: 65, 2101: 100}  # Vita 20/40/65, Royal Kale Juice
GOOD_LUCK_CHARM_ID = 10001
RESET_WHISTLE_ID = 7001


class MantRescueMixin:
    LATE_AGGRESSIVE_TURN = LATE_AGGRESSIVE_TURN
    LATE_UNCOVERED_FAILURE_REST = LATE_UNCOVERED_FAILURE_REST

    if TYPE_CHECKING:
        # Host contract: supplied by ScenarioStrategy, which every host of this
        # mixin also inherits. TYPE_CHECKING-only, so no runtime member is added.
        def _rainbow_count(self, command: Any, chara: Any) -> int: ...

    def _owned_item_count(self, data, item_id):
        total = 0
        for row in (data.get("free_data_set") or {}).get("user_item_info_array") or []:
            if int(row.get("item_id") or 0) == int(item_id):
                total += int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
        return total

    def _rescue_energy_value(self, data, vital, rest_threshold, margin, any_owned=False):
        """Restore value of the SMALLEST owned energy item that would lift vital
        comfortably above the rest threshold, or None if none owned can do it. Used
        to decide whether a low-energy turn can be rescued into a training."""
        target = rest_threshold + margin
        owned: dict[int, int] = {}
        for row in (data.get("free_data_set") or {}).get("user_item_info_array") or []:
            iid = int(row.get("item_id") or 0)
            if iid in ENERGY_ITEM_VALUES:
                owned[iid] = owned.get(iid, 0) + int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
        best = None
        for iid, qty in owned.items():
            if qty > 0 and (any_owned or vital + ENERGY_ITEM_VALUES[iid] > target):
                if best is None or ENERGY_ITEM_VALUES[iid] < ENERGY_ITEM_VALUES[best]:
                    best = iid
        return ENERGY_ITEM_VALUES[best] if best is not None else None

    def _can_rescue_training(self, data, chara, preset, best, best_score, vital, failure, rest_threshold):
        """Spend a charm / energy item to RUN a strong training instead of resting it
        away for low energy or high failure? Only for a genuinely good turn (a rainbow
        or a high cap-aware score), only when energy isn't critically low, and only
        when we actually own the mitigation that can clear the blocker: an energy item
        big enough to beat the vital floor, or a charm/energy when only failure is high.
        Mirrors items/use.py _rescue_energy_target so the post-item re-decision agrees."""
        if not preset.get("rescue_good_training", True):
            return False
        if best is None or int(best.get("command_type") or 0) != 1:
            return False
        turn = int(chara.get("turn") or 0)
        late_turn = int(preset.get("late_aggressive_turn") or self.LATE_AGGRESSIVE_TURN)
        charm_count = self._owned_item_count(data, GOOD_LUCK_CHARM_ID)
        late_glc = turn >= late_turn and charm_count > 0 and failure >= (3 if charm_count >= 4 else 10 if charm_count == 3 else 16 if charm_count == 2 else 20)
        if (best_score is None or best_score <= 0) and turn < late_turn:
            return False
        if vital < int(preset.get("rescue_min_vital") or 25) and turn < late_turn:
            return False
        rainbow = self._rainbow_count(best, chara)
        strong = float(best_score or 0) >= float(preset.get("rescue_score_threshold") or 0.55)
        late_aggressive = turn >= late_turn
        if rainbow < 1 and not strong and not late_aggressive:
            return False
        margin = int(preset.get("rescue_vital_margin") or 12)
        energy_val = self._rescue_energy_value(data, vital, rest_threshold, margin, any_owned=turn >= late_turn)
        has_charm = charm_count > 0
        hard_cap = int(preset.get("failure_hard_cap") or 50)
        if failure >= hard_cap:
            if turn >= late_turn:
                return has_charm or energy_val is not None
            # Absolute failure ceiling: above the cap only a Good-Luck Charm (which forces
            # a verified 0%) may rescue the turn -- an energy bump does NOT guarantee the
            # failure drops below the cap, so we never gamble a high-intensity facility on
            # it. With no charm we rest instead. (A pro run was seen training at 99%.)
            return has_charm
        if vital <= rest_threshold:
            if turn >= late_turn:
                if energy_val is not None or late_glc:
                    return True
                return failure <= int(preset.get("late_uncovered_failure_rest") or self.LATE_UNCOVERED_FAILURE_REST)
            # only an energy item can lift vital back over the rest threshold
            return energy_val is not None
        if turn >= late_turn and failure <= int(preset.get("late_uncovered_failure_rest") or self.LATE_UNCOVERED_FAILURE_REST):
            return True
        if turn >= late_turn and failure > int(preset.get("late_uncovered_failure_rest") or self.LATE_UNCOVERED_FAILURE_REST):
            return energy_val is not None or late_glc
        if failure >= int(preset.get("high_failure_rest_threshold") or 35):
            # vital is fine, just the (possibly stale) failure is high -> charm/energy fixes it
            return has_charm or energy_val is not None
        return False
