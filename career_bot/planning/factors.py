"""Shared parser for trained-character factor ids."""

import uma_data


CATEGORY_ORDER = {
    "stat": 0,
    "aptitude": 1,
    "unique": 2,
    "race": 3,
    "skill": 4,
    "scenario": 5,
    "other": 6,
}

STAT_MAP = {
    1: "Speed",
    2: "Stamina",
    3: "Power",
    4: "Guts",
    5: "Wit",
    11: "Turf",
    12: "Dirt",
    21: "Short",
    22: "Mile",
    23: "Medium",
    24: "Long",
    31: "Front Runner",
    32: "Pace Chaser",
    33: "Late Surger",
    34: "End Closer",
}


def skill_entry_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or ""
    return entry


def clean_factor_name(name, skill_data=None, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = skill_entry_name((skill_data or {}).get(f"{base_id}2"))
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")


def parse_factor_ids(fid_array, factor_map=None, skill_data=None, owner_card_id=None):
    results = []
    factor_map = factor_map or {}
    skill_data = skill_data or {}

    owner_cid_str = str(owner_card_id) if owner_card_id else ""
    if len(owner_cid_str) > 4:
        owner_cid_str = owner_cid_str[:4]

    for fid in fid_array or []:
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        if not fid or fid <= 0:
            continue

        fid_str = str(fid)
        factor_info = factor_map.get(fid_str)
        if factor_info:
            base_id = fid // 100
            category = factor_info.get("category") or uma_data.factor_category(fid)
            name = clean_factor_name(
                factor_info.get("name", f"Unknown({fid})"),
                skill_data,
                base_id,
                category,
            )
            stars = factor_info.get("stars", fid % 100)
            results.append({"name": name, "stars": stars, "id": fid, "category": category})
            continue

        base_id = fid // 100
        stars = fid % 100
        bid_str = str(base_id)
        name = f"Unknown({base_id})"
        category = "other"

        if base_id <= 34:
            category = "stat" if base_id <= 5 else "aptitude"
            name = STAT_MAP.get(base_id, name)
        elif bid_str in skill_data:
            category = "skill"
            name = skill_entry_name(skill_data[bid_str])

        results.append({"name": name, "stars": stars, "id": base_id, "category": category})

    return [
        factor for _, factor in sorted(
            enumerate(results),
            key=lambda item: (CATEGORY_ORDER.get(item[1]["category"], 99), item[0])
        )
    ]
