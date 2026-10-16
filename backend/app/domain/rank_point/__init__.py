import json  # noqa: F401
import logging
import threading

from datetime import datetime, timezone  # noqa: F401
from pathlib import Path  # noqa: F401
from typing import Any, cast

from career_bot.delay import dna_sleep  # noqa: F401
from career_bot.planning.factors import parse_factor_ids  # noqa: F401
from uma_api import game_service  # noqa: F401
from uma_api.errors import api_error_result_code  # noqa: F401
from uma_api.session import Session
import uma_data

from core.runtime_paths import resolve_master_json_path, resolve_state_root
from core.settings import Settings


log = logging.getLogger(__name__)

base_dir: Path = Settings.BASE_DIR
state_root: Path = resolve_state_root(base_dir).root

chara_map: dict[str, str] = {}
support_map: dict[str, dict] = {}
succession_relation_points: dict[int, int] = {}
succession_relation_members: dict[int, set[int]] = {}
succession_relation_loaded = False
g1_win_saddle_ids: set[int] = set()
win_saddle_groups: dict[int, int] = {}
win_saddle_types: dict[int, int] = {}
g1_win_saddle_loaded = False
rank_point_master_mdb_mtime_ns = None
rank_point_master_data_lock = threading.Lock()
rank_point_probe_log_lock = threading.Lock()
RANKPOINT_PROBE_LOG_PATH = None

chara_path = resolve_master_json_path(base_dir, 'chara_list.json', state_root)
support_path = resolve_master_json_path(base_dir, 'support_list.json', state_root)


def load_succession_relation_data():
    global succession_relation_points, succession_relation_members, succession_relation_loaded
    result = uma_data.load_succession_relations(base_dir)
    if not result.get("success"):
        succession_relation_points = {}
        succession_relation_members = {}
        succession_relation_loaded = False
        return False
    succession_relation_points = result.get("points") or {}
    succession_relation_members = result.get("members") or {}
    succession_relation_loaded = True
    return True


def load_g1_win_saddle_data():
    global g1_win_saddle_ids, win_saddle_groups, win_saddle_types, g1_win_saddle_loaded
    result = uma_data.load_g1_win_saddle_ids(base_dir)
    if not result.get("success"):
        g1_win_saddle_ids = set()
        win_saddle_groups = {}
        win_saddle_types = {}
        g1_win_saddle_loaded = False
        return False
    g1_win_saddle_ids = result.get("g1_saddle_ids") or set()
    win_saddle_groups = result.get("saddle_groups") or {}
    win_saddle_types = result.get("saddle_types") or {}
    g1_win_saddle_loaded = True
    return True


def display_support_type(value):
    return {
        "Friends": "Pal",
        "Wisdom": "Wit"
    }.get(value, value)


def g1_win_saddle_id_set(win_saddle_id_array):
    """Return unique G1 saddle IDs, or an empty set without G1 master data."""
    if not g1_win_saddle_loaded:
        return set()
    result = set()
    for saddle_id in win_saddle_id_array or []:
        saddle_id = int(saddle_id)
        if saddle_id in g1_win_saddle_ids:
            result.add(saddle_id)
    return result


def shared_g1_group_count(left_win_saddle_ids, right_win_saddle_ids):
    """Count the client's directional G1/group matches.

    Every left-side G1 entry counts once when any right-side entry has the same
    ``single_mode_wins_saddle.group_id``.  The right entry need not itself be
    G1, and duplicate left entries are deliberately not collapsed.
    """
    if not g1_win_saddle_loaded:
        return 0
    right_groups = set()
    for raw_saddle_id in right_win_saddle_ids or []:
        try:
            saddle_id = int(raw_saddle_id)
        except (TypeError, ValueError):
            continue
        if saddle_id in win_saddle_groups:
            right_groups.add(win_saddle_groups[saddle_id])

    count = 0
    for raw_saddle_id in left_win_saddle_ids or []:
        try:
            saddle_id = int(raw_saddle_id)
        except (TypeError, ValueError):
            continue
        if (
            win_saddle_types.get(saddle_id) == 3
            and win_saddle_groups.get(saddle_id) in right_groups
        ):
            count += 1
    return count


