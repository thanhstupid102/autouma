import re
from typing import Any

from uma_api.session import Session

from backend.app.domain import rank_point as rp


RENTAL_MAX_DEFAULT = 5


def parse_rental_parent(user_trained_chara, lineage_entry=None):
    """A friend's borrowable trained character -> compact dict, or None.

    `user_trained_chara` (from the friend summary) only carries the parent's OWN
    factors. The full grandparent lineage lives in a separate
    succession_trained_chara_array; when a matching `lineage_entry` is supplied
    (it has succession_chara_array), build the complete self/p1/p2/gp tree.
    Otherwise fall back to a self-only tree.
    """
    utc = user_trained_chara or {}
    tcid = utc.get("trained_chara_id")
    if not tcid:
        return None
    cid = utc.get("card_id")
    factors = rp.get_factors(utc.get("factor_id_array", []), cid)
    if lineage_entry and lineage_entry.get("succession_chara_array"):
        tree = rp.build_chara_tree(lineage_entry, lineage_entry.get("card_id", cid))
    else:
        tree = {
            "self": {
                "card_id": cid,
                "name": rp.chara_map.get(str(cid), f"Unknown ({cid})"),
                "factors": factors,
                "wins": rp.get_win_summary(utc.get("win_saddle_id_array", [])),
            }
        }
    return {
        "trained_chara_id": tcid,
        "card_id": cid,
        "name": rp.chara_map.get(str(cid), f"Unknown ({cid})"),
        "rank": utc.get("rank", 0),
        "rarity": utc.get("rarity", 0),
        "talent_level": utc.get("talent_level", 0),
        "factors": factors,
        "tree": tree,
    }


def read_rental_quota(data):
    """Daily friend-parent rental quota from a load/index data dict. Never raises."""
    data = data or {}
    used = int(data.get("single_mode_rental_succession_num") or 0)
    common = data.get("common_define") or {}
    max_num = int(common.get("single_mode_trained_chara_rental_max_num") or RENTAL_MAX_DEFAULT)
    remaining = max(0, max_num - used)
    return {"used": used, "max": max_num, "remaining": remaining}


def decide_rental(preset_vid, friends, quota):
    """Return (rental_viewer_id, rental_trained_chara_id) or (0, 0) to fall back."""
    preset_vid = int(preset_vid or 0)
    if not preset_vid:
        return (0, 0)
    if int((quota or {}).get("remaining") or 0) <= 0:
        return (0, 0)
    match = next((f for f in (friends or []) if int(f.get("viewer_id") or 0) == preset_vid), None)
    if not match:
        return (0, 0)
    rp = match.get("rental_parent")
    tcid = (rp or {}).get("trained_chara_id") if rp else None
    if not tcid:
        return (0, 0)
    return (preset_vid, int(tcid))


EVENT_DIFFICULTY_BASE = 400


def detect_event_difficulty(load_data, server_time=None):
    """Read active single-mode event difficulty from load/index data. Never raises."""
    data = load_data or {}
    arr = data.get("single_mode_difficulty_info_array") or []
    if not arr:
        return {"available": False, "difficulty_id": 0, "max_level": 0}
    first = arr[0] or {}
    did = int(first.get("difficulty_id") or 0)
    max_level = int(first.get("open_difficulty_index") or 0)
    if not did or max_level <= 0:
        return {"available": False, "difficulty_id": 0, "max_level": 0}
    return {"available": True, "difficulty_id": did, "max_level": max_level}


def event_difficulty_payload(enabled, level, boost, detect):
    """Map the runtime event selection to (difficulty_id, difficulty, is_boost).
    Returns (0, 0, 0) to run a normal career. difficulty = 400 + clamped level."""
    detect = detect or {}
    if not enabled or not detect.get("available"):
        return (0, 0, 0)
    max_level = int(detect.get("max_level") or 1)
    lvl = max(1, min(int(level or 1), max_level))
    return (int(detect.get("difficulty_id") or 0), EVENT_DIFFICULTY_BASE + lvl, 1 if boost else 0)


