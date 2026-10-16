"""Build the owned-veteran roster and its career-start lineage caches."""

import backend.app.domain.rank_point as rank_point


def build_parents(session, data):
    """Return dashboard parents and atomically replace the owned-parent caches.

    Login and on-demand refresh both use this function so the roster shape and
    the rank-point inputs consumed by career start cannot drift apart.
    """
    parents = []
    parent_cards = {}
    parent_rank_points = {}
    parent_g1_wins = {}
    parent_g1_sources = {}
    trained_chara_list = data.get("trained_chara", [])
    owned_lineage_by_id = rank_point.lineage_by_trained_chara_id(data)

    for chara in trained_chara_list:
        raw_id = str(chara.get("card_id", ""))

        if "{" in raw_id or "-" in raw_id or not raw_id.isdigit():
            found = False
            for value in chara.values():
                value_string = str(value)
                if value_string.isdigit() and len(value_string) >= 4:
                    raw_id = value_string
                    found = True
                    break
            if not found:
                continue

        card_id = raw_id
        tree_source = rank_point.merge_chara_lineage(
            chara,
            owned_lineage_by_id.get(str(chara.get("trained_chara_id"))),
        )
        tree = rank_point.build_chara_tree(tree_source, card_id)

        parents.append({
            "instance_id": chara.get("trained_chara_id"),
            "card_id": card_id,
            "name": rank_point.chara_map.get(card_id, f"Unknown ({card_id})"),
            "rank": chara.get("rank", 0),
            "is_locked": int(chara.get("is_locked") or 0),
            "tree": tree,
        })

        trained_chara_id = int(chara.get("trained_chara_id"))
        lineage_cards = [int(card_id)]
        for succession_chara in tree_source.get("succession_chara_array", []) or []:
            succession_card_id = succession_chara.get("card_id", 0)
            if succession_card_id:
                lineage_cards.append(int(succession_card_id))

        parent_cards[trained_chara_id] = lineage_cards
        parent_rank_points[trained_chara_id] = {
            "rank": chara.get("rank", 0),
            "rank_score": chara.get("rank_score", 0),
        }
        parent_g1_wins[trained_chara_id] = rank_point.parent_shared_g1_bonus(
            tree_source
        )
        parent_g1_sources[trained_chara_id] = tree_source

    session.parent_cards = parent_cards
    session.parent_rank_points = parent_rank_points
    session.parent_g1_wins = parent_g1_wins
    session.parent_g1_sources = parent_g1_sources
    return parents
