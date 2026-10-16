from career_bot.engine import CareerRunner
from career_bot.scenarios.grand_live import GrandLiveStrategy
from career_bot.scenarios.mant import MantStrategy


class FallbackClient:
    def __init__(self):
        self.calls = []

    def call(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        return {"data": {"chara_info": {"turn": 10, "playing_state": 1}, "unchecked_event_array": []}}


def test_fresh_career_state_fallback_uses_grand_live_prefix(tmp_path):
    runner = CareerRunner(tmp_path)
    client = FallbackClient()

    runner._fresh_career_state(client, GrandLiveStrategy())

    assert client.calls == [("single_mode_live/load", {})]


def test_fresh_career_state_fallback_uses_runner_strategy_when_omitted(tmp_path):
    runner = CareerRunner(tmp_path)
    runner.strategy = GrandLiveStrategy()
    client = FallbackClient()

    runner._fresh_career_state(client)

    assert client.calls == [("single_mode_live/load", {})]


def test_fresh_career_state_fallback_keeps_mant_free_prefix(tmp_path):
    runner = CareerRunner(tmp_path)
    client = FallbackClient()

    runner._fresh_career_state(client, MantStrategy())

    assert client.calls == [("single_mode_free/load", {})]


def test_blocked_minigame_fallback_uses_grand_live_prefix(tmp_path):
    runner = CareerRunner(tmp_path)
    client = FallbackClient()
    state = {"data": {"chara_info": {"turn": 24, "playing_state": 6}}}

    runner._recover_blocked_state(client, GrandLiveStrategy(), state)

    endpoint, payload = client.calls[0]
    assert endpoint == "single_mode_live/minigame_end"
    assert payload["current_turn"] == 24


def test_blocked_minigame_fallback_keeps_mant_free_prefix(tmp_path):
    runner = CareerRunner(tmp_path)
    client = FallbackClient()
    state = {"data": {"chara_info": {"turn": 24, "playing_state": 6}}}

    runner._recover_blocked_state(client, MantStrategy(), state)

    endpoint, payload = client.calls[0]
    assert endpoint == "single_mode_free/minigame_end"
    assert payload["current_turn"] == 24