"""Grand Live tree-square catalog and picker.

The trainee earns Dance/Passion/Vocal/Visual/Mental tokens from training and
spends them on tree squares through `single_mode_live/master_square`. Which
squares are on offer comes from the live state (`next_square_info_array`);
what each one costs and pays out comes from master.mdb
(`uma_data.load_live_squares`).

Square tiers, from the master table: square_type 1/2/3 (Parameter/Skill/Hp)
are the repeatable common squares -- the 2026-07-26 capture bought ids like
11101 and 11102 five times each -- while the 21 square_type 4 rows
(40000-40020) are the rare unique songs, each of which the capture bought
exactly once.

The default fallback policy buys songs first, then parameters, then skills, then HP,
and prefers the cheapest square within a tier so a career lands as many of the
21 unique songs as its token income allows. Weights are preset-overridable;
tuning which *specific* song to chase is deliberately left to step 3.
"""

from __future__ import annotations

import uma_data

from career_bot.scenarios.grand_live.live_state import (
    PERFORMANCE_NAMES,
    SQUARE_HP,
    SQUARE_PARAMETER,
    SQUARE_SKILL,
    SQUARE_SONG,
    SQUARE_TYPE_NAMES,
)
from career_bot.scenarios.grand_live.song_policy import choose_contextual_square

# Tier preference, highest first. Songs are one-shot and unique, so they carry
# the most value per purchase; Parameter common squares now outrank Skill by
# default, while HP squares are the cheap filler. Kept in sync with
# career_bot.bot_config.GRAND_LIVE_DEFAULTS, which is what the Bot Config page
# edits.
DEFAULT_SQUARE_TYPE_WEIGHTS = {
    SQUARE_SONG: 400,
    SQUARE_SKILL: 100,
    SQUARE_PARAMETER: 200,
    SQUARE_HP: 50,
}

# Runtime preset key per square type. apply_bot_config_to_preset flattens the
# scenario-3 bot config into the preset, so these arrive top-level.
PRESET_WEIGHT_KEYS = {
    SQUARE_SONG: "grand_live_song_square_weight",
    SQUARE_SKILL: "grand_live_skill_square_weight",
    SQUARE_PARAMETER: "grand_live_parameter_square_weight",
    SQUARE_HP: "grand_live_hp_square_weight",
}


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _contextual_policy_enabled(preset):
    if not preset or "grand_live_contextual_square_policy" not in preset:
        return True
    value = preset.get("grand_live_contextual_square_policy")
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "0", "no", "off"}
    return value not in (False, 0, 0.0)


def resolve_weights(preset=None, weights=None):
    """Merge Bot Config / caller overrides over DEFAULT_SQUARE_TYPE_WEIGHTS.

    Preset keys come from the scenario-3 bot config; `weights` is a direct
    {square_type: weight} override and wins over both.
    """
    resolved = dict(DEFAULT_SQUARE_TYPE_WEIGHTS)
    preset = preset or {}
    for square_type, preset_key in PRESET_WEIGHT_KEYS.items():
        if preset.get(preset_key) is not None:
            resolved[square_type] = _int(preset.get(preset_key))
    if isinstance(weights, dict):
        for square_type, weight in weights.items():
            resolved[_int(square_type)] = _int(weight)
    return resolved


class SquareCatalog:
    """master.mdb-backed square/live lookup.

    Loads lazily and degrades to empty rather than raising when master.mdb is
    missing or predates the Grand Live tables -- callers treat an unknown
    square as unbuyable instead of crashing a live career.
    """

    def __init__(self, base_dir, master_mdb_path=None):
        self.base_dir = base_dir
        self.master_mdb_path = master_mdb_path
        self._loaded = False
        self._squares = {}
        self._lives = []
        self._success = False

    def load(self, force=False):
        if self._loaded and not force:
            return self
        result = uma_data.load_live_squares(self.base_dir, self.master_mdb_path) or {}
        self._success = bool(result.get("success"))
        self._squares = result.get("squares") or {}
        self._lives = result.get("lives") or []
        self._loaded = True
        return self

    @property
    def available(self):
        self.load()
        return self._success and bool(self._squares)

    def square(self, square_id):
        self.load()
        return self._squares.get(_int(square_id))

    def cost(self, square_id):
        return (self.square(square_id) or {}).get("cost") or {}

    def square_type(self, square_id):
        return _int((self.square(square_id) or {}).get("square_type"))

    def song_square_ids(self):
        self.load()
        return sorted(sid for sid, row in self._squares.items() if _int(row.get("square_type")) == SQUARE_SONG)

    @property
    def live_turns(self):
        """Turns that run a scheduled live (single_mode_live_live_data.turn_num).

        The 2026-07-26 capture fired live_start on exactly these turns.
        """
        self.load()
        return [_int(row.get("turn_num")) for row in self._lives if _int(row.get("turn_num"))]

    def is_live_turn(self, turn):
        return _int(turn) in set(self.live_turns)


