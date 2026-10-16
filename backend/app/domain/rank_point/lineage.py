import backend.app.domain.rank_point as rp
from core.runtime_paths import resolve_master_json_path


skill_data_path = resolve_master_json_path(
    rp.base_dir, 'skill_data.json', rp.state_root,
)
factor_map_path = resolve_master_json_path(
    rp.base_dir, 'factor_map.json', rp.state_root,
)
race_map_path = resolve_master_json_path(
    rp.base_dir, 'race_map.json', rp.state_root,
)


def skill_entry_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or ""
    return entry


def get_win_summary(win_saddle_ids):
    summary = {
        "g1": 0,
        "g2": 0,
        "g3": 0
    }

    for saddle_id in win_saddle_ids or []:
        race = rp.race_map.get(str(saddle_id))
        grade = race.get("grade") if race else None
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1

    summary["total"] = summary["g1"] + summary["g2"] + summary["g3"]
    return summary


def clean_factor_name(name, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = rp.skill_entry_name(rp.skill_data.get(f"{base_id}2"))
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")


def get_factors(fid_array, owner_card_id=None):
    return rp.parse_factor_ids(
        fid_array,
        factor_map=rp.factor_map,
        skill_data=rp.skill_data,
        owner_card_id=owner_card_id,
    )


def get_chara_factor_ids(chara):
    factor_ids = chara.get('factor_id_array')
    if isinstance(factor_ids, list) and factor_ids:
        return factor_ids
    return [f.get('factor_id', 0) for f in chara.get('factor_info_array', []) or []]


_SUCCESSION_POS_KEY = {10: "p1", 20: "p2", 11: "gp1", 12: "gp2", 21: "gp3", 22: "gp4"}


def lineage_by_trained_chara_id(data):
    stcd = (data or {}).get('succession_trained_chara_data') or {}
    by_id = {}
    for entry in stcd.get('succession_trained_chara_array', []) or []:
        if not isinstance(entry, dict):
            continue
        trained_chara_id = entry.get('trained_chara_id')
        if trained_chara_id in (None, ''):
            continue
        by_id[str(trained_chara_id)] = entry
    return by_id


def merge_chara_lineage(chara, lineage_entry=None):
    if not isinstance(chara, dict) or not isinstance(lineage_entry, dict):
        return chara

    merged = None

    def out():
        nonlocal merged
        if merged is None:
            merged = dict(chara)
        return merged

    def missing(value):
        return value is None or value == '' or value == []

    if not chara.get('succession_chara_array') and lineage_entry.get('succession_chara_array'):
        out()['succession_chara_array'] = lineage_entry.get('succession_chara_array')
    for key in ('factor_id_array', 'factor_info_array', 'win_saddle_id_array', 'card_id', 'rank', 'rank_score'):
        if (key not in chara or missing(chara.get(key))) and not missing(lineage_entry.get(key)):
            out()[key] = lineage_entry.get(key)
    return merged or chara


def build_chara_tree(chara, cid):
    """self/p1/p2/gp1-4 lineage tree from a trained-chara dict (has succession_chara_array)."""
    cid = str(cid)
    tree = {
        "self": {"card_id": cid, "name": rp.chara_map.get(cid, f"Unknown ({cid})"), "factors": [], "wins": rp.get_win_summary(chara.get('win_saddle_id_array', []))},
        "p1": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
        "p2": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
        "gp1": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
        "gp2": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
        "gp3": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
        "gp4": {"card_id": 0, "name": "", "factors": [], "wins": rp.get_win_summary([])},
    }
    tree["self"]["factors"] = rp.get_factors(rp.get_chara_factor_ids(chara), cid)
    for sc in chara.get('succession_chara_array', []) or []:
        key = _SUCCESSION_POS_KEY.get(sc.get('position_id'))
        if not key:
            continue
        sc_cid = sc.get('card_id', 0)
        tree[key]["card_id"] = sc_cid
        tree[key]["name"] = rp.chara_map.get(str(sc_cid), f"Unknown ({sc_cid})")
        tree[key]["factors"] = rp.get_factors(rp.get_chara_factor_ids(sc), sc_cid)
        tree[key]["wins"] = rp.get_win_summary(sc.get('win_saddle_id_array', []))
    return tree
