from career_bot.bot_config import apply_bot_config_to_preset
from career_bot.scenarios import resolve_scenario_id

from backend.app.domain.account_status import result_scenario_id


def sync_runtime_preset_scenario(preset, result=None, req=None):
    sid = result_scenario_id(result)
    if not sid and req is not None:
        sid = int(getattr(req, 'scenario_id', 0) or 0)
    if not sid:
        sid = resolve_scenario_id(preset)
    preset['scenario_id'] = sid
    preset['scenario'] = sid
    if req is not None:
        req.scenario_id = sid
    return sid


def apply_runtime_bot_config(preset, scenario_id, store):
    updated = apply_bot_config_to_preset(
        preset,
        store=store,
        scenario_id=scenario_id or preset.get("scenario_id") or preset.get("scenario"),
    )
    preset.clear()
    preset.update(updated)
    return preset
