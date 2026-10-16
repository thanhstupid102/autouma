import pytest

from career_bot.bot_config import apply_bot_config_to_preset, default_bot_config
from career_bot.engine import CareerRunner
from career_bot.engine.report import new_report
from career_bot.scenarios.unity_cup import UnityCupStrategy
from uma_api.errors import ApiError


class ClockClient:
    ALARM_CLOCK_ITEM_ID = 95
    ALARM_CLOCK_CARAT_PRICE = 10

    def __init__(self, *, cached_clocks=0, live_clocks=0, live_carats=20):
        self.item_map = {} if cached_clocks is None else {95: cached_clocks}
        self.coin_info = {"fcoin": 0, "coin": 0}
        self.live_clocks = live_clocks
        self.live_carats = live_carats
        self.read_calls = 0
        self.buy_calls = 0
        self.purchase_error = None
        self.read_error = None
        self.events = []

    def read_info(self):
        self.read_calls += 1
        self.events.append("read")
        if self.read_error is not None:
            raise self.read_error
        data = {
            "coin_info": {"fcoin": self.live_carats, "coin": 0},
        }
        if self.live_clocks is not None:
            data["user_item"] = {"item_id": 95, "num": self.live_clocks}
        return {"data": data}

    def refresh_cached_account_state(self, data):
        self.coin_info = dict(data["coin_info"])
        if data.get("user_item"):
            self.item_map[95] = int(data["user_item"]["num"])

    def alarm_clock_carat_price(self):
        return 10

    def buy_alarm_clock(self, account_data=None):
        self.buy_calls += 1
        self.events.append("buy")
        if self.purchase_error is not None:
            raise self.purchase_error
        self.item_map[95] = int(self.item_map.get(95) or 0) + 1
        self.coin_info["fcoin"] -= 10
        return {"data": {}}


def test_cached_alarm_clock_count_is_none_when_all_partial_caches_omit_it(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None)

    assert runner._cached_alarm_clock_count(client) is None


def test_ensure_alarm_clock_owned_skips_refresh_and_purchase(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=1)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert client.read_calls == 0
    assert client.buy_calls == 0


def test_ensure_alarm_clock_buys_with_enough_live_carats(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.report = new_report()
    client = ClockClient(live_carats=20)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert client.read_calls == 1
    assert client.buy_calls == 1
    assert client.item_map[95] == 1
    assert runner.status["clocks_bought"] == 1
    assert runner.report["clocks_bought"] == 1


def test_ensure_alarm_clock_unknown_reaches_refresh_before_purchase(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None, live_clocks=None)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert client.events == ["read", "buy"]


def test_ensure_alarm_clock_unknown_refresh_finds_owned_clock(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None, live_clocks=1)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert client.read_calls == 1
    assert client.buy_calls == 0


def test_ensure_alarm_clock_unknown_refresh_confirms_none_and_buys_once(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None, live_clocks=None)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert client.read_calls == 1
    assert client.buy_calls == 1


def test_ensure_alarm_clock_insufficient_carats_does_not_purchase(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(live_carats=9)

    assert runner._ensure_alarm_clock(client, {}) is False
    assert client.read_calls == 1
    assert client.buy_calls == 0
    assert any("only 9/10 carats" in row["detail"] for row in runner.status["log"])


def test_ensure_alarm_clock_disabled_refreshes_but_does_not_purchase(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(live_carats=20)

    assert runner._ensure_alarm_clock(
        client,
        {"buy_clocks_with_carats": False},
    ) is False
    assert client.read_calls == 1
    assert client.buy_calls == 0


def test_ensure_alarm_clock_uses_applied_unity_scenario_config(tmp_path):
    config = default_bot_config()
    config["scenarios"]["2"]["buy_clocks_with_carats"] = False
    preset = apply_bot_config_to_preset({"scenario_id": 2}, config=config)
    runner = CareerRunner(tmp_path)
    runner.strategy = UnityCupStrategy()
    client = ClockClient(live_carats=20)

    assert "buy_clocks_with_carats" not in preset
    assert runner._ensure_alarm_clock(client, preset) is False
    assert client.read_calls == 1
    assert client.buy_calls == 0


def test_ensure_alarm_clock_honors_per_career_purchase_cap(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.status["clocks_bought"] = 3
    client = ClockClient(live_carats=20)

    assert runner._ensure_alarm_clock(
        client,
        {"max_clocks_bought_per_career": 3},
    ) is False
    assert client.read_calls == 1
    assert client.buy_calls == 0


def test_ensure_alarm_clock_purchase_failure_is_logged_and_not_propagated(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(live_carats=20)
    client.purchase_error = ApiError(777, "item/exchange", "rejected")

    assert runner._ensure_alarm_clock(client, {}) is False
    assert client.buy_calls == 1
    assert any("result_code=777" in row["detail"] for row in runner.status["log"])


def test_ensure_alarm_clock_blocked_refresh_error_propagates(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None)
    error = ApiError(102, "load/index", "blocked")
    client.read_error = error

    with pytest.raises(ApiError) as caught:
        runner._ensure_alarm_clock(client, {})

    assert caught.value is error


def test_paid_continue_omitting_clock_row_decrements_known_cache(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=1)

    runner._sync_cached_alarm_clock_count(client, {"data": {"user_item": []}})

    assert client.item_map[95] == 0
    assert runner.user_info_cache["item_map"][95] == 0


def test_paid_continue_omitting_clock_row_leaves_unknown_cache_unknown(tmp_path):
    runner = CareerRunner(tmp_path)
    client = ClockClient(cached_clocks=None)

    runner._sync_cached_alarm_clock_count(client, {"data": {"user_item": []}})

    assert 95 not in client.item_map
    assert 95 not in runner.user_info_cache.get("item_map", {})


def test_alarm_clock_cap_survives_automatic_resume(monkeypatch, tmp_path):
    runner = CareerRunner(tmp_path)
    runner.status["clocks_bought"] = 3
    runner.set_resume_attempt(1, 3)
    monkeypatch.setattr(
        CareerRunner,
        "_run",
        lambda self, *_args: self._mark(running=False),
    )

    runner.start(None, {"scenario_id": 2}, {})
    runner.thread.join(timeout=10)
    client = ClockClient(live_clocks=0)

    assert runner._ensure_alarm_clock(
        client,
        {"max_clocks_bought_per_career": 3},
    ) is False
    assert runner.status["clocks_bought"] == 3
    assert client.buy_calls == 0


def test_rejected_races_survive_automatic_resume_but_reset_for_new_career(
    monkeypatch,
    tmp_path,
):
    runner = CareerRunner(tmp_path)
    runner.race_planner.reject(28, 198)
    runner.race_planner.reject(28, 199)
    runner.set_resume_attempt(1, 3)
    monkeypatch.setattr(
        CareerRunner,
        "_run",
        lambda self, *_args: self._mark(running=False),
    )

    runner.start(None, {"scenario_id": 2}, {})
    runner.thread.join(timeout=10)
    forced_state = {
        "data": {
            "chara_info": {"turn": 28},
            "home_info": {
                "command_info_array": [
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                ]
            },
            "race_condition_array": [
                {"program_id": 198},
                {"program_id": 199},
            ],
        }
    }

    assert runner.strategy.next_decision(forced_state, {}).action == "idle"

    runner.set_resume_attempt(0, 0)
    runner.start(None, {"scenario_id": 2}, {})
    runner.thread.join(timeout=10)
    assert runner.race_planner.rejected == set()