def parent_shared_g1_bonus(chara):
    """Return the G1/group bonus for a parent and its direct grandparents.

    Each left-side parent G1 whose group occurs in a direct grandparent's win
    array is worth 3 points. Great-grandparent positions do not contribute.
    """
    shared_count = 0
    for sc in chara.get('succession_chara_array') or []:
        if int(sc.get('position_id') or 0) in (10, 20):
            shared_count += shared_g1_group_count(
                chara.get('win_saddle_id_array'),
                sc.get('win_saddle_id_array'),
            )
    return 3 * shared_count


def parent_pair_shared_g1_bonus(parent_1, parent_2):
    """Directional G1/group bonus from parent 1's wins to parent 2's wins."""
    if not isinstance(parent_1, dict) or not isinstance(parent_2, dict):
        return 0
    return 3 * shared_g1_group_count(
        parent_1.get('win_saddle_id_array'),
        parent_2.get('win_saddle_id_array'),
    )


def chara_base_id(card_id):
    return int(card_id or 0) // 100


def relation_point(*card_ids):
    """Sum relation types shared by every distinct base character supplied."""
    if not succession_relation_loaded:
        return 0
    base_ids = [chara_base_id(card_id) for card_id in card_ids]
    if not base_ids or any(not base_id for base_id in base_ids):
        return 0
    # GetRelationList(a,b,c) returns an empty list when any IDs repeat. The
    # two-argument overload behaves the same for a == b.
    if len(set(base_ids)) != len(base_ids):
        return 0
    common_relations = set(succession_relation_members.get(base_ids[0], set()))
    for base_id in base_ids[1:]:
        common_relations.intersection_update(
            succession_relation_members.get(base_id, set())
        )
    return sum(
        int(succession_relation_points.get(relation_id) or 0)
        for relation_id in common_relations
    )


def relation_pair_point(card_id_a, card_id_b):
    return relation_point(card_id_a, card_id_b)


def relation_triple_point(card_id_a, card_id_b, card_id_c):
    return relation_point(card_id_a, card_id_b, card_id_c)


def direct_grandparent_cards(parent_source):
    result = {10: 0, 20: 0}
    if not isinstance(parent_source, dict):
        return result
    for chara in parent_source.get('succession_chara_array') or []:
        position_id = int(chara.get('position_id') or 0)
        if position_id in result:
            result[position_id] = int(chara.get('card_id') or 0)
    return result


def parent_direct_card(session: Session, parent_id):
    parent_cards = session.parent_cards.get(int(parent_id), [])
    if not parent_cards:
        return 0
    return parent_cards[0]


def reload_rank_point_master_data_if_changed():
    """Reload relation/G1 lookup tables once when master.mdb is replaced."""
    global rank_point_master_mdb_mtime_ns

    current_mtime_ns = uma_data.master_mdb_mtime_ns(base_dir)
    if current_mtime_ns == rank_point_master_mdb_mtime_ns:
        return False

    with rank_point_master_data_lock:
        current_mtime_ns = uma_data.master_mdb_mtime_ns(base_dir)
        if current_mtime_ns == rank_point_master_mdb_mtime_ns:
            return False
        relation_ok = load_succession_relation_data()
        g1_ok = load_g1_win_saddle_data()
        if not (relation_ok and g1_ok):
            log.warning(
                "[RANKPOINT] master.mdb changed but relation/G1 reload failed; will retry"
            )
            return False
        rank_point_master_mdb_mtime_ns = current_mtime_ns
        log.info("master.mdb changed -> reloaded relation/G1 data")
        return True


def _selected_parent_source(session: Session, parent_id, rental_key=None):
    if rental_key is None:
        return getattr(session, "parent_g1_sources", {}).get(parent_id)
    return getattr(session, "rental_parent_g1_sources", {}).get(rental_key)


