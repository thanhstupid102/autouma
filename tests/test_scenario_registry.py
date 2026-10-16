from career_bot.scenarios import (
    DEFAULT_SCENARIO_ID,
    STRATEGIES,
    get_strategy_class,
    resolve_scenario_id,
)
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.unity_cup import UnityCupStrategy


def test_registry_maps_scenario_ids_to_strategies():
    assert STRATEGIES[4] is MantStrategy
    assert STRATEGIES[2] is UnityCupStrategy


def test_registry_keys_come_from_the_classes_themselves():
    for scenario_id, cls in STRATEGIES.items():
        assert cls.scenario_id == scenario_id


def test_get_strategy_class_returns_none_for_unknown():
    assert get_strategy_class(99) is None
    assert get_strategy_class(None) is None


def test_resolve_scenario_id_reads_both_keys_and_defaults_to_mant():
    assert DEFAULT_SCENARIO_ID == 4
    assert resolve_scenario_id({"scenario_id": 2}) == 2
    assert resolve_scenario_id({"scenario": 2}) == 2
    assert resolve_scenario_id({"scenario_id": 0, "scenario": 2}) == 2
    assert resolve_scenario_id({}) == 4
    assert resolve_scenario_id(None) == 4
