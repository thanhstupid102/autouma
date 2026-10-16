from __future__ import annotations

import copy
from typing import Any

from career_bot.bot_config.defaults import MANT_SCENARIO_ID, default_bot_config
from career_bot.bot_config.schema import validate_bot_config
from career_bot.bot_config.store import BotConfigStore


def scenario_config(config: dict[str, Any], scenario_id: int | str) -> dict[str, Any]:
    sid = str(int(scenario_id or MANT_SCENARIO_ID))
    validated = validate_bot_config(config or {})
    return copy.deepcopy(validated["scenarios"].get(sid) or {})


def apply_bot_config_to_preset(
    preset: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    store: BotConfigStore | None = None,
    scenario_id: int | str | None = None,
) -> dict[str, Any]:
    """Return a runtime preset with the global bot config applied.

    MANT already consumes many top-level preset keys, so its scenario config is
    flattened into the runtime preset. Unity Cup uses constants today, so its
    scenario config is attached under a private key and read through helpers.
    """
    result = dict(preset or {})
    sid = int(scenario_id or result.get("scenario_id") or result.get("scenario") or MANT_SCENARIO_ID)
    full = config if config is not None else (store.read_active() if store is not None else default_bot_config())
    values = scenario_config(full, sid)
    from career_bot.scenarios import get_strategy_class  # lazy: scenarios imports bot_config
    strategy_cls = get_strategy_class(sid)
    if strategy_cls is not None:
        return strategy_cls.apply_config_to_preset(result, values)
    return result