def score_square(square, weights):
    """Rank key for an affordable square: tier first, then cheapest, then id.

    Returned as a tuple to be sorted descending, so cost and id are negated.
    """
    square_type = _int(square.get("square_type"))
    return (
        _int(weights.get(square_type)),
        -_int(square.get("cost_total")),
        -_int(square.get("id")),
    )


def rank_squares(catalog, live_state, offered_ids=None, preset=None, weights=None):
    """Offered squares split into affordable/unaffordable, best first.

    `offered_ids` defaults to the live state's next_square_info_array. Squares
    missing from master.mdb are reported separately rather than guessed at.
    """
    resolved = resolve_weights(preset, weights)
    ids = offered_ids if offered_ids is not None else live_state.next_square_ids
    affordable, unaffordable, unknown = [], [], []
    for square_id in ids:
        square = catalog.square(square_id)
        if not square:
            unknown.append(_int(square_id))
            continue
        entry = {
            "square_id": _int(square.get("id")),
            "square_type": _int(square.get("square_type")),
            "cost": square.get("cost") or {},
            "cost_total": _int(square.get("cost_total")),
            "score": score_square(square, resolved),
        }
        if live_state.can_afford(entry["cost"]):
            affordable.append(entry)
        else:
            entry["shortfall"] = live_state.shortfall(entry["cost"])
            unaffordable.append(entry)
    affordable.sort(key=lambda item: item["score"], reverse=True)
    unaffordable.sort(key=lambda item: item["score"], reverse=True)
    return {"affordable": affordable, "unaffordable": unaffordable, "unknown": unknown}


def describe_offers(catalog, live_state, offered_ids=None, preset=None, weights=None):
    """`40007(Song,42,SHORT 11Pa 21Me) 11001(Param,10,ok)` -- what the tree is
    offering and whether the trainee can pay for it."""
    ranked = rank_squares(catalog, live_state, offered_ids, preset, weights)
    parts = []
    for item in ranked["affordable"]:
        label = SQUARE_TYPE_NAMES.get(item["square_type"], item["square_type"])
        parts.append(f"{item['square_id']}({label},{item['cost_total']},ok)")
    for item in ranked["unaffordable"]:
        label = SQUARE_TYPE_NAMES.get(item["square_type"], item["square_type"])
        short = " ".join(
            f"{gap} {PERFORMANCE_NAMES.get(ptype, ptype)[:2]}"
            for ptype, gap in sorted((item.get("shortfall") or {}).items())
        )
        parts.append(f"{item['square_id']}({label},{item['cost_total']},short {short})")
    for square_id in ranked["unknown"]:
        parts.append(f"{square_id}(?)")
    return " ".join(parts) or "none"


def choose_square(catalog, live_state, offered_ids=None, preset=None, weights=None, context=None):
    """Pick the square to buy this turn.

    Returns (square_id, reason). square_id is None when there is nothing to
    buy -- no offer, nothing affordable, or no square catalog -- and the reason
    is a log-ready explanation in every case.
    """
    if not catalog.available:
        return None, "no square catalog (master.mdb missing or pre-Grand-Live)"
    ranked = rank_squares(catalog, live_state, offered_ids, preset, weights)
    if not (ranked["affordable"] or ranked["unaffordable"] or ranked["unknown"]):
        return None, "no squares offered"
    if not ranked["affordable"]:
        if ranked["unaffordable"]:
            best = ranked["unaffordable"][0]
            missing = ", ".join(
                f"{ptype}:{gap}" for ptype, gap in sorted((best.get("shortfall") or {}).items())
            )
            return None, f"cannot afford best square {best['square_id']} (short {missing})"
        return None, f"offered squares not in master.mdb: {ranked['unknown']}"
    if context is not None and _contextual_policy_enabled(preset):
        best, reason = choose_contextual_square(ranked["affordable"], live_state, context)
        if best:
            label = SQUARE_TYPE_NAMES.get(best["square_type"], str(best["square_type"]))
            return best["square_id"], f"{reason}: buy {label} square {best['square_id']} (cost {best['cost_total']})"
        return None, reason
    best = ranked["affordable"][0]
    label = SQUARE_TYPE_NAMES.get(best["square_type"], str(best["square_type"]))
    return best["square_id"], f"buy {label} square {best['square_id']} (cost {best['cost_total']})"
