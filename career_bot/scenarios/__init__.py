"""Scenario registry.

Adding a new scenario: create career_bot/scenarios/<name>/ exposing a
ScenarioStrategy subclass with a unique `scenario_id`, then add the class to
STRATEGY_CLASSES below. See career_bot/scenarios/README.md.
"""

from career_bot.scenarios.grand_live import GrandLiveStrategy
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.unity_cup import UnityCupStrategy

STRATEGY_CLASSES = (MantStrategy, UnityCupStrategy, GrandLiveStrategy)
STRATEGIES = {cls.scenario_id: cls for cls in STRATEGY_CLASSES}
DEFAULT_SCENARIO_ID = MantStrategy.scenario_id  # 4


def runnable_scenarios():
    """Ordered [{id, label}] for every registered strategy -- the data-driven
    source of truth the frontend scenario picker renders from."""
    return [{"id": sid, "label": cls.display_label} for sid, cls in STRATEGIES.items()]


def endpoint_prefix_by_id():
    """Map scenario_id -> its career-API endpoint prefix (single_mode_*),
    each declared by its strategy. Owned here so a new scenario declares its
    prefix on its strategy instead of editing uma_api/client.py."""
    return {sid: cls.endpoint_prefix for sid, cls in STRATEGIES.items()}


def get_strategy_class(scenario_id):
    try:
        return STRATEGIES.get(int(scenario_id))
    except (TypeError, ValueError):
        return None


def is_runnable_scenario(scenario_id):
    """Whether the registry has a strategy that can drive ``scenario_id``."""
    return get_strategy_class(scenario_id) is not None


def resolve_scenario_id(preset):
    """The scenario id a preset runs under (presets carry it under either
    'scenario_id' or the legacy 'scenario' key; 0/absent means MANT)."""
    preset = preset or {}
    return int(preset.get("scenario_id") or preset.get("scenario") or DEFAULT_SCENARIO_ID)
