import logging
from typing import TYPE_CHECKING, Any, NamedTuple

from career_bot.scenarios.mant.items.data import *
from career_bot.scenarios.mant.items.data import MantItemManagerState, _coin_turn_bucket
from uma_api.errors import api_error_result_code

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Type-only base: declares the manager state / sibling-mixin helpers this
    # mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class MantShopMixin:` would produce.
    _HostState = MantItemManagerState
else:
    _HostState = object


class _ShopShifts(NamedTuple):
    """Deck- and inventory-derived tier adjustments for one shop visit.

    A value type, not a collaborator: it exists only so the effective-tier
    helpers can take one readable parameter instead of the seven locals
    `buy_shop_items` used to thread by hand.
    """

    deck_counts: Any
    bbq_shift: int
    charm_owned: int
    charm_stop: bool
    cupcake_shift: int
    active_ailments: Any
    has_miracle: bool


class MantShopMixin(_HostState):
    def buy_shop_items(self, client, state, preset, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        pickups = free.get("pick_up_item_info_array") or []
        self._set_turn(current_turn)
        self._set_shop_snapshot(pickups)
        cfg = self._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or DEFAULT_ITEM_TIERS
        tier_count = int(cfg.get("tier_count") or 8)
        budget = self._coin_budget(free)
        start_budget = budget
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {"mant_coin": budget}
        self.buy_attempt_events = []
        if not pickups:
            self.last_buy_result = {"skip": "no_pickups", "mant_coin": budget}
            return state, 0
        if budget <= 0:
            self.last_buy_result = {"skip": "no_mant_coin", "mant_coin": budget}
            return state, 0

        owned = self._owned_map(free)
        any_sale = any(int(row.get("coin_num") or 0) < int(row.get("original_coin_num") or 0) for row in pickups if int(row.get("original_coin_num") or 0) > 0)
        sale_modifier = 0.9 if any_sale else 1.0
        shifts = self._shop_priority_shifts(data, chara, owned, preset, cfg, current_turn)

        available, self.last_buy_options = self._shop_available_rows(
            pickups, owned, preset, current_turn, start_budget, data, race_planner)

        if not available:
            self.last_buy_result = {"skip": "no_available", "mant_coin": budget}
            return state, 0

        miracle_available = any(name == AILMENT_CURE_ALL for name, _ in available)

        pre_summer = bool(preset.get("pre_summer_stock", True)) and current_turn in (cfg.get("pre_summer_window") or SUMMER_HOLD_TURNS)
        projected_owned = dict(owned)
        effective_rows = self._shop_effective_rows(
            available, tiers, shifts, owned, projected_owned, preset, cfg, current_turn, pre_summer)

        targets: list[Any] = []
        selected_ids: set[int] = set()
        budget = self._shop_take_first_megaphone(available, budget, targets, selected_ids)

        for tier in range(1, tier_count + 1):
            tier_rows = [(name, row) for eff_t, name, row in effective_rows if eff_t == tier and id(row) not in selected_ids]
            tier_rows.sort(key=lambda item: self._buy_sort_key(item[0], item[1], pre_summer))
            for name, row in tier_rows:
                if self._shop_row_blocked(name, projected_owned, preset, data, current_turn, pre_summer, miracle_available):
                    continue
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                remaining = budget - cost
                if remaining < 0:
                    continue
                threshold = self._tier_threshold(tier, current_turn, cfg, sale_modifier)
                floor = self._buy_floor(name, tier, current_turn, start_budget, budget, threshold, cfg)
                if remaining < floor:
                    continue
                targets.append(row)
                selected_ids.add(id(row))
                budget = remaining
                projected_owned[name] = projected_owned.get(name, 0) + 1

        if not targets:
            self.last_buy_result = {"skip": "no_targets", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        self.last_buy_selected = [{
            "name": ITEM_NAMES.get(int(row.get("item_id") or 0), ""),
            "item_id": int(row.get("item_id") or 0),
            "shop_item_id": int(row.get("shop_item_id") or 0),
            "cost": int(row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(row.get("item_id") or 0), ""), 9999)),
            "current_num": int(row.get("item_buy_num") or 0),
            "limit_turn": int(row.get("limit_turn") or 0),
        } for row in targets]

        payload = self._shop_exchange_payload(targets)

        if not payload:
            self.last_buy_result = {"skip": "empty_payload", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        return self._exchange_batch(client, state, payload, current_turn)

    def _coin_budget(self, free):
        """MANT coin held in `free`, tolerating both field names the server uses."""
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        return int(coin_val or 0)

    def _shop_priority_shifts(self, data, chara, owned, preset, cfg, current_turn):
        """Deck/inventory signals that reorder the shop tiers for this visit."""
        # Per-stat support-card counts [Speed, Stamina, Power, Guts, Wit] of the running
        # deck -- used to prioritize stat-specific shop items toward the deck's focus.
        deck_counts = preset.get("_deck_type_counts") or []
        motivation = int(chara.get("motivation") or 3)
        non_rainbow_count = 0
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) in {1, 2, 3, 4, 5, 6} and int(row.get("evaluation") or 0) < 80:
                non_rainbow_count += 1
        bbq_threshold = int(cfg.get("bbq_unmaxxed_cards") or 3)
        bbq_shift = non_rainbow_count - bbq_threshold
        charm_owned = owned.get("Good-Luck Charm", 0)
        is_senior_or_later = current_turn > 48
        charm_stop_qty = 3 if current_turn >= SUMMER_ITEM_RELEASE_TURN else 99
        charm_stop = charm_owned >= charm_stop_qty
        cupcake_names = {"Plain Cupcake", "Berry Sweet Cupcake"}
        total_cupcakes = sum(owned.get(n, 0) for n in cupcake_names)
        skip_cupcakes = total_cupcakes >= 2 or (is_senior_or_later and total_cupcakes >= 1) or motivation >= 5
        cupcake_shift = total_cupcakes - 1 if skip_cupcakes else 0
        active_ailments = self._active_bad_statuses(data)
        has_miracle = owned.get("Miracle Cure", 0) > 0
        return _ShopShifts(deck_counts, bbq_shift, charm_owned, charm_stop, cupcake_shift,
                           active_ailments, has_miracle)

    def _shop_available_rows(self, pickups, owned, preset, current_turn, start_budget, data, race_planner):
        """(available, option_rows) -- the buyable subset of this shop snapshot,
        plus the per-row audit trail incl. why each rejected row was rejected."""
        available = []
        option_rows = []
        for row in pickups:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
            limit_turn = int(row.get("limit_turn") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            current_num = int(row.get("item_buy_num") or 0)
            skip_reason = None
            if shop_item_id <= 0 or shop_item_id in self.failed_exchange_this_snapshot:
                skip_reason = "failed_snapshot"
            elif limit_turn > 0 and limit_turn < current_turn:
                skip_reason = "expired"
            elif current_num >= limit:
                skip_reason = "limit_reached"
            elif self._skip_buy(name, owned, preset, current_turn, start_budget, data, race_planner):
                skip_reason = "skip_buy"
            option_rows.append({
                "name": name,
                "item_id": item_id,
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": current_num,
                "limit": limit,
                "limit_turn": limit_turn,
                "turns_left": (limit_turn - current_turn) if limit_turn > 0 else None,
                "skip_reason": skip_reason,
            })
            if not skip_reason:
                available.append((name, row))
        return available, option_rows

    def _shop_effective_rows(self, available, tiers, shifts, owned, projected_owned, preset, cfg, current_turn, pre_summer):
        """(effective_tier, name, row) for every available row, lowest tier = buy first."""
        effective_rows = []
        for name, row in available:
            slug = display_to_slug(name)
            base_t = int(tiers.get(slug) or 999)
            eff_t = self._shop_cure_tier(name, slug, base_t, shifts, owned)
            eff_t = self._shop_shift_tier(name, slug, base_t, eff_t, shifts, preset)
            if pre_summer:
                boost = self._pre_summer_boost_tier(name, projected_owned, cfg, preset, current_turn)
                if boost is not None:
                    eff_t = min(eff_t, boost)
            effective_rows.append((max(1, eff_t), name, row))
        return effective_rows

    def _shop_cure_tier(self, name, slug, base_t, shifts, owned):
        """Escalate a cure to tier 1 while its ailment is active and unstocked."""
        eff_t = base_t
        for ailment in shifts.active_ailments:
            specific_cure = AILMENT_CURE_MAP.get(ailment)
            if specific_cure and name == specific_cure and not shifts.has_miracle and owned.get(name, 0) <= 0:
                eff_t = 1
        if slug == "miracle_cure" and shifts.active_ailments and not shifts.has_miracle:
            eff_t = 1
        if (slug == "miracle_cure" or slug == "rich_hand_cream") and owned.get(name, 0) <= 0:
            eff_t = 1
        return eff_t

    def _shop_shift_tier(self, name, slug, base_t, eff_t, shifts, preset):
        """Stock- and deck-driven ordering shifts layered on the base tier."""
        if slug == "grilled_carrots":
            eff_t = min(eff_t, base_t - shifts.bbq_shift)
        elif slug == "good-luck_charm":
            eff_t = 999 if shifts.charm_stop else min(eff_t, base_t - shifts.charm_owned)
        elif slug in {"plain_cupcake", "berry_sweet_cupcake"}:
            eff_t = min(eff_t, base_t - shifts.cupcake_shift)
        elif name in TRAINING_ITEM_DECK_TYPE_INDEX:
            # Deck-match priority: a stat item (Ankle Weights / Training Application)
            # whose stat the deck is built around gets a higher priority (lower tier)
            # than a borderline secondary stat. So a Speed-heavy deck (4 cards) buys
            # Speed Ankle Weights before Power ones (2 cards), instead of treating all
            # stat items at the same tier. Items for stats with < min cards were
            # already dropped by _skip_buy, so this only orders the ones worth buying.
            if preset.get("deck_match_stat_items", True):
                type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
                deck_counts = shifts.deck_counts
                dc = int(deck_counts[type_idx]) if (deck_counts and type_idx is not None and 0 <= type_idx < len(deck_counts)) else 0
                bump = max(0, dc - int(preset.get("deck_match_min_count") or 2))
                eff_t = max(1, base_t - bump)
        return eff_t

    def _shop_take_first_megaphone(self, available, budget, targets, selected_ids):
        """Guarantee one megaphone out of the career's first shop, ahead of the tier
        ladder. Appends into `targets`/`selected_ids`; returns the budget left."""
        first_mega = self._first_shop_megaphone_candidate(available)
        if first_mega:
            first_mega_name, first_mega_row = first_mega
            cost = int(first_mega_row.get("coin_num") or SHOP_ITEM_COSTS.get(first_mega_name, 9999))
            if cost <= budget:
                targets.append(first_mega_row)
                selected_ids.add(id(first_mega_row))
                budget -= cost
                self.first_shop_megaphone_done = True
                self.first_shop_megaphone_to_use = first_mega_name
        return budget

    def _shop_row_blocked(self, name, projected_owned, preset, data, current_turn, pre_summer, miracle_available):
        """Content gates a tier row must clear before its cost is weighed at all."""
        if pre_summer and self._summer_stock_item(name) and not (self._early_pre_summer_hold_active(current_turn) and name == "Royal Kale Juice") and not self._summer_stock_needed(name, projected_owned, preset, current_turn):
            return True
        if name in {AILMENT_CURE_ALL, "Rich Hand Cream"} and int(projected_owned.get(name, 0) or 0) >= 2:
            return True
        if name in CURE_ITEMS - {AILMENT_CURE_ALL, "Rich Hand Cream"} and (miracle_available or projected_owned.get(AILMENT_CURE_ALL, 0) > 0 or not self._can_use_cure_now(name, data, current_turn)):
            return True
        return False

    def _tier_threshold(self, tier, current_turn, cfg, sale_modifier):
        """Coin a tier-N purchase must leave behind, before _buy_floor relaxes it."""
        threshold = 0
        thresholds = cfg.get("tier_thresholds") or {}
        if tier > 1 and current_turn <= 64:
            raw_threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
            threshold = int(raw_threshold * sale_modifier)
        return threshold

    def _shop_exchange_payload(self, targets):
        payload = []
        for row in targets:
            sid = int(row.get("shop_item_id") or 0)
            if sid > 0 and sid not in self.failed_exchange_this_snapshot:
                payload.append({"shop_item_id": sid, "current_num": 0})
        return payload

    def _item_inventory_cap(self, item_id):
        return 2 if ITEM_NAMES.get(int(item_id or 0)) in {AILMENT_CURE_ALL, "Rich Hand Cream"} else 5

    def _ensure_local_exchange_applied(self, state, shop_item_id, item_id, cost, before_num, before_buy_num, before_coin):
        data = state.setdefault("data", {})
        free = data.setdefault("free_data_set", {})

        coin_key = "coin_num" if free.get("coin_num") is not None else "gained_coin_num"
        if free.get(coin_key) is not None and int(free.get(coin_key) or 0) >= before_coin:
            free[coin_key] = max(0, before_coin - cost)

        rows = free.setdefault("user_item_info_array", [])
        for row in rows:
            if int(row.get("item_id") or 0) == item_id:
                current = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
                if current <= before_num:
                    row["num"] = before_num + 1
                break
        else:
            rows.append({"item_id": item_id, "num": before_num + 1})

        for row in free.get("pick_up_item_info_array") or []:
            if int(row.get("shop_item_id") or 0) == shop_item_id:
                current = int(row.get("item_buy_num") or 0)
                if current <= before_buy_num:
                    row["item_buy_num"] = before_buy_num + 1
                break

    def _exchange_batch(self, client, state, payload, current_turn):
        if not payload:
            return state, 0

        current = self._refresh_before_exchange(client, state, current_turn)

        data = current.get("data") or {}
        chara = data.get("chara_info") or {}
        source_turn = int(chara.get("turn") or 0)
        if source_turn != current_turn:
            self.last_buy_result = {"skip": "stale_turn_detected", "request_current_turn": current_turn, "source_state_turn": source_turn}
            return current, 0

        free = data.get("free_data_set") or {}
        budget = self._coin_budget(free)
        valid_entries = self._exchange_preflight(free, payload, current_turn, budget)

        if not valid_entries:
            self.last_buy_result = {"skip": "preflight_failed", "mant_coin": budget}
            return current, 0

        rounds = self._split_exchange_rounds(valid_entries)
        self.last_buy_attempt = [dict(entry["payload"]) for entry in valid_entries]
        return self._run_exchange_rounds(client, current, rounds, current_turn, budget)

    def _refresh_before_exchange(self, client, state, current_turn):
        """Best-effort re-read so current_num/coin are the server's and not ours.
        A refresh that landed on a different turn is discarded, never merged."""
        current = state
        if hasattr(client, "load_career"):
            try:
                refreshed = client.load_career()
                refreshed_turn = int((((refreshed or {}).get("data") or {}).get("chara_info") or {}).get("turn") or 0)
                if refreshed_turn == current_turn:
                    current = self._merge_state(current, refreshed)
            except Exception as exc:
                log.warning(f"Item exchange refresh failed at turn {current_turn}: {exc}")
                pass
        return current

    def _requested_shop_ids(self, payload):
        """Requested shop_item_ids in request order, deduplicated."""
        requested_shop_ids = []
        seen = set()
        for item in payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id > 0 and shop_item_id not in seen:
                requested_shop_ids.append(shop_item_id)
                seen.add(shop_item_id)
        return requested_shop_ids

    def _exchange_preflight(self, free, payload, current_turn, start_budget):
        """Re-validate every requested shop row against the freshly-read state:
        expiry, per-shop buy limit, running affordability and the inventory cap.
        Each survivor carries the exact payload/attempt dicts the round will send."""
        valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}
        owned_by_id = {}
        for row in free.get("user_item_info_array") or []:
            owned_by_id[int(row.get("item_id") or 0)] = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)

        requested_shop_ids = self._requested_shop_ids(payload)

        valid_entries: list[dict[str, Any]] = []
        projected_owned = dict(owned_by_id)
        total_cost = 0
        for shop_item_id in requested_shop_ids:
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            item_id = int(shop_row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id, "")
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
            limit_turn = int(shop_row.get("limit_turn") or 0)
            before_buy_num = int(shop_row.get("item_buy_num") or 0)
            if limit_turn > 0 and limit_turn < current_turn:
                continue
            if before_buy_num >= int(shop_row.get("limit_buy_count") or 1):
                continue
            if total_cost + cost > start_budget:
                continue
            current_num = int(projected_owned.get(item_id, 0) or 0)
            if current_num >= self._item_inventory_cap(item_id):
                continue

            valid_entries.append({
                "shop_item_id": shop_item_id,
                "item_id": item_id,
                "cost": cost,
                "current_num": current_num,
                "before_buy_num": before_buy_num,
                "payload": {"shop_item_id": shop_item_id, "current_num": current_num},
                "attempt": {"shop_item_id": shop_item_id, "item_id": item_id, "cost": cost, "current_num": current_num},
            })
            projected_owned[item_id] = current_num + 1
            total_cost += cost
        return valid_entries

    def _run_exchange_rounds(self, client, current, rounds, current_turn, before_coin):
        """Send each duplicate-free round in order; the first round that still
        errors after its per-item retry stops the whole exchange."""
        bought = 0
        all_payload = []
        for round_entries in rounds:
            round_payload = [dict(entry["payload"]) for entry in round_entries]
            round_attempt = [dict(entry["attempt"]) for entry in round_entries]
            all_payload.extend(round_payload)
            event = {
                "turn": current_turn,
                "selected": list(self.last_buy_selected),
                "attempt": round_attempt,
                "payload": round_payload,
                "result": {},
            }
            self.buy_attempt_events.append(event)
            current, round_bought, before_coin, err = self._exchange_entries(
                client, current, round_entries, current_turn, before_coin)
            bought += round_bought
            if err is None:
                event["result"] = {"result": "ok", "turn": current_turn, "payload": round_payload, "bought": round_bought}
            else:
                # Per-item retry already salvaged the buyable items in this round; the
                # offender(s) are marked and recover_after_exchange_error is set, so the
                # runner reloads career state. Stop here (like the original flow) rather
                # than exchanging more against a state the server just rejected.
                self.last_buy_result = {"result": "ok" if bought else "failed", "turn": current_turn,
                                        "error": str(err), "payload": all_payload, "bought": bought}
                event["result"] = {"result": "ok" if round_bought else "failed", "turn": current_turn,
                                   "error": str(err), "payload": round_payload, "bought": round_bought}
                return current, bought

        self.failed_exchange_this_snapshot = set()
        self.last_buy_result = {"result": "ok", "turn": current_turn, "payload": all_payload, "bought": bought}
        return current, bought

    def _exchange_entries(self, client, current, entries, current_turn, before_coin):
        """Exchange a set of shop entries as one atomic call. multi_item_exchange is
        atomic, so if the server rejects ONE item (e.g. a 205 stale current_num) the
        whole call fails. When the set has more than one item, retry each item on its
        own so the rest still buy and only the offender is dropped + marked failed.
        Returns (current_state, bought, before_coin, last_error)."""
        payload = [dict(entry["payload"]) for entry in entries]
        try:
            result = client.exchange_items(payload, current_turn)
            current = self._merge_state(current, result)
            for entry in entries:
                self._ensure_local_exchange_applied(
                    current,
                    entry["shop_item_id"],
                    entry["item_id"],
                    entry["cost"],
                    entry["current_num"],
                    entry["before_buy_num"],
                    before_coin,
                )
                before_coin = max(0, before_coin - entry["cost"])
            return current, len(entries), before_coin, None
        except Exception as e:
            log.warning(f"Item Exchange Error at turn {current_turn}: {e}")
            if len(entries) <= 1:
                # Optional purchase: mark the offender failed-this-snapshot and skip it.
                # Only 208 loses the sid on this batch endpoint -> reload to resync;
                # 201/205 keep the sid synced and are safely skipped (no reload).
                if api_error_result_code(e) == 208:
                    self.recover_after_exchange_error = True
                for entry in entries:
                    self.failed_exchange_this_snapshot.add(int(entry.get("shop_item_id") or 0))
                return current, 0, before_coin, e
            bought = 0
            last_err = None
            for entry in entries:
                current, sub_bought, before_coin, sub_err = self._exchange_entries(
                    client, current, [entry], current_turn, before_coin)
                bought += sub_bought
                if sub_err is not None:
                    last_err = sub_err
            return current, bought, before_coin, last_err

    def _split_exchange_rounds(self, entries):
        rounds: list[list[Any]] = []
        round_item_ids: list[set[int]] = []
        for entry in entries:
            item_id = int(entry.get("item_id") or 0)
            for index, used_item_ids in enumerate(round_item_ids):
                if item_id not in used_item_ids:
                    rounds[index].append(entry)
                    used_item_ids.add(item_id)
                    break
            else:
                rounds.append([entry])
                round_item_ids.append({item_id})
        return rounds

    def _is_g1_program(self, program_id, race_planner):
        if not race_planner or not program_id:
            return False
        info = (race_planner.program or {}).get(program_id) or {}
        race_inst = str(info.get("race_instance_id") or "")
        return race_inst.startswith("1")

    def _first_shop_megaphone_candidate(self, available):
        if self.first_shop_megaphone_done:
            return None
        by_name = {name: row for name, row in available}
        for name in MEGAPHONE_PRIORITY:
            if name in by_name:
                return name, by_name[name]
        return None

    def _old_ui_cleat_before_race(self, owned, turn, program_id, race_planner):
        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        if master_qty + artisan_qty <= 0:
            return None

        if turn in CLIMAX_RACE_TURNS:
            if master_qty > 0:
                return "Master Cleat Hammer"
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            return None

        if not self._is_g1_program(program_id, race_planner):
            return None

        hold = 0
        if MASTER_HAMMER_EARLY_HOLD_TURN <= int(turn or 0) < MASTER_HAMMER_FULL_HOLD_TURN:
            hold = MASTER_HAMMER_EARLY_RESERVE
        elif MASTER_HAMMER_FULL_HOLD_TURN <= int(turn or 0) < CLIMAX_FIRST_RACE_TURN:
            hold = MASTER_HAMMER_CLIMAX_RESERVE
        if master_qty > hold:
            return "Master Cleat Hammer"
        if artisan_qty > 0:
            return "Artisan Cleat Hammer"
        return None

    def _old_ui_cleat_shop_target(self, available, owned, budget, current_turn, coin_reserve=0):
        return None

    def _coin_reserve(self, turn, budget, cfg):
        reserve, _cap_key, _cap_default = _coin_turn_bucket(turn)
        reserve = int(cfg.get("mant_coin_reserve", reserve) if "mant_coin_reserve" in cfg else reserve)
        cap = self._coin_cap(turn, cfg)
        if cap and budget > cap:
            reserve = min(reserve, max(0, cap // 2))
        if turn >= 73:
            return 0
        if turn >= 65 and budget > 300:
            return min(reserve, 40)
        if turn >= 56 and budget > 220:
            return min(reserve, 60)
        if turn >= 46 and budget > 260:
            return min(reserve, 80)
        if turn >= 36 and budget > 320:
            return min(reserve, 120)
        return reserve

    def _coin_cap(self, turn, cfg):
        _reserve, cap_key, cap_default = _coin_turn_bucket(turn)
        return int(cfg.get(cap_key, cap_default))

    def _buy_floor(self, name, tier, turn, start_budget, budget, threshold, cfg):
        reserve = self._coin_reserve(turn, start_budget, cfg)
        cap = self._coin_cap(turn, cfg)
        floor = max(int(threshold or 0), reserve) if tier > 1 else 0
        if self._is_instant_stat_item(name):
            if turn >= 46:
                return 0
            if turn >= 36 and start_budget > cap:
                return min(floor, 40)
            if start_budget > cap:
                return min(floor, reserve // 2)
            return min(floor, reserve)
        if turn >= 73:
            return 0
        if start_budget > cap:
            floor = min(floor, max(0, reserve // 2))
        if start_budget >= reserve + 400:
            floor = min(floor, max(0, reserve // 3))
        elif start_budget >= reserve + 250:
            floor = min(floor, max(0, reserve // 2))
        if turn >= 65:
            floor = min(floor, 40)
        elif turn >= 56:
            floor = min(floor, 80)
        elif turn >= 46:
            floor = min(floor, 120)
        return max(0, int(floor))

    def _buy_sort_key(self, name, row, pre_summer=False):
        cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
        limit = int(row.get("limit_turn") or 99)
        if not pre_summer:
            return (limit, cost)
        mega_rank = {"Empowering Megaphone": 0, "Motivating Megaphone": 1, "Coaching Megaphone": 2}
        if name in mega_rank:
            return (0, mega_rank[name], limit, cost)
        if name == "Good-Luck Charm":
            return (1, 0, limit, cost)
        if name in ENERGY_ITEMS:
            energy_rank = {"Vita 65": 0, "Vita 40": 1, "Vita 20": 2, "Royal Kale Juice": 3}
            return (1, 1, energy_rank.get(name, 9), limit, cost)
        if name == "Berry Sweet Cupcake":
            return (1, 2, 0, limit, cost)
        if name == "Plain Cupcake":
            return (1, 2, 1, limit, cost)
        if str(name or "").endswith("Ankle Weights"):
            return (2, limit, cost)
        if name == "Reset Whistle":
            return (3, limit, cost)
        return (9, limit, cost)

    def _skip_buy(self, name, owned, preset=None, turn=0, budget=0, data=None, race_planner=None):
        if name == "Energy Drink MAX EX":
            return True
        if name in FORBIDDEN_BUY_ITEMS:
            return True
        if name.endswith("Notepad") and (preset or {}).get("buy_notepads") is False:
            return True
        if name in MEGAPHONE_TIERS and self.first_shop_megaphone_done and not self._summer_hold_active(turn) and self._megaphone_buy_surplus(data or {}, owned, turn, race_planner, preset):
            return True
        if name in CURE_ITEMS:
            if name == AILMENT_CURE_ALL:
                return owned.get(name, 0) >= 2
            if name == "Rich Hand Cream":
                return owned.get(name, 0) >= 2
            if owned.get(AILMENT_CURE_ALL, 0) > 0 or owned.get(name, 0) > 0 or not self._can_use_cure_now(name, data or {}, turn):
                return True
            return False
        if name in TRAINING_APPLICATION_ITEMS:
            return (not self._training_application_allowed(name)) or owned.get(name, 0) > 0 or name in self.used_buffs
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is not None:
            counts = (preset or {}).get("_deck_type_counts") or []
            count = int(counts[type_idx] or 0) if len(counts) > type_idx else 0
            if name.endswith("Ankle Weights") and self._summer_hold_active(turn):
                return False
            if count < 2:
                return True
            return False
        if name in ONE_TIME_BUFF_ITEMS and name in self.used_buffs:
            return True
        return False