def _selected_parent_g1_bonus(session: Session, parent_id, rental_key=None):
    source = _selected_parent_source(
        session, parent_id, rental_key=rental_key
    )
    cache = (
        session.parent_g1_wins
        if rental_key is None else session.rental_parent_g1_wins
    )
    key = parent_id if rental_key is None else rental_key
    if source is not None:
        cache[key] = parent_shared_g1_bonus(source)
    return int(cache.get(key, 0) or 0)


def selected_succession_rank_point_components(session: Session, req, rental_parent_2=None):
    """Return the exact rank-point value and the components used to compute it."""
    reload_rank_point_master_data_if_changed()

    parent1_id = int(req.parent_id_1)
    parent1_source = _selected_parent_source(session, parent1_id)
    parent1_card = parent_direct_card(session, parent1_id)
    if not parent1_card and isinstance(parent1_source, dict):
        parent1_card = int(parent1_source.get('card_id') or 0)
    parent1_g1_bonus = _selected_parent_g1_bonus(session, parent1_id)
    rental_viewer_id = 0
    rental_trained_chara_id = 0
    if rental_parent_2 is None:
        parent2_id = int(req.parent_id_2)
        parent2_source = _selected_parent_source(session, parent2_id)
        parent2_card = parent_direct_card(session, parent2_id)
        if not parent2_card and isinstance(parent2_source, dict):
            parent2_card = int(parent2_source.get('card_id') or 0)
        parent2_g1_bonus = _selected_parent_g1_bonus(session, parent2_id)
    else:
        rental_viewer_id = int(rental_parent_2[0])
        rental_trained_chara_id = int(rental_parent_2[1])
        rental_key = (rental_viewer_id, rental_trained_chara_id)
        parent2_source = _selected_parent_source(
            session, rental_trained_chara_id, rental_key=rental_key
        )
        rental_cards = session.rental_parent_cards.get(rental_key, [])
        parent2_id = rental_trained_chara_id
        parent2_card = rental_cards[0] if rental_cards else 0
        if not parent2_card and isinstance(parent2_source, dict):
            parent2_card = int(parent2_source.get('card_id') or 0)
        parent2_g1_bonus = _selected_parent_g1_bonus(
            session, parent2_id, rental_key=rental_key
        )

    relation_pairs = {
        "t_p1": relation_pair_point(req.card_id, parent1_card) if parent1_card else 0,
        "t_p2": relation_pair_point(req.card_id, parent2_card) if parent2_card else 0,
        "p1_p2": relation_pair_point(parent1_card, parent2_card)
        if parent1_card and parent2_card else 0,
    }
    parent1_grandparents = direct_grandparent_cards(parent1_source)
    parent2_grandparents = direct_grandparent_cards(parent2_source)
    relation_triples = {
        "t_p1_gp10": relation_triple_point(
            req.card_id, parent1_card, parent1_grandparents[10]
        ) if parent1_card and parent1_grandparents[10] else 0,
        "t_p1_gp20": relation_triple_point(
            req.card_id, parent1_card, parent1_grandparents[20]
        ) if parent1_card and parent1_grandparents[20] else 0,
        "t_p2_gp10": relation_triple_point(
            req.card_id, parent2_card, parent2_grandparents[10]
        ) if parent2_card and parent2_grandparents[10] else 0,
        "t_p2_gp20": relation_triple_point(
            req.card_id, parent2_card, parent2_grandparents[20]
        ) if parent2_card and parent2_grandparents[20] else 0,
    }
    relation_total = sum(relation_pairs.values()) + sum(relation_triples.values())
    parent_pair_g1_bonus = parent_pair_shared_g1_bonus(
        parent1_source, parent2_source
    )
    g1_bonus_total = (
        parent1_g1_bonus + parent2_g1_bonus + parent_pair_g1_bonus
    )
    formula_total = relation_total + g1_bonus_total
    used_account_fallback = not (formula_total or parent1_card or parent2_card)
    computed = (
        int(session.start_state.get('succession_rank_point', 0) or 0)
        if used_account_fallback else formula_total
    )
    return {
        "card_id": int(req.card_id),
        "parent_1": {
            "trained_chara_id": parent1_id,
            "card_id": int(parent1_card or 0),
            "g1_bonus": parent1_g1_bonus,
        },
        "parent_2": {
            "trained_chara_id": parent2_id,
            "requested_trained_chara_id": int(req.parent_id_2),
            "card_id": int(parent2_card or 0),
            "g1_bonus": parent2_g1_bonus,
        },
        "rental": {
            "viewer_id": rental_viewer_id,
            "trained_chara_id": rental_trained_chara_id,
        },
        "relation_pairs": relation_pairs,
        "relation_triples": relation_triples,
        "relation_total": relation_total,
        "parent_pair_g1_bonus": parent_pair_g1_bonus,
        "g1_bonus_total": g1_bonus_total,
        "formula_total": formula_total,
        "used_account_fallback": used_account_fallback,
        "computed": computed,
    }


