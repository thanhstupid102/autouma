"""Global bot scoring / train-decision preset storage.

This module is intentionally separate from career_bot.planning.presets: skill/race
presets describe a trainee build, while bot config describes how the automation
scores and chooses commands globally for the app.
"""

from career_bot.bot_config.apply import apply_bot_config_to_preset, scenario_config
from career_bot.bot_config.defaults import (
    BOT_CONFIG_VERSION,
    DEFAULT_BOT_CONFIG,
    GRAND_LIVE_DEFAULTS,
    GRAND_LIVE_SCENARIO_ID,
    MANT_DEFAULTS,
    MANT_SCENARIO_ID,
    SCENARIOS,
    UNITY_CONFIG_KEY,
    UNITY_CUP_SCENARIO_ID,
    UNITY_DEFAULTS,
    default_bot_config,
)
from career_bot.bot_config.migrations import (
    OLDEST_BOT_CONFIG_VERSION,
    migrate_bot_config,
)
from career_bot.bot_config.schema import BotConfigValidationError, validate_bot_config
from career_bot.bot_config.store import BotConfigStore
from career_bot.bot_config.ui_metadata import (
    FIELD_DESCRIPTIONS,
    FIELD_LABELS,
    bot_config_field_specs,
)


__all__ = [
    "BOT_CONFIG_VERSION",
    "DEFAULT_BOT_CONFIG",
    "GRAND_LIVE_DEFAULTS",
    "GRAND_LIVE_SCENARIO_ID",
    "FIELD_DESCRIPTIONS",
    "FIELD_LABELS",
    "MANT_DEFAULTS",
    "MANT_SCENARIO_ID",
    "OLDEST_BOT_CONFIG_VERSION",
    "SCENARIOS",
    "UNITY_CONFIG_KEY",
    "UNITY_CUP_SCENARIO_ID",
    "UNITY_DEFAULTS",
    "BotConfigStore",
    "BotConfigValidationError",
    "apply_bot_config_to_preset",
    "bot_config_field_specs",
    "default_bot_config",
    "migrate_bot_config",
    "scenario_config",
    "validate_bot_config",
]
