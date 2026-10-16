"""Versioned upgrades for stored bot configs (§12.6).

A bot config on disk (``data/bot_config/default.json``, ``active.json``) or one
POSTed/imported through ``/api/bot-config`` was written by whatever schema
version was current at the time. ``career_bot.bot_config.schema`` validates
*strictly* -- an unknown key is a hard ``BotConfigValidationError`` -- so a knob
can only be deprecated if old payloads are upgraded first.

``migrate_bot_config`` is that upgrade. It runs at the top of
``validate_bot_config``, which is the single funnel every load/save path goes
through (``BotConfigStore.read_default`` / ``read_active`` / ``write_active``
and ``bot_config.apply.scenario_config``), so a legacy config is repaired
transparently wherever it enters the process.

Contract:
  * pure -- never mutates ``raw``;
  * idempotent -- migrating an already-current config is a no-op beyond the
    version stamp;
  * lossless for live knobs -- only keys listed in a step are removed;
  * a payload with a missing/blank version is treated as the OLDEST schema (1),
    because that is what shipped before the field was enforced;
  * a payload whose version is unparseable or NEWER than ``BOT_CONFIG_VERSION``
    is returned untouched, so ``validate_bot_config`` still reports it as
    unsupported instead of this module silently downgrading it.
"""

from __future__ import annotations

import copy
from typing import Any

from career_bot.bot_config.defaults import (
    BOT_CONFIG_VERSION,
    MANT_SCENARIO_ID,
    UNITY_CUP_SCENARIO_ID,
)


OLDEST_BOT_CONFIG_VERSION = 1

_MANT_SID = str(MANT_SCENARIO_ID)
_UNITY_SID = str(UNITY_CUP_SCENARIO_ID)

# v1 -> v2: MANT knobs that no scoring/decision path ever read. Verified by a
# whole-repo grep (career_bot, backend, uma_api, scripts, tests,
# frontend/src) -- their only readers were the defaults table itself,
# ui_metadata's description map, and hydrate_preset copying them verbatim into
# a runtime preset that never looked them up again.
_V2_DROPPED_MANT_KEYS = (
    "special_training",
    "spirit_explosion",
    "wit_special_multiplier",
)

# v1 -> v2: `npc_score_value` rows carried a third column; _npc_score only ever
# reads [0] and [1] to interpolate by bond. Truncating is required, not
# cosmetic: the float row template accepts the stale decimal third column, so
# it would otherwise survive validation even though that column is dead data.
_V2_ROW_WIDTHS = {"npc_score_value": 2}


def _drop_keys(scenario: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in scenario.items() if key not in keys}


def _truncate_rows(scenario: dict[str, Any], widths: dict[str, int]) -> dict[str, Any]:
    result = dict(scenario)
    for key, width in widths.items():
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        result[key] = [row[:width] if isinstance(row, list) else row for row in rows]
    return result


def _migrate_v1_to_v2(scenarios: dict[str, Any]) -> dict[str, Any]:
    """Drop the MANT knobs nothing reads and the dead npc_score_value column."""
    result = dict(scenarios)
    mant = result.get(_MANT_SID)
    if isinstance(mant, dict):
        result[_MANT_SID] = _truncate_rows(
            _drop_keys(mant, _V2_DROPPED_MANT_KEYS),
            _V2_ROW_WIDTHS,
        )
    return result


# stored version -> function producing the NEXT version's `scenarios` mapping.
_STEPS = {
    1: _migrate_v1_to_v2,
}


def _migrate_unity_legacy_stack_bonus_step(values: dict[str, Any]) -> dict[str, Any]:
    """Accept old Unity configs that used one Speed/Power/Guts stack step.

    Version-INDEPENDENT (it predates the version field and is cheap to keep
    running), so it is applied on every payload rather than from a numbered
    step -- exactly the behaviour it had when it lived in schema.py.
    """
    if "speed_power_guts_stack_bonus_step" not in values:
        return values
    migrated = dict(values)
    legacy_step = migrated.pop("speed_power_guts_stack_bonus_step")
    for key in (
        "speed_blue_purple_soul_stack_bonus_step",
        "power_blue_purple_soul_stack_bonus_step",
        "guts_blue_purple_soul_stack_bonus_step",
    ):
        migrated.setdefault(key, legacy_step)
    return migrated


def stored_config_version(raw: dict[str, Any]) -> int | None:
    """The schema version ``raw`` claims, or None when it is not a number.

    Missing / null / 0 mean "written before the field was enforced" -> the
    oldest schema.
    """
    value = raw.get("version")
    if value is None or value == "":
        return OLDEST_BOT_CONFIG_VERSION
    try:
        version = int(value)
    except (TypeError, ValueError):
        return None
    return version or OLDEST_BOT_CONFIG_VERSION


def migrate_bot_config(raw: Any) -> Any:
    """Upgrade a stored bot config payload to ``BOT_CONFIG_VERSION``.

    Non-dict input is passed through untouched so ``validate_bot_config`` keeps
    ownership of the "must be a JSON object" error message.
    """
    if not isinstance(raw, dict):
        return raw
    version = stored_config_version(raw)
    if version is None or version > BOT_CONFIG_VERSION:
        return raw  # unparseable / from the future -> let validation reject it

    scenarios = raw.get("scenarios")
    if scenarios is not None and not isinstance(scenarios, dict):
        return raw  # malformed -> let validation reject it

    migrated = copy.deepcopy(scenarios) if scenarios else {}
    unity = migrated.get(_UNITY_SID)
    if isinstance(unity, dict):
        migrated[_UNITY_SID] = _migrate_unity_legacy_stack_bonus_step(unity)

    while version < BOT_CONFIG_VERSION:
        step = _STEPS.get(version)
        if step is None:
            # A gap in the chain: refuse to stamp a version we did not actually
            # reach, so validation rejects the payload loudly instead of this
            # module mislabelling a half-upgraded config as current.
            return raw
        migrated = step(migrated)
        version += 1

    result = copy.deepcopy(raw)
    if scenarios is not None or migrated:
        result["scenarios"] = migrated
    result["version"] = BOT_CONFIG_VERSION
    return result
