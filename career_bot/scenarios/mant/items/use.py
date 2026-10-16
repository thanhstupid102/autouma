import logging
from typing import TYPE_CHECKING

from career_bot.scenarios.mant.items.data import *
from career_bot.scenarios.mant.items.data import MantItemManagerState
from uma_api.errors import api_error_result_code

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Type-only base: declares the manager state / sibling-mixin helpers this
    # mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class MantUseMixin:` would produce.
    _HostState = MantItemManagerState
else:
    _HostState = object


class MantUseMixin(_HostState):
    def use_items(self, client, state, preset, best_command=None, status=None, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        current_turn = int(chara.get("turn") or 0)
        self._set_turn(current_turn)
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.use_attempt_events = []
        if not owned:
            self.last_use_result = {"skip": "no_owned"}
            return state, 0

        targets = self._collect_use_targets(
            state, data, chara, owned, preset, best_command, status, current_turn, race_planner)
        targets = self._cap_use_targets(self._merge_targets(targets, owned), owned, preset, current_turn)
        selected_names = {name for name, _ in targets}
        self.last_use_options = self._use_option_rows(owned, selected_names, current_turn, best_command)
        if not targets:
            self.last_use_result = {"skip": "no_targets"}
            return state, 0

        payload, valid_targets = self._use_payload(targets, owned)
        if not payload:
            self.last_use_result = {"skip": "empty_payload"}
            return state, 0

        self.last_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in valid_targets]
        self.last_use_attempt = list(payload)
        event = {
            "turn": current_turn,
            "selected": list(self.last_use_selected),
            "attempt": list(payload),
            "payload": list(payload),
            "result": {},
        }
        self.use_attempt_events.append(event)
        try:
            res = client.use_items(payload, current_turn)
            self._apply_use_success(valid_targets, payload, current_turn)
            event["result"] = self.last_use_result
            return self._merge_state(state, res), len(payload)
        except Exception as exc:
            self._apply_use_failure(exc, payload, current_turn)
            event["result"] = self.last_use_result
            return state, 0

    def _instant_use_targets(self, owned, preset, current_turn):
        """Everything in INSTANT_USE_ITEMS that is owned, unlocked, not already
        spent this career and not reserved for the summer camp."""
        targets = []
        for name in INSTANT_USE_ITEMS:
            qty = owned.get(name, 0)
            if qty <= 0:
                continue
            if name in TRAINING_APPLICATION_ITEMS and (not self._training_application_allowed(name) or name in self.used_buffs):
                continue
            if DISPLAY_TO_ID.get(name) in self.failed_use_this_turn:
                continue
            available_qty = self._available_to_use(name, owned, preset, current_turn)
            if available_qty <= 0:
                continue
            if name in ONE_TIME_BUFF_ITEMS:
                if name in self.used_buffs:
                    continue
                targets.append((name, 1))
            elif name in TRAINING_APPLICATION_ITEMS:
                targets.append((name, 1))
            else:
                targets.append((name, available_qty))
        return targets

    def _collect_use_targets(self, state, data, chara, owned, preset, best_command, status, current_turn, race_planner):
        """Every (name, count) this turn wants, before the merge/cap pass. A Reset
        Whistle is exclusive: it rerolls the turn, so nothing else is worth using."""
        targets = self._instant_use_targets(owned, preset, current_turn)

        carrot = self._grilled_carrot_target(data, owned, preset, current_turn)
        if carrot:
            targets.append(carrot)

        command_type = int((best_command or {}).get("command_type") or 0)
        is_race = command_type == 4
        energy_targets = [] if is_race else self._energy_targets(chara, owned, preset, best_command)
        targets.extend(energy_targets)
        rescue_targets = [] if is_race else self._rescue_energy_target(chara, owned, preset, best_command)
        targets.extend(rescue_targets)
        targets.extend(self._ailment_cure_targets(data, owned, current_turn))
        targets.extend(self._mood_targets(chara, owned, preset))

        whistle = self._whistle_target(state, best_command, owned, preset, status, current_turn)
        if whistle:
            return [whistle]
        # Vita-first, charm-fallback: if any energy item is already being used this
        # turn, it covers the failure -- only reach for the scarce charm otherwise.
        vita_covered = bool(energy_targets) or bool(rescue_targets)
        charm = self._charm_target(best_command, owned, preset, status, chara, vita_covered)
        if charm:
            targets.append(charm)
        mega = self._megaphone_target(state, best_command, owned, preset, status, current_turn, race_planner)
        if mega:
            targets.append(mega)
        anklet = self._anklet_target(state, best_command, owned, preset)
        if anklet:
            targets.append(anklet)
        return targets

    def _use_option_rows(self, owned, selected_names, current_turn, best_command):
        """The per-item audit rows the UI shows: every owned item, whether it was
        selected this turn, and why not when it wasn't."""
        rows = []
        for name, count in sorted(owned.items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or count <= 0:
                continue
            failed = item_id in self.failed_use_this_turn
            selected = name in selected_names and not failed
            reason = None if selected else ("failed_this_turn" if failed else "not_useful_now")
            rows.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "selected": selected,
                "skip_reason": reason,
                "reason": "selected" if selected else reason,
                "turn": current_turn,
                "context": {
                    "command_type": int((best_command or {}).get("command_type") or 0),
                    "command_id": int((best_command or {}).get("command_id") or 0),
                    "command_group_id": int((best_command or {}).get("command_group_id") or 0),
                },
            })
        return rows

    def _use_payload(self, targets, owned):
        """(payload, valid_targets) -- drops targets whose id is unknown, already
        failed this turn, or is no longer backed by enough stock."""
        payload = []
        valid_targets = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            have = int(owned.get(name) or 0)
            if have < count or have <= 0:
                continue

            valid_targets.append((name, count))
            payload.append({
                "item_id": item_id,
                "use_num": count,
                "current_num": have
            })
        return payload, valid_targets

    def _apply_use_success(self, valid_targets, payload, current_turn):
        self.failed_use_this_turn = set()
        for name, _ in valid_targets:
            if name in ONE_TIME_BUFF_ITEMS or name in TRAINING_APPLICATION_ITEMS:
                self.used_buffs.add(name)
            if name == self.first_shop_megaphone_to_use:
                self.first_shop_megaphone_to_use = None
        self.last_use_result = {"result": "ok", "turn": current_turn, "payload": payload}

    def _apply_use_failure(self, exc, payload, current_turn):
        log.warning(f"Item Use Error at turn {current_turn}: {exc}")
        if api_error_result_code(exc) in (201, 205, 208):
            # Optional item: skip the offender (mark failed-this-turn) and continue.
            # Only 208 loses the sid on this batch endpoint -> reload to resync;
            # 201/205 keep the sid synced and are safely skipped (no reload).
            for item in payload:
                self.failed_use_this_turn.add(int(item.get("item_id") or 0))
            if api_error_result_code(exc) == 208:
                self.recover_after_use_error = True
        self.last_use_result = {"result": "failed", "turn": current_turn, "error": str(exc), "payload": payload}

    def _is_instant_stat_item(self, name):
        slug = display_to_slug(name)
        return slug.endswith("_notepad") or slug.endswith("_manual") or slug.endswith("_scroll")

    def _mant_cfg(self, preset):
        cfg = dict((preset or {}).get("mant_config") or {})
        cfg.setdefault("item_tiers", DEFAULT_ITEM_TIERS)
        cfg.setdefault("tier_count", 8)
        cfg.setdefault("tier_thresholds", {"3": 31, "7": 100, "8": 99999999999})
        cfg.setdefault("charm_failure_rate", 30)
        cfg.setdefault("charm_min_stat", 27)
        cfg.setdefault("mega_small_threshold", 11)
        cfg.setdefault("mega_medium_threshold", 21)
        cfg.setdefault("mega_large_threshold", 35)
        cfg.setdefault("mega_late_buy_buffer", 5)
        cfg.setdefault("training_weights_threshold", 40)
        cfg.setdefault("pre_summer_tier", 2)
        cfg.setdefault("summer_raw_stat_target", SUMMER_RAW_STAT_TARGET)
        return cfg

    def _owned_map(self, free):
        result: dict[str, int] = {}
        for row in free.get("user_item_info_array") or []:
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if name:

                qty = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
                result[name] = result.get(name, 0) + qty
        return result

    def _available_to_use(self, name, owned, preset, turn, allow_reserved=False):
        qty = int(owned.get(name, 0) or 0)
        if qty <= 0:
            return 0
        if allow_reserved:
            return qty
        reserved = self._summer_reserved_items(owned, preset, turn).get(name, 0)
        return max(0, qty - int(reserved or 0))

    def _cap_use_targets(self, targets, owned, preset, turn):
        result = []
        for name, count in targets:
            allow_reserved = self._summer_turn(turn) and (
                name in ENERGY_ITEMS
                or name in MEGAPHONE_TIERS
                or name == "Good-Luck Charm"
                or name == "Reset Whistle"
                or name in SUMMER_CUPCAKE_STOCK
                or name.endswith("Ankle Weights")
            )
            limit = self._available_to_use(name, owned, preset, turn, allow_reserved=allow_reserved)
            use_num = min(int(count or 0), limit)
            if use_num > 0:
                result.append((name, use_num))
        return result

    def _active_bad_statuses(self, data):
        result = []
        for effect_id in (data.get("chara_info") or {}).get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name:
                result.append(name)
        return result

    def _deck_group_slots(self, chara):
        return {int(c.get("position") or 0) for c in (chara or {}).get("support_card_array") or [] if int(c.get("support_card_id") or 0) in GROUP_SUPPORT_IDS}

    def _bond_over_80_counts(self, chara, *, exclude_groups=False):
        groups = self._deck_group_slots(chara) if exclude_groups else set()
        slots = {int(c.get("position") or 0) for c in (chara or {}).get("support_card_array") or []}
        count = total = 0
        for row in (chara or {}).get("evaluation_info_array") or []:
            slot = int(row.get("target_id") or 0)
            if slot in slots and slot not in groups:
                total += 1
                count += int(row.get("evaluation") or 0) >= 80
        return count, total

    def _whistle_bond_gate(self, state, turn, preset=None):
        turn = int(turn or 0)
        if not self._summer_turn(turn) and turn < SUMMER_ITEM_RELEASE_TURN:
            return False
        chara = ((state or {}).get("data") or {}).get("chara_info") or {}
        if (preset or {}).get("two_pal_deck") is True:
            count, total = self._bond_over_80_counts(chara, exclude_groups=True)
            return total >= 4 and count >= 3
        count, total = self._bond_over_80_counts(chara)
        return total >= 6 and count >= 4

    def _is_charming_active(self, data):
        return any(int(eff.get("item_id") or 0) == CHARMING_ITEM_ID for eff in ((data or {}).get("free_data_set") or {}).get("item_effect_array") or [])

    def _grilled_carrot_gain(self, data):
        return 7 if self._is_charming_active(data) else 5

    def _grilled_carrot_target(self, data, owned, preset, turn):
        qty = int(owned.get("Grilled Carrots", 0) or 0)
        if qty <= 0:
            return None
        if self._is_charming_active(data):
            return ("Grilled Carrots", qty)
        chara = (data or {}).get("chara_info") or {}
        groups = self._deck_group_slots(chara)
        gain = self._grilled_carrot_gain(data)
        for row in chara.get("evaluation_info_array") or []:
            slot = int(row.get("target_id") or 0)
            bond = int(row.get("evaluation") or 0)
            if 1 <= slot <= 6 and slot not in groups and bond < 80 and bond + qty * gain > 80:
                return ("Grilled Carrots", qty)
        return None

    def _can_use_skin_or_miracle(self, turn):
        turn = int(turn or 0)
        return turn == TAKARAZUKA_YEAR2_TURN or turn >= SENIOR_INHERITANCE_DONE_TURN

    def _can_use_cure_now(self, name, data, turn):
        for ailment in self._active_bad_statuses(data or {}):
            if ailment != "Practice Poor" and AILMENT_CURE_MAP.get(ailment) == name:
                return name != "Rich Hand Cream" or self._can_use_skin_or_miracle(turn)
        return False

    def _training_application_allowed(self, name):
        return name in ALLOWED_TRAINING_APPLICATIONS

    def _ailment_cure_targets(self, data, owned, turn=0):
        result: list[tuple[str, int]] = []
        active_ailments = self._active_bad_statuses(data)
        if not active_ailments:
            return result

        unhandled_ailments = []
        for ailment in active_ailments:
            if ailment == "Practice Poor":
                continue
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) > 0:
                if cure == "Rich Hand Cream" and not self._can_use_skin_or_miracle(turn):
                    continue
                result.append((cure, 1))
            else:
                unhandled_ailments.append(ailment)

        if unhandled_ailments and owned.get(AILMENT_CURE_ALL, 0) > 0 and self._can_use_skin_or_miracle(turn):
            result.append((AILMENT_CURE_ALL, 1))
        return result

    def _energy_targets(self, chara, owned, preset, best_command=None):
        result: list[tuple[str, int]] = []
        hp = int(chara.get("vital") or 0)
        max_hp = int(chara.get("max_vital") or 100)
        gap = max_hp - hp
        if gap < 20:
            return result
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("energy_recovery_threshold") or 30)
        if hp > threshold:
            return result

        command_type = int((best_command or {}).get("command_type") or 0)
        low_train = command_type != 4 and hp < int((preset or {}).get("train_low_vital_rkj_threshold") or TRAIN_LOW_VITAL_RKJ_THRESHOLD)
        turn = int(chara.get("turn") or 0)
        if low_train and self._available_to_use("Royal Kale Juice", owned, preset, turn, allow_reserved=self._summer_turn(turn)) > 0:
            return [("Royal Kale Juice", 1)]

        candidates = []
        for name, value in ENERGY_ITEMS.items():
            if low_train and name != "Royal Kale Juice" and owned.get("Royal Kale Juice", 0) > 0:
                continue
            qty = self._available_to_use(name, owned, preset, turn, allow_reserved=self._summer_turn(turn))
            if qty > 0:
                candidates.append({"name": name, "value": value, "qty": qty})

        candidates.sort(key=lambda x: x["value"], reverse=True)

        remaining_gap = gap
        for c in candidates:
            if remaining_gap <= 5: break
            num_to_use = min(c["qty"], (remaining_gap + 5) // c["value"])
            if num_to_use > 0:
                result.append((c["name"], num_to_use))
                remaining_gap -= num_to_use * c["value"]

        return result

    def _rescue_energy_target(self, chara, owned, preset, best_command):
        """Top up energy with the smallest sufficient Vita so a STRONG training (the
        chosen best_command) can run this turn instead of being rested away for low
        energy. Mirrors MantStrategy._can_rescue_training so the post-item re-decision
        actually trains it. Very-low energy (<= reactive floor) is left to the normal
        _energy_targets; here we only handle the 'a bit too tired for a great turn' band."""
        if not (preset or {}).get("rescue_good_training", True):
            return []
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return []
        vital = int(chara.get("vital") or 0)
        cfg = self._mant_cfg(preset)
        reactive_floor = int(cfg.get("energy_recovery_threshold") or 30)
        if vital <= reactive_floor:
            return []  # reactive _energy_targets already refills critically low energy
        rest_threshold = int((preset or {}).get("rest_threshold") or 48)
        margin = int((preset or {}).get("rescue_vital_margin") or 12)
        target = rest_threshold + margin
        if vital >= target:
            return []  # already enough energy to train without resting
        failure = int(best_command.get("failure_rate") or 0)
        turn = int(chara.get("turn") or 0)
        # Mirror mant/rescue.py's failure hard-cap: above the cap an energy bump is NOT trusted to
        # clear the failure, so the energy rescue does not fire (only a charm may, via
        # _charm_target). Keeps this half in agreement with _can_rescue_training.
        if failure >= int((preset or {}).get("failure_hard_cap") or 50) and turn < SUMMER_ITEM_RELEASE_TURN:
            return []
        at_risk = vital <= rest_threshold or failure >= int(cfg.get("rescue_failure") or 30)
        if not at_risk:
            return []
        gain = self._command_stat_gain(best_command)
        rainbow = self._rainbow_count(best_command, chara)
        min_gain = 0 if turn >= SUMMER_ITEM_RELEASE_TURN else int(cfg.get("rescue_train_stat") or 27)
        if rainbow < 1 and gain < min_gain:
            return []
        best = None
        for name, value in ENERGY_ITEMS.items():
            if self._available_to_use(name, owned, preset, turn, allow_reserved=self._summer_turn(turn)) <= 0:
                continue
            if (turn >= SUMMER_ITEM_RELEASE_TURN or vital + value > target) and (best is None or value < ENERGY_ITEMS[best]):
                best = name
        return [(best, 1)] if best else []

    def _mood_targets(self, chara, owned, preset=None):
        motivation = int(chara.get("motivation") or 3)
        if motivation >= 5:
            return []

        needed = 5 - motivation

        turn = int(chara.get("turn") or 0)
        targets = []
        plain = self._available_to_use("Plain Cupcake", owned, preset, turn, allow_reserved=self._summer_turn(turn))
        berry = self._available_to_use("Berry Sweet Cupcake", owned, preset, turn, allow_reserved=self._summer_turn(turn))
        if berry > 0 and (motivation < 4 or plain <= 0):
            targets.append(("Berry Sweet Cupcake", 1))
            needed -= 2

        if plain > 0 and needed > 0:
            use_num = min(plain, needed)
            if use_num > 0:
                targets.append(("Plain Cupcake", use_num))

        return targets

    def _whistle_target(self, state, best_command, owned, preset, status, turn):
        if owned.get("Reset Whistle", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        if turn < SUMMER_ITEM_RELEASE_TURN and not self._whistle_bond_gate(state, turn, preset):
            return None

        score = self._command_stat_gain(best_command)
        cfg = self._mant_cfg(preset)
        if turn >= SUMMER_ITEM_RELEASE_TURN:
            if self._rainbow_count(best_command, (((state or {}).get("data") or {}).get("chara_info") or {})) < 1 and score < int(cfg.get("late_train_stat_target") or 20):
                 return ("Reset Whistle", 1)
            return None
        threshold = int(cfg.get("summer_raw_stat_target") or SUMMER_RAW_STAT_TARGET)
        if self._summer_turn(turn) and score < threshold:
             return ("Reset Whistle", 1)
        if turn >= SUMMER_ITEM_RELEASE_TURN and score < int(cfg.get("whistle_score_threshold") or 35) and turn <= 72:
             return ("Reset Whistle", 1)
        return None

    def _charm_target(self, best_command, owned, preset, status, chara=None, vita_covered=False):
        # Good-Luck Charm is a scarce item that forces 0% failure. Spend it ONLY on a
        # strong training whose failure a cheaper Vita can't cover -- the user's rule:
        # "good training + risky failure -> use Vita if it covers it, else the charm."
        turn = int((chara or {}).get("turn") or 0)
        charm_count = self._available_to_use("Good-Luck Charm", owned, preset, turn, allow_reserved=self._summer_turn(turn))
        if charm_count <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        fail_rate = int(best_command.get("failure_rate") or 0)
        cfg = self._mant_cfg(preset)
        threshold = (3 if charm_count >= 4 else 10 if charm_count == 3 else 16 if charm_count == 2 else 20) if turn >= SUMMER_ITEM_RELEASE_TURN else int(cfg.get("charm_failure_rate") or 30)
        if fail_rate < threshold:
            return None
        above_cap = fail_rate >= int((preset or {}).get("failure_hard_cap") or 50)
        # Vita-first before finale; late aggressive spends GLC by stock threshold even if energy also fires.
        if vita_covered and not above_cap and turn < SUMMER_ITEM_RELEASE_TURN:
            return None
        # Only worth a charm on a genuinely strong turn (a rainbow or a big stat gain),
        # not a mediocre training.
        if chara is not None and not above_cap:
            rainbow = self._rainbow_count(best_command, chara)
            gain = self._command_stat_gain(best_command)
            min_gain = 0 if turn >= SUMMER_ITEM_RELEASE_TURN else int(cfg.get("charm_min_stat") or 27)
            if rainbow < 1 and gain < min_gain:
                return None
        return ("Good-Luck Charm", 1)

    def _megaphone_target(self, state, best_command, owned, preset, status, turn, race_planner):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        data = state.get("data") or {}
        current_mega_tier = self._active_megaphone_tier(state)
        if current_mega_tier > 0:
            return None
        if self.first_shop_megaphone_to_use and self._available_to_use(self.first_shop_megaphone_to_use, owned, preset, turn, allow_reserved=True) > 0:
            return (self.first_shop_megaphone_to_use, 1)

        score = self._command_stat_gain(best_command, sp_weight=0 if self._summer_turn(turn) else 0.5)
        cfg = self._mant_cfg(preset)
        tiers = self._megaphone_score_thresholds(cfg)
        # Computed unconditionally, exactly where the original did: the pressure
        # probes reach into race_planner, so their call position is behaviour.
        pressure = self._megaphone_pressure(data, owned, turn, race_planner, preset)

        if current_mega_tier <= 0:
            pick, target_tier = self._megaphone_fresh_target(
                score, owned, preset, turn, cfg, tiers, pressure, current_mega_tier)
            if pick:
                return pick
        else:
            target_tier = self._megaphone_active_tier_target(current_mega_tier, score, tiers)

        return self._megaphone_upgrade_pick(target_tier, current_mega_tier, owned, preset, turn)

    def _megaphone_score_thresholds(self, cfg):
        """(small, medium, large) training-score gates of the megaphone ladder."""
        return (
            float(cfg.get("mega_small_threshold") or 11),
            float(cfg.get("mega_medium_threshold") or 21),
            float(cfg.get("mega_large_threshold") or 35),
        )

    def _megaphone_pressure(self, data, owned, turn, race_planner, preset):
        """(dump_mode, inventory_pressure, has_upgrade_pair) -- the stock-vs-slots
        signals that make the ladder spend a megaphone it would otherwise hold."""
        dump_mode = self._megaphone_dump_mode(data, owned, turn, race_planner, preset)
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        owned_count = self._owned_megaphone_count(owned)
        inventory_pressure = slots_left > 0 and owned_count >= slots_left
        has_upgrade_pair = owned.get("Motivating Megaphone", 0) > 0 and owned.get("Empowering Megaphone", 0) > 0 and slots_left >= 2
        return dump_mode, inventory_pressure, has_upgrade_pair

    def _megaphone_fresh_target(self, score, owned, preset, turn, cfg, tiers, pressure, current_mega_tier):
        """The no-active-megaphone ladder. Returns (pick, target_tier): a pick is
        final; a target_tier instead feeds the shared upgrade fallback."""
        dump_mode, inventory_pressure, has_upgrade_pair = pressure
        if self._summer_turn(turn):
            return self._megaphone_summer_target(score, owned, preset, turn, cfg, current_mega_tier), 0
        if turn >= SUMMER_ITEM_RELEASE_TURN:
            pick = self._megaphone_priority_pick(owned, preset, turn)
            if pick:
                return pick, 0
        pick = self._megaphone_score_pick(score, owned, preset, turn, tiers, has_upgrade_pair)
        if pick:
            return pick, 0
        if inventory_pressure or dump_mode:
            return self._megaphone_dump_pick(score, owned, preset, turn, tiers, has_upgrade_pair), 0
        return None, self._megaphone_tier_from_score(score, tiers)

    def _megaphone_priority_pick(self, owned, preset, turn, allow_reserved=False):
        """Best available megaphone in MEGAPHONE_PRIORITY order."""
        for name in MEGAPHONE_PRIORITY:
            if self._available_to_use(name, owned, preset, turn, allow_reserved=allow_reserved) > 0:
                return (name, 1)
        return None

    def _megaphone_summer_target(self, score, owned, preset, turn, cfg, current_mega_tier):
        if current_mega_tier > 0 or score < float(cfg.get("summer_raw_stat_target") or SUMMER_RAW_STAT_TARGET):
            return None
        return self._megaphone_priority_pick(owned, preset, turn, allow_reserved=True)

    def _megaphone_score_pick(self, score, owned, preset, turn, tiers, has_upgrade_pair):
        """Spend a megaphone the training score has genuinely earned."""
        small_threshold, medium_threshold, large_threshold = tiers
        if has_upgrade_pair and score >= medium_threshold and self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if score >= large_threshold and self._available_to_use("Empowering Megaphone", owned, preset, turn) > 0:
            return ("Empowering Megaphone", 1)
        if score >= medium_threshold and self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if score >= small_threshold and self._available_to_use("Coaching Megaphone", owned, preset, turn) > 0:
            return ("Coaching Megaphone", 1)
        return None

    def _megaphone_dump_pick(self, score, owned, preset, turn, tiers, has_upgrade_pair):
        """More megaphones than training turns left -- spend one regardless of score."""
        small_threshold, medium_threshold, _large_threshold = tiers
        if has_upgrade_pair and self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if self._available_to_use("Empowering Megaphone", owned, preset, turn) > 0:
            return ("Empowering Megaphone", 1)
        if score >= medium_threshold and self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if score >= small_threshold and self._available_to_use("Coaching Megaphone", owned, preset, turn) > 0:
            return ("Coaching Megaphone", 1)
        if self._available_to_use("Coaching Megaphone", owned, preset, turn) > 0:
            return ("Coaching Megaphone", 1)
        if self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if self._available_to_use("Empowering Megaphone", owned, preset, turn) > 0:
            return ("Empowering Megaphone", 1)
        return None

    def _megaphone_tier_from_score(self, score, tiers):
        small_threshold, medium_threshold, large_threshold = tiers
        if score >= large_threshold:
            return 3
        if score >= medium_threshold:
            return 2
        if score >= small_threshold:
            return 1
        return 0

    def _megaphone_active_tier_target(self, current_mega_tier, score, tiers):
        """Upgrade ladder for a megaphone that is ALREADY active.

        NOTE: unreachable today -- _megaphone_target returns None as soon as
        _active_megaphone_tier() is non-zero, so this branch of the original
        if/elif chain never ran. Transcribed verbatim rather than deleted.
        """
        _small_threshold, medium_threshold, large_threshold = tiers
        if current_mega_tier == 1:
            if score >= large_threshold * 1.2:
                return 3
            if score >= medium_threshold * 1.1:
                return 2
        elif current_mega_tier == 2:
            if score >= large_threshold * 1.1:
                return 3
        return 0

    def _megaphone_upgrade_pick(self, target_tier, current_mega_tier, owned, preset, turn):
        """Highest megaphone at or below target_tier that is actually in stock."""
        if target_tier >= 3 and current_mega_tier < 3 and self._available_to_use("Empowering Megaphone", owned, preset, turn) > 0:
            return ("Empowering Megaphone", 1)
        if target_tier >= 2 and current_mega_tier < 2 and self._available_to_use("Motivating Megaphone", owned, preset, turn) > 0:
            return ("Motivating Megaphone", 1)
        if target_tier >= 1 and current_mega_tier < 1 and self._available_to_use("Coaching Megaphone", owned, preset, turn) > 0:
            return ("Coaching Megaphone", 1)

        return None

    def _megaphone_dump_mode(self, data, owned, turn, race_planner, preset):
        training_turns_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        total_duration = 0
        for name, (_, duration) in MEGAPHONE_TIERS.items():
            total_duration += int(owned.get(name, 0) or 0) * duration
        return training_turns_left > 0 and total_duration >= training_turns_left

    def _owned_megaphone_count(self, owned):
        total = 0
        for name in MEGAPHONE_TIERS:
            total += int(owned.get(name, 0) or 0)
        return total

    def _megaphone_buy_surplus(self, data, owned, turn, race_planner, preset):
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        if slots_left <= 0:
            return False
        cfg = self._mant_cfg(preset)
        buffer = int(cfg.get("mega_late_buy_buffer") or 3)
        target = max(0, slots_left - buffer)
        return self._owned_megaphone_count(owned) >= target

    def _remaining_megaphone_slots(self, data, turn, race_planner, preset):
        return self._remaining_training_turns_to_77(data, turn, race_planner, preset)

    def _remaining_training_turns_to_77(self, data, turn, race_planner, preset):
        planned_race_turns = self._planned_race_turns_to_77(data, turn, race_planner, preset)
        remaining = 0
        for t in range(int(turn or 0), 77):
            if t in (74, 76):
                continue
            if t not in planned_race_turns:
                remaining += 1
        return remaining

    def _planned_race_turns_to_77(self, data, turn, race_planner, preset):
        current_turn = int(turn or 0)
        wanted_pids = set()
        if race_planner and preset:
            wanted_pids = race_planner.wanted_programs(preset)
        result = set()
        for item in data.get("race_condition_array") or []:
            item_turn = int(item.get("turn") or 0)
            program_id = int(item.get("program_id") or 0)
            if item_turn >= current_turn and item_turn < 77 and (not wanted_pids or program_id in wanted_pids):
                result.add(item_turn)
        if race_planner and wanted_pids:
            for program_id in wanted_pids:
                info = (race_planner.program or {}).get(int(program_id or 0)) or {}
                race_turn = self._program_turn_from_month_half(info, current_turn)
                if race_turn >= current_turn and race_turn < 77:
                    result.add(race_turn)
        return result

    def _program_turn_from_month_half(self, program_info, current_turn):
        month = int((program_info or {}).get("month") or 0)
        half = int((program_info or {}).get("half") or 0)
        if month <= 0 or half <= 0:
            return 0
        base_turn = (month - 1) * 2 + half
        candidates = [base_turn + 24 * year for year in range(4)]
        for candidate in candidates:
            if candidate >= int(current_turn or 0):
                return candidate
        return candidates[-1]

    def _anklet_target(self, state, best_command, owned, preset):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        cmd_id = int(best_command.get("command_id") or 0)
        anklet = TRAINING_TYPE_ANKLET.get(cmd_id)
        turn = int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
        if not anklet or self._available_to_use(anklet, owned, preset, turn, allow_reserved=self._summer_turn(turn)) <= 0:
            return None

        data = state.get("data") or {}
        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        for eff in item_effects:
            if eff.get("item_id") in (9001, 9002, 9003, 9004, 9005):
                return None

        score = self._command_stat_gain(best_command, sp_weight=0 if self._summer_turn(turn) else 0.5)
        threshold = (0 if turn >= SUMMER_ITEM_RELEASE_TURN else float((self._mant_cfg(preset)).get("summer_raw_stat_target") or SUMMER_RAW_STAT_TARGET)
                     if self._summer_turn(turn) else 30 * (1 - (0.2 * self._active_megaphone_tier(state))))
        if turn >= SUMMER_ITEM_RELEASE_TURN:
            threshold = 0
        if score >= threshold:
            return (anklet, 1)
        return None

    def _active_megaphone_tier(self, state):
        current_mega_tier = 0
        for eff in ((state.get("data") or {}).get("free_data_set") or {}).get("item_effect_array") or []:
            item_id = eff.get("item_id")
            if item_id == 8001: current_mega_tier = max(current_mega_tier, 1)
            elif item_id == 8002: current_mega_tier = max(current_mega_tier, 2)
            elif item_id == 8003: current_mega_tier = max(current_mega_tier, 3)
        return current_mega_tier

    def _rainbow_count(self, command, chara):
        """Deck supports at max bond (>=80) present on this training = rainbows.
        Used to recognise a 'good training' worth spending a Vita/charm to run."""
        if not command or not chara:
            return 0
        bonds = {}
        for row in chara.get("evaluation_info_array") or []:
            bonds[int(row.get("target_id") or 0)] = int(row.get("evaluation") or 0)
        count = 0
        for pid in command.get("training_partner_array") or []:
            pid = int(pid or 0)
            if pid in {1, 2, 3, 4, 5, 6} and bonds.get(pid, 0) >= 80:
                count += 1
        return count

    def _command_stat_gain(self, cmd, sp_weight=0):
        if not cmd: return 0
        total = 0
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            if tt in [1, 2, 3, 4, 5]:
                total += int(item.get("value") or 0)
            elif (tt == 6 or tt == 30) and sp_weight > 0:
                total += int(item.get("value") or 0) * sp_weight
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(cmd.get(field) or 0)
            if sp_weight > 0:
                total += int(cmd.get("lp") or cmd.get("skill_point") or 0) * sp_weight
        return total

    def _merge_targets(self, targets, owned):
        counts: dict[str, int] = {}
        for name, count in targets:
            counts[name] = counts.get(name, 0) + count
        result = []
        for name, count in counts.items():
            actual = min(count, owned.get(name, 0))
            if actual > 0:
                result.append((name, actual))
        return result

    def _pre_summer_boost_tier(self, name, owned, cfg, preset=None, turn=None):
        """During the pre-camp window, give summer-prep items that are still under their
        target owned-count a high buy priority (low tier number) so the Lv5 camp turns are
        stocked. Returns the boosted tier, or None for items not being stockpiled. All
        targets are tunable via mant_config."""
        tier = int(cfg.get("pre_summer_tier") or 2)
        if self._early_pre_summer_hold_active(turn):
            if (name == "Good-Luck Charm" or name in ENERGY_ITEMS) and self._summer_stock_needed(name, owned, preset, turn):
                return tier
            return None
        if name == "Empowering Megaphone" and owned.get(name, 0) < SUMMER_MEGA_STOCK:
            return tier
        if name in MEGAPHONE_TIERS and sum(int(owned.get(n, 0) or 0) for n in MEGAPHONE_TIERS) < SUMMER_MEGA_STOCK:
            return tier
        if name == "Good-Luck Charm" and self._summer_energy_charm_value(owned, turn) <= self._summer_energy_charm_target(turn):
            return tier
        if name in ENERGY_ITEMS and self._summer_energy_charm_value(owned, turn) <= self._summer_energy_charm_target(turn):
            return tier
        if name in SUMMER_CUPCAKE_STOCK and owned.get(name, 0) < SUMMER_CUPCAKE_STOCK[name]:
            return tier
        if name.endswith("Ankle Weights") and owned.get(name, 0) < self._summer_ankle_target(name, preset):
            return tier
        if name == "Reset Whistle":
            return tier
        return None
