"""TP / recovery-resource methods for CareerRunner, extracted verbatim from actions.py.

Everything here answers one question: "can we afford the next paid action, and if
not, which recovery resource do we spend?" -- the cached/live TP bottle count, the
carat (jewel) TP recovery fallback, and the TP balance read off the client. None of
these drive a career decision; they only top the account up so a decision the runner
already made can go through.
"""

import logging
from contextlib import nullcontext
from typing import TYPE_CHECKING

from uma_api import account_state
from uma_api.errors import api_error_result_code, is_blocked_state_error


log = logging.getLogger(__name__)


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerResourceMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerResourceMixin(_HostState):
    _ALARM_CLOCK_ITEM_ID = 95
    _ALARM_CLOCK_CARAT_PRICE_FALLBACK = 10

    def _tp_current(self, client):
        try:
            return int((getattr(client, "tp_info", {}) or {}).get("current_tp") or 0)
        except (TypeError, ValueError):
            return 0

    def _cached_tp_bottle_count(self, bottle_id):
        cache = getattr(self, "user_info_cache", {}) or {}
        counts = []
        for value in (
            cache.get("tp_bottle_count"),
            (cache.get("item_map") or {}).get(int(bottle_id)),
        ):
            if value is None:
                continue
            try:
                counts.append(max(int(value or 0), 0))
            except (TypeError, ValueError):
                continue
        return max(counts) if counts else None

    def _set_cached_tp_bottle_count(self, bottle_id, count):
        cache = getattr(self, "user_info_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.user_info_cache = cache
        count = max(int(count or 0), 0)
        cache["tp_bottle_count"] = count
        item_map = cache.get("item_map")
        if not isinstance(item_map, dict):
            item_map = {}
            cache["item_map"] = item_map
        item_map[int(bottle_id)] = count

    def _clock_purchase_setting(self, preset, key, default):
        preset = preset if isinstance(preset, dict) else {}
        if key in preset:
            return preset[key]
        config_key = getattr(getattr(self, "strategy", None), "config_preset_key", "")
        values = preset.get(config_key) if config_key else None
        if isinstance(values, dict) and key in values:
            return values[key]
        return default

    def _cached_alarm_clock_count(self, client):
        item_id = int(getattr(client, "ALARM_CLOCK_ITEM_ID", self._ALARM_CLOCK_ITEM_ID))
        counts = []
        cache = getattr(self, "user_info_cache", {}) or {}
        for items in (
            getattr(client, "item_map", None),
            cache.get("item_map"),
        ):
            if not isinstance(items, dict):
                continue
            for key in (item_id, str(item_id)):
                if key in items:
                    try:
                        counts.append(max(int(items.get(key) or 0), 0))
                    except (TypeError, ValueError):
                        continue
        return max(counts) if counts else None

    def _set_cached_alarm_clock_count(self, client, count):
        item_id = int(getattr(client, "ALARM_CLOCK_ITEM_ID", self._ALARM_CLOCK_ITEM_ID))
        count = max(int(count or 0), 0)
        client_items = getattr(client, "item_map", None)
        if isinstance(client_items, dict):
            client_items[item_id] = count
        cache = getattr(self, "user_info_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.user_info_cache = cache
        cached_items = cache.get("item_map")
        if not isinstance(cached_items, dict):
            cached_items = {}
            cache["item_map"] = cached_items
        cached_items[item_id] = count

    def _sync_cached_alarm_clock_count(self, client, response):
        item_id = int(getattr(client, "ALARM_CLOCK_ITEM_ID", self._ALARM_CLOCK_ITEM_ID))
        data = (response or {}).get("data") if isinstance(response, dict) else response
        rows = account_state.find_item_rows(data)
        if account_state.rows_report_item(rows, item_id):
            for row in rows or []:
                try:
                    if int((row or {}).get("item_id")) != item_id:
                        continue
                except (TypeError, ValueError):
                    continue
                count = account_state.item_count(row)
                if count is not None:
                    self._set_cached_alarm_clock_count(client, count)
                return
        count = self._cached_alarm_clock_count(client)
        if count is not None:
            self._set_cached_alarm_clock_count(client, count - 1)

    def _record_clock_counter(self, key):
        with self.lock:
            count = int(self.status.get(key) or 0) + 1
            self.status[key] = count
            if isinstance(self.report, dict):
                self.report[key] = count

    def _record_clock_used(self):
        self._record_clock_counter("clocks_used")

    def _ensure_alarm_clock(self, client, preset):
        cached_count = self._cached_alarm_clock_count(client)
        if cached_count is not None and cached_count > 0:
            return True

        try:
            transaction_lock = getattr(client, "_call_lock", None)
            with transaction_lock if transaction_lock is not None else nullcontext():
                info = client.read_info()
                data = (info or {}).get("data", {})
                if not isinstance(data, dict):
                    raise ValueError("load/index returned no account data")
                if hasattr(client, "refresh_cached_account_state"):
                    client.refresh_cached_account_state(data)
                else:
                    if data.get("coin_info"):
                        client.coin_info = data["coin_info"]
                    rows = account_state.find_item_rows(data)
                    for row in rows or []:
                        if not isinstance(row, dict) or row.get("item_id") is None:
                            continue
                        count = account_state.item_count(row)
                        if count is not None and isinstance(getattr(client, "item_map", None), dict):
                            client.item_map[int(row["item_id"])] = count

                # Per-action item arrays are partial, but this fresh load/index is
                # a full account snapshot: an absent item 95 is authoritative zero.
                rows = account_state.find_item_rows(data)
                if not account_state.rows_report_item(
                    rows,
                    int(getattr(client, "ALARM_CLOCK_ITEM_ID", self._ALARM_CLOCK_ITEM_ID)),
                ):
                    self._set_cached_alarm_clock_count(client, 0)
                if self._cached_alarm_clock_count(client) > 0:
                    return True

                if not bool(
                    self._clock_purchase_setting(
                        preset,
                        "buy_clocks_with_carats",
                        True,
                    )
                ):
                    self._log(
                        "alarm_clock_purchase_skipped",
                        self.status.get("turn", 0),
                        "buying Alarm Clocks with carats is disabled",
                    )
                    return False

                try:
                    max_bought = max(
                        int(
                            self._clock_purchase_setting(
                                preset,
                                "max_clocks_bought_per_career",
                                3,
                            )
                        ),
                        0,
                    )
                except (TypeError, ValueError):
                    max_bought = 3
                bought = max(int(self.status.get("clocks_bought") or 0), 0)
                if bought >= max_bought:
                    self._log(
                        "alarm_clock_purchase_skipped",
                        self.status.get("turn", 0),
                        f"Alarm Clock purchase cap reached ({bought}/{max_bought})",
                    )
                    return False

                coin_info = getattr(client, "coin_info", {}) or {}
                if not isinstance(coin_info, dict) or not any(
                    key in coin_info for key in ("fcoin", "coin")
                ):
                    raise ValueError("load/index returned no coin_info")
                carats = int(coin_info.get("fcoin") or 0) + int(
                    coin_info.get("coin") or 0
                )
                price_getter = getattr(client, "alarm_clock_carat_price", None)
                price = (
                    int(price_getter())
                    if callable(price_getter)
                    else int(
                        getattr(
                            client,
                            "ALARM_CLOCK_CARAT_PRICE",
                            self._ALARM_CLOCK_CARAT_PRICE_FALLBACK,
                        )
                    )
                )
                if carats < price:
                    self._log(
                        "alarm_clock_purchase_skipped",
                        self.status.get("turn", 0),
                        f"only {carats}/{price} carats",
                    )
                    return False

                if bought == 0:
                    log.warning(
                        "buying Alarm Clock for %s carats (1/%s) - "
                        "set buy_clocks_with_carats=false to disable",
                        price,
                        max_bought,
                    )
                client.buy_alarm_clock(account_data=data)
                self._record_clock_counter("clocks_bought")
                return True
        except Exception as exc:
            if is_blocked_state_error(exc):
                raise
            result_code = api_error_result_code(exc)
            code_text = result_code if result_code is not None else "unknown"
            self._log(
                "alarm_clock_purchase_failed",
                self.status.get("turn", 0),
                f"result_code={code_text}: {exc}",
            )
            return False

    def _ensure_spark_reroll_tp(self, client, cost=30):
        current = self._tp_current(client)
        if current >= cost:
            return True
        bottle_id = int(getattr(client, "TP_BOTTLE_ITEM_ID", 32))
        bottles = self._cached_tp_bottle_count(bottle_id) or 0
        try:
            bottles = max(bottles, int(((getattr(client, "item_map", {}) or {}).get(bottle_id)) or 0))
        except (TypeError, ValueError):
            pass
        fallback_reason = f"have {current}, cached TP bottles={bottles}"
        if bottles > 0 and hasattr(client, "use_recovery_item"):
            try:
                client_items = getattr(client, "item_map", None)
                if isinstance(client_items, dict):
                    client_items[bottle_id] = max(int(client_items.get(bottle_id) or 0), bottles)
                self._log("spark_reroll_tp", 0, f"have {current}, using cached TP bottle {bottle_id} x1 ({bottles} owned)")
                tp = client.use_recovery_item(bottle_id, 1)
                remaining = bottles - 1
                if isinstance(client_items, dict):
                    try:
                        remaining = min(remaining, max(int(client_items.get(bottle_id) or 0), 0))
                    except (TypeError, ValueError):
                        pass
                    client_items[bottle_id] = remaining
                self._set_cached_tp_bottle_count(bottle_id, remaining)
                if tp:
                    client.tp_info = tp
                current = self._tp_current(client)
                if current >= cost:
                    return True
                fallback_reason = f"only {current}/{cost} TP after bottle"
            except Exception as bottle_err:
                fallback_reason = f"bottle unavailable ({bottle_err})"

        self._log("spark_reroll_tp", 0, f"{fallback_reason}; falling back to carat TP recovery")
        try:
            info = client.read_info()
            data = (info or {}).get("data", {})
            if not isinstance(data, dict):
                raise ValueError("load/index returned no account data")
            if hasattr(client, "refresh_cached_account_state"):
                client.refresh_cached_account_state(data)
            else:
                if data.get("tp_info"):
                    client.tp_info = data["tp_info"]
                if data.get("coin_info"):
                    client.coin_info = data["coin_info"]
        except Exception as refresh_err:
            self._log(
                "spark_reroll_tp",
                0,
                f"carat TP recovery skipped: live account refresh failed ({refresh_err}); finishing original list",
            )
            return False

        current = self._tp_current(client)
        if current >= cost:
            return True

        coin_info = data.get("coin_info") or {}
        try:
            if not isinstance(coin_info, dict) or not any(key in coin_info for key in ("fcoin", "coin")):
                raise ValueError("load/index returned no coin_info")
            total_jewels = int(coin_info.get("fcoin") or 0) + int(coin_info.get("coin") or 0)
        except (TypeError, ValueError) as coin_err:
            self._log(
                "spark_reroll_tp",
                0,
                f"carat TP recovery skipped: invalid live jewel balance ({coin_err}); finishing original list",
            )
            return False
        if total_jewels < self._CARAT_TP_RECOVERY_COST:
            self._log(
                "spark_reroll_tp",
                0,
                f"carat TP recovery skipped: only {total_jewels}/{self._CARAT_TP_RECOVERY_COST} jewels after live refresh; finishing original list",
            )
            return False

        try:
            tp = client.recovery_tp(1)
            if tp:
                client.tp_info = tp
        except Exception as carat_err:
            if "API error 213 on user/recovery_trainer_point" in str(carat_err):
                self._log(
                    "spark_reroll_tp",
                    0,
                    f"carat TP recovery rejected by server (213: {carat_err}); finishing original list",
                )
            else:
                self._log("spark_reroll_tp", 0, f"carat TP recovery failed ({carat_err}); finishing original list")
            return False
        current = self._tp_current(client)
        if current < cost:
            self._log("spark_reroll_tp", 0, f"only {current}/{cost} TP after carat recovery; finishing original list")
            return False
        return True