def normalize_friend_cards(data, session=None):
    source = 'refresh'
    friend_data = data.get('friend_support_card_data')
    friend_summaries = (friend_data or {}).get('summary_user_info_array', []) if friend_data else []
    top_summaries = data.get('summary_user_info_array', [])
    if friend_data:
        source = 'initial'
        summaries = friend_summaries
        support_cards = friend_data.get('support_card_data_array', [])
    else:
        summaries = top_summaries
        support_cards = data.get('support_card_data_array', [])

    support_by_key = {}
    for sc in support_cards or []:
        key = (sc.get('viewer_id'), sc.get('support_card_id'))
        support_by_key[key] = sc

    # Initial pre_single_mode nests the friend cards under friend_support_card_data,
    # while the borrowable trained chara can arrive on a top-level summary. Merge
    # both summary sources by viewer so rental parents load before any refresh.
    # str(viewer_id) -> that summary's raw `user_trained_chara` block.
    trained_chara_by_viewer: dict[str, Any] = {}
    for summary_source in (friend_summaries, top_summaries):
        for summary in summary_source or []:
            viewer_id = summary.get('viewer_id')
            if not viewer_id:
                continue
            user_trained_chara = summary.get('user_trained_chara')
            if not user_trained_chara:
                continue
            current = trained_chara_by_viewer.get(str(viewer_id))
            current_id = (current or {}).get('trained_chara_id')
            next_id = (user_trained_chara or {}).get('trained_chara_id')
            if next_id or not current_id:
                trained_chara_by_viewer[str(viewer_id)] = user_trained_chara

    # Full grandparent lineage for friend parents lives in a separate block,
    # keyed by (viewer_id, trained_chara_id). Build a lookup so each friend's
    # borrowable parent can show its complete spark tree when available.
    lineage_by_key = {}
    stcd = data.get('succession_trained_chara_data') or {}
    for entry in stcd.get('succession_trained_chara_array', []) or []:
        lkey = (str(entry.get('viewer_id')), entry.get('trained_chara_id'))
        lineage_by_key[lkey] = entry

    friends = []
    exclude_viewer_ids = []
    seen = set()
    for info in summaries or []:
        viewer_id = info.get('viewer_id')
        support_card_id = info.get('support_card_id')
        if not viewer_id or not support_card_id:
            continue
        key = (viewer_id, support_card_id)
        if key in seen:
            continue
        seen.add(key)
        exclude_viewer_ids.append(viewer_id)
        card_data = support_by_key.get(key) or info.get('user_support_card') or {}
        support_info = rp.support_map.get(str(support_card_id), {})
        user_trained_chara = trained_chara_by_viewer.get(str(viewer_id)) or info.get('user_trained_chara')
        trained_chara_id = (user_trained_chara or {}).get('trained_chara_id')
        lineage_entry = lineage_by_key.get((str(viewer_id), trained_chara_id))
        rental_parent = parse_rental_parent(user_trained_chara, lineage_entry)
        if session is not None and rental_parent:
            rp.cache_rental_parent_rank_point_data(
                session, viewer_id, user_trained_chara, lineage_entry
            )
        friends.append({
            'viewer_id': viewer_id,
            'name': info.get('name', ''),
            'support_card_id': support_card_id,
            'support_name': support_info.get('name', f"Unknown ({support_card_id})"),
            'rarity': support_info.get('rarity', '?'),
            'type': rp.display_support_type(support_info.get('type', 'Unknown')),
            'exp': card_data.get('exp', info.get('user_support_card', {}).get('exp')),
            'limit_break_count': card_data.get('limit_break_count', info.get('user_support_card', {}).get('limit_break_count')),
            'favorite_flag': card_data.get('favorite_flag', 0),
            'friend_state': info.get('friend_state', 0),
            'rental_parent': rental_parent,
        })
    return friends, exclude_viewer_ids, source


def normalize_card_name(name):
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'\([^)]*\)', '', str(name or '').lower()))


def validate_start_selection(session: Session, req):
    support_ids = [int(card_id) for card_id in req.support_card_ids]
    friend_card_id = int(req.friend_card_id)
    if friend_card_id in support_ids:
        return "Friend support card is already in selected deck"

    friend_info = rp.support_map.get(str(friend_card_id), {})
    friend_name = normalize_card_name(friend_info.get('name'))
    if friend_name:
        for support_id in support_ids:
            support_name = normalize_card_name(rp.support_map.get(str(support_id), {}).get('name'))
            if support_name and support_name == friend_name:
                return "Friend support card has same character as selected deck"

        trainee_name = normalize_card_name(rp.chara_map.get(str(req.card_id), ''))
        if trainee_name and trainee_name == friend_name:
            return "Friend support card has same character as trainee"

    parent1_cards = session.parent_cards.get(int(req.parent_id_1), [])
    parent2_cards = session.parent_cards.get(int(req.parent_id_2), [])
    trainee_id = int(req.card_id)
    if parent1_cards and parent2_cards and trainee_id in (parent1_cards[0], parent2_cards[0]):
        return "Selected direct parent is same character as trainee"

    return None


_DECK_TYPE_INDEX = {"Speed": 0, "Stamina": 1, "Power": 2, "Guts": 3, "Wisdom": 4}


def deck_type_counts_from_ids(support_ids, friend_card_id=0):
    counts = [0] * 5
    for sid_int in list(support_ids or []) + ([friend_card_id] if friend_card_id else []):
        info = rp.support_map.get(str(sid_int))
        if not info:
            continue
        # Raw support-card catalog row: `type` may be absent, and the resulting
        # `.get(None)` miss is the deliberate "unknown deck type -> skip" path
        # below. Typed Any so that stays the control flow, not a None check.
        deck_type: Any = info.get('type')
        idx = _DECK_TYPE_INDEX.get(deck_type)
        if idx is not None:
            counts[idx] += 1
    return counts


def deck_type_counts_from_chara(chara_info):
    ids = []
    for card in (chara_info or {}).get('support_card_array') or []:
        sid = int(card.get('support_card_id') or 0)
        if sid:
            ids.append(sid)
    return deck_type_counts_from_ids(ids)


def apply_deck_type_counts(preset, req=None, chara_info=None):
    counts = None
    if req and (req.support_card_ids or req.friend_card_id):
        counts = deck_type_counts_from_ids(req.support_card_ids, req.friend_card_id)
    elif chara_info:
        counts = deck_type_counts_from_chara(chara_info)
    if counts is not None:
        preset["_deck_type_counts"] = counts
        scale_table = [0.0, 0.02, 0.05, 0.09, 0.14, 0.20]
        preset["_deck_multipliers"] = [1.0 + scale_table[min(5, c)] for c in counts]
