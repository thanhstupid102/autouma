from __future__ import annotations

import copy
from typing import Any

from career_bot.bot_config.defaults import (
    BOT_CONFIG_VERSION,
    DEFAULT_BOT_CONFIG,
    default_bot_config,
)
from career_bot.bot_config.migrations import migrate_bot_config


class BotConfigValidationError(ValueError):
    """Raised when an imported/saved bot config JSON is invalid."""


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _validate_value(value: Any, default: Any, path: str) -> Any:
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise BotConfigValidationError(f"{path} must be a boolean")
        return value
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise BotConfigValidationError(f"{path} must be an integer")
        return int(value)
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BotConfigValidationError(f"{path} must be a number")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise BotConfigValidationError(f"{path} must be a string")
        return value
    if isinstance(default, list):
        if not isinstance(value, list):
            raise BotConfigValidationError(f"{path} must be an array")
        if not default:
            return copy.deepcopy(value)
        result = []
        for idx, item in enumerate(value):
            template = default[idx] if idx < len(default) else default[-1]
            result.append(_validate_value(item, template, f"{path}[{idx}]"))
        return result
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise BotConfigValidationError(f"{path} must be an object")
        dict_result = copy.deepcopy(default)
        unknown = set(value) - set(default)
        if unknown:
            raise BotConfigValidationError(f"Unknown field(s) at {path}: {', '.join(sorted(unknown))}")
        for key, item in value.items():
            dict_result[key] = _validate_value(item, default[key], f"{path}.{key}")
        return dict_result
    return copy.deepcopy(value)


def validate_bot_config(raw: Any) -> dict[str, Any]:
    # Upgrade first: this is the single funnel every load/save path uses
    # (BotConfigStore.read_default/read_active/write_active, apply.scenario_config,
    # the /api/bot-config import), so a config written by an older schema version
    # is repaired here instead of failing the strict unknown-key check below.
    raw = migrate_bot_config(raw)
    if not isinstance(raw, dict):
        raise BotConfigValidationError("Bot config must be a JSON object")
    allowed_top = {"version", "scenarios"}
    unknown_top = set(raw) - allowed_top
    if unknown_top:
        raise BotConfigValidationError(f"Unknown top-level field(s): {', '.join(sorted(unknown_top))}")
    try:
        version = int(raw.get("version") or BOT_CONFIG_VERSION)
    except (TypeError, ValueError):
        raise BotConfigValidationError(f"Unsupported bot config version: {raw.get('version')}")
    if version != BOT_CONFIG_VERSION:
        raise BotConfigValidationError(f"Unsupported bot config version: {raw.get('version')}")
    if "scenarios" in raw and not isinstance(raw["scenarios"], dict):
        raise BotConfigValidationError("scenarios must be an object")

    result = default_bot_config()
    for scenario_id, scenario_values in (raw.get("scenarios") or {}).items():
        sid = str(scenario_id)
        if sid not in DEFAULT_BOT_CONFIG["scenarios"]:
            raise BotConfigValidationError(f"Unknown scenario id: {scenario_id}")
        result["scenarios"][sid] = _validate_value(
            scenario_values,
            DEFAULT_BOT_CONFIG["scenarios"][sid],
            f"scenarios.{sid}",
        )
    return result
