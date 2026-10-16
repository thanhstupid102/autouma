from typing import TYPE_CHECKING

from career_bot.scenarios.mant.items.data import *
from career_bot.scenarios.mant.items.data import MantItemManagerState

if TYPE_CHECKING:
    # Type-only base: declares the manager state / sibling-mixin helpers this
    # mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class MantSummerMixin:` would produce.
    _HostState = MantItemManagerState
else:
    _HostState = object


class MantSummerMixin(_HostState):
    def _summer_hold_active(self, turn):
        return int(turn or 0) in SUMMER_HOLD_TURNS

    def _full_pre_summer_hold_active(self, turn):
        return int(turn or 0) in PRE_SUMMER_TURNS

    def _early_pre_summer_hold_active(self, turn):
        return int(turn or 0) in EARLY_PRE_SUMMER_TURNS

    def _summer_turn(self, turn):
        return int(turn or 0) in SUMMER_CAMP_TURNS

    def _deck_counts(self, preset):
        counts = (preset or {}).get("_deck_type_counts") or []
        return [int(counts[i] or 0) if len(counts) > i else 0 for i in range(5)]

    def _summer_ankle_target(self, name, preset):
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is None or not name.endswith("Ankle Weights"):
            return 0
        counts = self._deck_counts(preset)
        return 2 if type_idx < len(counts) and counts[type_idx] > 0 else 1

    def _summer_energy_charm_target(self, turn=None):
        return SUMMER_EARLY_ENERGY_CHARM_TARGET if self._early_pre_summer_hold_active(turn) else SUMMER_ENERGY_CHARM_TARGET

    def _summer_energy_charm_value(self, owned, turn=None):
        total = int(owned.get("Good-Luck Charm", 0) or 0) * 50
        for name, value in ENERGY_ITEMS.items():
            if name == "Royal Kale Juice":
                if self._early_pre_summer_hold_active(turn):
                    continue
                value = SUMMER_RKJ_STOCK_VALUE
            total += int(owned.get(name, 0) or 0) * value
        return total

    def _summer_reserved_energy_charm(self, owned, turn=None):
        reserved: dict[str, int] = {}
        value = 0
        target = self._summer_energy_charm_target(turn)
        for _ in range(int(owned.get("Good-Luck Charm", 0) or 0)):
            if value > target:
                break
            reserved["Good-Luck Charm"] = reserved.get("Good-Luck Charm", 0) + 1
            value += 50
        stock_values = {name: value for name, value in ENERGY_ITEMS.items() if name != "Royal Kale Juice"}
        if not self._early_pre_summer_hold_active(turn):
            stock_values["Royal Kale Juice"] = SUMMER_RKJ_STOCK_VALUE
        stock_order = ["Vita 65", "Vita 40", "Vita 20", "Royal Kale Juice"]
        for name in stock_order:
            if name not in stock_values:
                continue
            item_value = stock_values[name]
            for _ in range(int(owned.get(name, 0) or 0)):
                if value > target:
                    break
                reserved[name] = reserved.get(name, 0) + 1
                value += item_value
        return reserved

    def _summer_reserved_cupcakes(self, owned, turn=None):
        if not (self._full_pre_summer_hold_active(turn) or self._summer_turn(turn)):
            return {}
        return {
            name: min(int(owned.get(name, 0) or 0), target)
            for name, target in SUMMER_CUPCAKE_STOCK.items()
            if int(owned.get(name, 0) or 0) > 0
        }

    def _summer_reserved_megaphones(self, owned):
        reserved = {}
        need = SUMMER_MEGA_STOCK
        for name in MEGAPHONE_PRIORITY:
            take = min(int(owned.get(name, 0) or 0), need)
            if take > 0:
                reserved[name] = take
                need -= take
            if need <= 0:
                break
        return reserved

    def _summer_stock_item(self, name):
        return name in MEGAPHONE_TIERS or name in ENERGY_ITEMS or name == "Good-Luck Charm" or name == "Reset Whistle" or name in SUMMER_CUPCAKE_STOCK or str(name or "").endswith("Ankle Weights")

    def _summer_stock_needed(self, name, owned, preset, turn=None):
        if self._early_pre_summer_hold_active(turn):
            if name == "Royal Kale Juice":
                return False
            if name == "Good-Luck Charm" or name in ENERGY_ITEMS:
                return self._summer_energy_charm_value(owned, turn) <= self._summer_energy_charm_target(turn)
            return False
        if name == "Reset Whistle":
            return True
        if name == "Empowering Megaphone":
            return int(owned.get(name, 0) or 0) < SUMMER_MEGA_STOCK
        if name in MEGAPHONE_TIERS:
            return sum(int(owned.get(n, 0) or 0) for n in MEGAPHONE_TIERS) < SUMMER_MEGA_STOCK
        if name == "Good-Luck Charm" or name in ENERGY_ITEMS:
            return self._summer_energy_charm_value(owned, turn) <= self._summer_energy_charm_target(turn)
        if name in SUMMER_CUPCAKE_STOCK:
            return int(owned.get(name, 0) or 0) < SUMMER_CUPCAKE_STOCK[name]
        if str(name or "").endswith("Ankle Weights"):
            return int(owned.get(name, 0) or 0) < self._summer_ankle_target(name, preset)
        return False

    def _summer_reserved_items(self, owned, preset, turn):
        if not self._summer_hold_active(turn):
            return {}
        if self._early_pre_summer_hold_active(turn):
            return self._summer_reserved_energy_charm(owned, turn)
        reserved = self._summer_reserved_megaphones(owned)
        for name, count in self._summer_reserved_energy_charm(owned, turn).items():
            reserved[name] = max(reserved.get(name, 0), count)
        for name, count in self._summer_reserved_cupcakes(owned, turn).items():
            reserved[name] = max(reserved.get(name, 0), count)
        for name in TRAINING_TYPE_ANKLET.values():
            target = self._summer_ankle_target(name, preset)
            if target:
                reserved[name] = max(reserved.get(name, 0), min(int(owned.get(name, 0) or 0), target))
        if int(turn or 0) < SUMMER_ITEM_RELEASE_TURN:
            reserved["Reset Whistle"] = int(owned.get("Reset Whistle", 0) or 0)
        return reserved
