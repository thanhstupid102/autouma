import json
from pathlib import Path

from career_bot.planning.factors import parse_factor_ids
from core.runtime_paths import resolve_master_json_path


_COLOUR_BY_CATEGORY = {
    "stat": "blue",
    "aptitude": "pink",
    "unique": "green",
    "skill": "white",
    "race": "white",
    "scenario": "white",
}


def factor_ids_from_row(row):
    def clean(values):
        if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
            values = [values]
        out = []
        for value in values or []:
            try:
                fid = int(value)
            except (TypeError, ValueError):
                continue
            if fid > 0:
                out.append(fid)
        return out

    if not isinstance(row, dict):
        return []
    ids = row.get("factor_id_array")
    if ids:
        cleaned = clean(ids)
        if cleaned:
            return cleaned
    return clean(item.get("factor_id") for item in row.get("factor_info_array") or [] if isinstance(item, dict))


def _load_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    # exists()/read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError):
        pass
    return {}


def load_factor_context(base_dir, state_root=None):
    root = Path(base_dir)
    return (
        _load_json(resolve_master_json_path(root, "factor_map.json", state_root)),
        _load_json(resolve_master_json_path(root, "skill_data.json", state_root)),
    )


def spark_colour(category):
    return _COLOUR_BY_CATEGORY.get(category)


def score_factor_ids(factor_ids, base_dir, state_root=None):
    factor_map, skill_data = load_factor_context(base_dir, state_root)
    score = {"blue": 0, "pink": 0, "green": 0, "white": 0}
    for factor in parse_factor_ids(factor_ids or [], factor_map=factor_map, skill_data=skill_data):
        colour = spark_colour(factor.get("category"))
        if colour == "white":
            score["white"] += 1
        elif colour:
            try:
                score[colour] += int(factor.get("stars") or 0)
            except (TypeError, ValueError):
                pass
    return score["blue"], score["pink"], score["green"], score["white"]


def choose_spark_list(option_factor_ids, base_dir, state_root=None):
    options = list(option_factor_ids or [])
    first = score_factor_ids(
        options[0] if len(options) > 0 else [], base_dir, state_root,
    )
    second = score_factor_ids(
        options[1] if len(options) > 1 else [], base_dir, state_root,
    )
    return 2 if second > first else 1


def _factor_select_rows(response):
    roots = []
    if isinstance(response, dict):
        roots.append(response)
        if isinstance(response.get("data"), dict):
            roots.append(response["data"])
    for root in roots:
        for key in ("single_mode_factor_select_common", "single_mode_factor_lottery_common"):
            common = root.get(key) or {}
            yield from common.get("factor_select_info_array") or []
        resume = root.get("resume_factor_select") or {}
        yield from resume.get("factor_select_info_array") or []
        load_common = root.get("single_mode_load_common") or {}
        resume = load_common.get("resume_factor_select") or {}
        yield from resume.get("factor_select_info_array") or []


def extract_reroll_option_map(*responses):
    options = {}
    for response in responses:
        for row in _factor_select_rows(response):
            if not isinstance(row, dict):
                continue
            try:
                lottery_id = int((row or {}).get("lottery_id") or 0)
            except (TypeError, ValueError):
                continue
            if lottery_id in (1, 2):
                ids = factor_ids_from_row(row)
                if ids:
                    options[lottery_id] = ids
    return options


def extract_reroll_options(*responses):
    options = extract_reroll_option_map(*responses)
    if 1 in options and 2 in options:
        return [options[1], options[2]]
    return []
