from typing import Any

from uma_api.session import Session

from backend.app.domain import rank_point as rp


def set_cached_user_item_count(session: Session, item_id, count):
    try:
        iid = int(item_id)
        value = max(int(count or 0), 0)
    except (TypeError, ValueError):
        return
    cache = getattr(session, "user_info_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        session.user_info_cache = cache
    item_map = cache.get("item_map")
    if not isinstance(item_map, dict):
        item_map = {}
        cache["item_map"] = item_map
    item_map[iid] = value
    if iid == TP_BOTTLE_ITEM_ID:
        cache["tp_bottle_count"] = value


def cache_user_info(session: Session, data):
    if not data:
        return
    cache = getattr(session, "user_info_cache", None)
    if not isinstance(cache, dict):
        cache = {}
    for key in ("user_info", "tp_info", "coin_info"):
        value = data.get(key)
        if isinstance(value, dict):
            cache[key] = dict(value)
    session.user_info_cache = cache
    item_list = _account_item_rows(data)
    if any(isinstance((data or {}).get(key), list) for key in ('item_list', 'user_item_array', 'user_item')):
        # Career responses carry partial item deltas, including empty arrays.
        # Preserve omitted counts and update only items the response names.
        cache["item_list"] = [dict(item) for item in item_list if isinstance(item, dict)]
        for item in cache["item_list"]:
            iid = item.get("item_id")
            for count_key in ("number", "num", "current_num", "item_num"):
                if count_key in item:
                    set_cached_user_item_count(session, iid, item.get(count_key))
                    break


def update_start_state(session: Session, data):
    if not data:
        return
    cache_user_info(session, data)
    if data.get('tp_info'):
        tp_info = dict(data.get('tp_info'))
        session.start_state['tp_info'] = tp_info
    item_list = _account_item_rows(data)
    if any(isinstance(data.get(key), list) for key in ('item_list', 'user_item_array', 'user_item')):
        session.start_state['current_money'] = get_item_count(item_list, 59)
        session.start_state['succession_rank_point'] = get_item_count(item_list, 75)
        bottle_count = _item_count_from_rows(item_list, TP_BOTTLE_ITEM_ID, None)
        if bottle_count is not None:
            session.start_state['tp_bottle_count'] = bottle_count


# Plain TP bottle (master item_data id 32, +30 TP). Auto-spend these before
# carats. The Valentine chocolates (10001-10068) share the +30 TP effect but are
# rare collectibles -- never auto-spend them.
TP_BOTTLE_ITEM_ID = 32


def _account_item_rows(data):
    for key in ('item_list', 'user_item_array', 'user_item'):
        rows = (data or {}).get(key)
        if isinstance(rows, list):
            return rows
    return []


def _item_count_from_rows(item_list, item_id, missing=0):
    for item in item_list or []:
        if not isinstance(item, dict):
            continue
        try:
            # Raw server field: when absent this is None and int() raises
            # TypeError, which the except below is the deliberate handler for.
            # Typed Any so that stays the control flow rather than becoming a
            # None check (which would change behaviour, not just types).
            raw_id: Any = item.get('item_id')
            if int(raw_id) != int(item_id):
                continue
        except (TypeError, ValueError):
            continue
        for key in ('number', 'num', 'current_num', 'item_num'):
            if key in item:
                try:
                    return max(int(item.get(key) or 0), 0)
                except (TypeError, ValueError):
                    return 0
        return 0
    return missing


def get_item_count(item_list, item_id):
    return _item_count_from_rows(item_list, item_id)


def get_account_status(session: Session, data, career_data=None):
    client = session.client
    tp_info = data.get('tp_info') or (client.tp_info if client else {})
    coin_info = data.get('coin_info') or (client.coin_info if client else {})
    item_list = _account_item_rows(data)
    if not any(isinstance((data or {}).get(key), list) for key in ('item_list', 'user_item_array', 'user_item')):
        gold = client.item_map.get(59, 0) if client else 0
    else:
        gold = get_item_count(item_list, 59)
    career = data.get('single_mode_chara_light') or None

    if career_data:
        career_payload = career_data.get('data') if career_data.get('data') else career_data
        if career_payload.get('chara_info'):
            career = career_payload.get('chara_info')

    status = {
        "tp": {
            "current": tp_info.get('current_tp', 0),
            "max": tp_info.get('max_tp', 0)
        },
        "carrots": {
            "free": coin_info.get('fcoin', 0) or 0,
            "paid": coin_info.get('coin', 0) or 0,
            "total": (coin_info.get('fcoin', 0) or 0) + (coin_info.get('coin', 0) or 0)
        },
        "gold": gold,
        "clocks": client.item_map.get(95, 0) if client else 0,
        "career": None
    }
    if career:
        card_id = str(career.get('card_id', ''))

        p1 = career.get('succession_trained_chara_id_1')
        p2 = career.get('succession_trained_chara_id_2')

        friend_viewer_id = None
        friend_card_id = None
        friend_support = None
        current_deck_cards = []
        current_deck_supports = []

        support_array = career.get('support_card_array') or []
        for sc in support_array:
            pos = sc.get('position')
            if pos == 6:
                friend_viewer_id = sc.get('owner_viewer_id')
                friend_card_id = sc.get('support_card_id')
                friend_info = rp.support_map.get(str(friend_card_id))
                friend_support = {
                    "viewer_id": friend_viewer_id,
                    "support_card_id": friend_card_id,
                    "support_name": friend_info['name'] if friend_info else f"Unknown ({friend_card_id})",
                    "rarity": friend_info['rarity'] if friend_info else "?",
                    "type": rp.display_support_type(friend_info['type']) if friend_info else "?",
                    "limit_break_count": sc.get('limit_break_count')
                }
            elif 1 <= pos <= 5:
                support_card_id = sc.get('support_card_id')
                current_deck_cards.append(support_card_id)
                support_info = rp.support_map.get(str(support_card_id))
                current_deck_supports.append({
                    "id": str(support_card_id),
                    "name": support_info['name'] if support_info else f"Unknown ({support_card_id})",
                    "rarity": support_info['rarity'] if support_info else "?",
                    "type": rp.display_support_type(support_info['type']) if support_info else "?"
                })

        matched_deck_id = None
        user_decks = data.get('support_card_deck_array') or []
        if current_deck_cards:
            current_deck_set = set(current_deck_cards)
            for deck in user_decks:
                deck_cards = deck.get('support_card_id_array') or []
                if set(deck_cards) == current_deck_set:
                    matched_deck_id = deck.get('deck_id')
                    break

        status["career"] = {
            "active": True,
            "card_id": card_id,
            "name": rp.chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": career.get('turn', 0),
            "scenario_id": career.get('scenario_id', 0),
            "fans": career.get('fans', 0),
            "vital": career.get('vital', 0),
            "max_vital": career.get('max_vital', 0),
            "deck_id": matched_deck_id,
            "support_card_ids": current_deck_cards,
            "support_cards": current_deck_supports,
            "friend_viewer_id": friend_viewer_id,
            "friend_card_id": friend_card_id,
            "friend": friend_support,
            "parent_id_1": p1,
            "parent_id_2": p2,
        }

    return status


def unwrap_single_mode_start_common(result):
    """Promote wrapped career-start state while preserving sibling data."""
    if not isinstance(result, dict):
        return result
    data = result.get("data")
    if not isinstance(data, dict) or data.get("chara_info"):
        return result
    start_common = data.get("single_mode_start_common")
    if not isinstance(start_common, dict) or not start_common.get("chara_info"):
        return result

    merged = dict(start_common)
    for key, value in data.items():
        if key != "single_mode_start_common":
            merged[key] = value
    unwrapped = dict(result)
    unwrapped["data"] = merged
    return unwrapped


def apply_career_result(session: Session, result):
    result_data = result.get('data', {})
    update_start_state(session, result_data)
    account = get_account_status(session, result_data, result)
    chara_info = result_data.get('chara_info') or {}
    if chara_info:
        account["career"] = account.get("career") or {}
        card_id = str(chara_info.get('card_id', account["career"].get("card_id", '')))
        account["career"].update({
            "active": True,
            "card_id": card_id,
            "name": rp.chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": chara_info.get('turn', 0),
            "scenario_id": chara_info.get('scenario_id', 0),
            "fans": chara_info.get('fans', 0),
            "vital": chara_info.get('vital', 0),
            "max_vital": chara_info.get('max_vital', 0)
        })
    session.account = account
    if session.dashboard_data:
        session.dashboard_data["account"] = account
    return account, chara_info


def result_scenario_id(result):
    data = (result or {}).get('data') or {}
    for key in ('chara_info', 'single_mode_chara_light', 'single_mode_chara'):
        chara = data.get(key)
        if isinstance(chara, dict) and chara.get('scenario_id'):
            return int(chara.get('scenario_id') or 0)
    return 0