def selected_succession_rank_point(session: Session, req, rental_parent_2=None):
    """Return the live client's ``current_succession_rank_point``.

    ``Gallop.SingleModeUtils.CalcRelationPoint`` sums relation intersections
    for trainee-parent pairs, four trainee-parent-direct-grandparent triples,
    and the parent-parent pair. It then adds 3 for each directional G1/group
    match in P1-GP10, P1-GP20, P2-GP10, P2-GP20, and P1-P2. There is no
    aptitude term and no clamp.
    """
    return selected_succession_rank_point_components(
        session, req, rental_parent_2=rental_parent_2
    )["computed"]


RANKPOINT_PROBE_OFFSETS = (64, 256, 1024, 4096)
RANKPOINT_PROBE_MAX_ATTEMPTS = 16


skill_data: dict[str, Any] = {}

factor_map: dict[str, Any] = {}

race_map: dict[str, dict] = {}


def cache_rental_parent_rank_point_data(session: Session, viewer_id, chara, lineage_entry=None):
    """Cache a friend's card and rank-point lineage in its account namespace."""
    if not isinstance(chara, dict):
        return False
    try:
        rental_key = (int(viewer_id), int(cast(Any, chara.get('trained_chara_id'))))
    except (TypeError, ValueError):
        return False

    tree_source = merge_chara_lineage(chara, lineage_entry)
    try:
        lineage_cards = [int(cast(Any, tree_source.get('card_id')))]
    except (TypeError, ValueError):
        return False
    for sc in tree_source.get('succession_chara_array', []) or []:
        try:
            card_id = int(sc.get('card_id'))
        except (TypeError, ValueError):
            continue
        if card_id:
            lineage_cards.append(card_id)

    session.rental_parent_cards[rental_key] = lineage_cards
    session.rental_parent_g1_wins[rental_key] = parent_shared_g1_bonus(tree_source)
    rental_sources = getattr(session, "rental_parent_g1_sources", None)
    if not isinstance(rental_sources, dict):
        rental_sources = {}
        session.rental_parent_g1_sources = rental_sources
    rental_sources[rental_key] = tree_source
    return True


from .lineage import (  # noqa: E402, F401
    _SUCCESSION_POS_KEY as _SUCCESSION_POS_KEY,
    build_chara_tree as build_chara_tree,
    clean_factor_name as clean_factor_name,
    factor_map_path as factor_map_path,
    get_chara_factor_ids as get_chara_factor_ids,
    get_factors as get_factors,
    get_win_summary as get_win_summary,
    lineage_by_trained_chara_id as lineage_by_trained_chara_id,
    merge_chara_lineage as merge_chara_lineage,
    race_map_path as race_map_path,
    skill_data_path as skill_data_path,
    skill_entry_name as skill_entry_name,
)
from .probe import (  # noqa: E402, F401
    _rankpoint_probe_log_path as _rankpoint_probe_log_path,
    persist_rankpoint_probe as persist_rankpoint_probe,
    probe_succession_rank_point as probe_succession_rank_point,
)
