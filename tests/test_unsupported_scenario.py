from types import SimpleNamespace

import pytest

from career_bot.engine import CareerRunner
from career_bot.scenarios import STRATEGIES, is_runnable_scenario
from uma_api import routes, update_guard
from uma_api.client import UmaClient
from uma_api.errors import UnsupportedScenarioError


def make_client():
    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = None
    client.account_name = "lewpie"
    client.calls = []
    client.hard_reset_calls = 0

    def call(endpoint, args=None, **kwargs):
        client.calls.append((endpoint, args, kwargs))
        return {"data": {}}

    def hard_reset():
        client.hard_reset_calls += 1

    client.call = call
    client.hard_reset = hard_reset
    return client


@pytest.fixture
def unsupported_scenario_id():
    return next(
        scenario_id
        for scenario_id in range(1, max(STRATEGIES) + 2)
        if scenario_id not in STRATEGIES
    )


def test_registered_scenarios_are_runnable_and_unknown_scenarios_are_not(
    unsupported_scenario_id,
):
    for scenario_id in STRATEGIES:
        assert is_runnable_scenario(scenario_id) is True

    assert is_runnable_scenario(unsupported_scenario_id) is False


def test_single_mode_prefix_routes_registered_scenarios_and_keeps_zero_default():
    client = make_client()

    assert client._single_mode_prefix(4) == "single_mode_free"
    assert client._single_mode_prefix(2) == "single_mode_team"
    assert client._single_mode_prefix(None) == "single_mode_free"
    assert client._single_mode_prefix(0) == "single_mode_free"

    client.current_scenario_id = 2
    assert client._single_mode_prefix(None) == "single_mode_team"


def test_single_mode_prefix_rejects_an_unrunnable_scenario(
    monkeypatch, unsupported_scenario_id
):
    client = make_client()
    monkeypatch.setattr(
        routes._update_guard,
        "alert_unsupported_scenario",
        lambda *args: None,
    )

    with pytest.raises(UnsupportedScenarioError) as exc_info:
        client._single_mode_prefix(unsupported_scenario_id)

    assert exc_info.value.scenario_id == unsupported_scenario_id


def test_unknown_scenario_load_fails_before_a_wire_call_or_hard_reset(
    monkeypatch, unsupported_scenario_id
):
    client = make_client()
    client.current_scenario_id = unsupported_scenario_id
    alerts = []
    monkeypatch.setattr(
        routes._update_guard,
        "alert_unsupported_scenario",
        lambda *args: alerts.append(args),
    )

    with pytest.raises(UnsupportedScenarioError) as exc_info:
        client.load_career()

    error = exc_info.value
    assert error.scenario_id == unsupported_scenario_id
    assert f"Scenario {unsupported_scenario_id}" in str(error)
    assert "no strategy" in str(error)
    assert "game client" in str(error)
    assert "retry" not in str(error).lower()
    assert client.calls == []
    assert client.hard_reset_calls == 0
    assert len(alerts) == 1


def test_recovery_does_not_retry_or_hard_reset_an_unsupported_scenario(
    tmp_path, unsupported_scenario_id
):
    runner = CareerRunner(tmp_path)
    client = SimpleNamespace(load_calls=0, hard_reset_calls=0)

    def load_career():
        client.load_calls += 1
        raise UnsupportedScenarioError(unsupported_scenario_id)

    def hard_reset():
        client.hard_reset_calls += 1

    client.load_career = load_career
    client.hard_reset = hard_reset

    with pytest.raises(
        UnsupportedScenarioError, match=rf"Scenario {unsupported_scenario_id}"
    ):
        runner._fresh_career_state(client)

    assert client.load_calls == 1
    assert client.hard_reset_calls == 0


def test_runner_does_not_turn_an_unsupported_scenario_into_a_retry(
    tmp_path, unsupported_scenario_id
):
    runner = CareerRunner(tmp_path)
    runner._flush_report = lambda **kwargs: None

    with pytest.raises(
        UnsupportedScenarioError, match=rf"Scenario {unsupported_scenario_id}"
    ):
        try:
            raise UnsupportedScenarioError(unsupported_scenario_id)
        except UnsupportedScenarioError as error:
            runner._handle_turn_error(SimpleNamespace(), None, {}, error)


def test_client_version_error_skips_runner_recovery_ladder(tmp_path):
    runner = CareerRunner(tmp_path)
    runner._flush_report = lambda **kwargs: None
    runner._run_crash_retries = 0
    error = update_guard.ClientVersionError("publish a new client version")

    with pytest.raises(update_guard.ClientVersionError):
        try:
            raise error
        except update_guard.ClientVersionError as active_error:
            runner._handle_turn_error(
                SimpleNamespace(), None, {}, active_error,
            )

    assert runner._run_crash_retries == 0


def test_unsupported_scenario_uses_the_standard_terminal_alert(
    monkeypatch, tmp_path, unsupported_scenario_id
):
    alerts = []
    monkeypatch.setattr(
        update_guard,
        "alert_once",
        lambda *args, **kwargs: alerts.append((args, kwargs)) or True,
    )

    assert (
        update_guard.alert_unsupported_scenario(
            tmp_path, "lewpie", unsupported_scenario_id
        )
        is True
    )

    args, kwargs = alerts[0]
    assert args[1] == "lewpie"
    assert args[2] is update_guard.Diagnosis.UNSUPPORTED_SCENARIO
    assert f"Scenario {unsupported_scenario_id}" in args[3]
    assert "retry" not in args[3].lower()
    assert kwargs["extra"] == f"scenario_id={unsupported_scenario_id}"
