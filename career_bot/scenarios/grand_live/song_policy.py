"""Contextual Grand Live tree-square policy.

The fallback picker in :mod:`career_bot.scenarios.grand_live.squares` still
orders broad tiers (Song > Skill > Parameter > HP) for callers/tests that do not
pass context.  This module is the tuned in-run policy used by
``GrandLiveStrategy``: common squares are cheap pathing, while unique 4xxxx song
offers are chased/held according to the current concert session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from career_bot.scenarios.grand_live.live_state import (
    DANCE,
    MENTAL,
    PASSION,
    SQUARE_PARAMETER,
    SQUARE_SONG,
    VISUAL,
    VOCAL,
)


def _int(value, default=0):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default or 0)


@dataclass(frozen=True)
class SongInfo:
    square_id: int
    kind: str
    stat: str = ""
    amount: int = 0
    friendship: int = 0
    specialty_priority: int = 0
    support_event_chance: int = 0


UNIQUE_SONGS: dict[int, SongInfo] = {
    40000: SongInfo(40000, "skillpt", amount=2, specialty_priority=5),
    40001: SongInfo(40001, "stat", stat="power", amount=22, friendship=5),
    40002: SongInfo(40002, "stat", stat="speed", amount=22, friendship=5),
    40003: SongInfo(40003, "skillpt", amount=22, friendship=5),
    40004: SongInfo(40004, "skillpt", amount=3, support_event_chance=1),
    40005: SongInfo(40005, "sg", stat="wit", amount=2, support_event_chance=1),
    40006: SongInfo(40006, "sg", stat="power", amount=1, support_event_chance=1),
    40007: SongInfo(40007, "sg", stat="wit", amount=1, specialty_priority=5),
    40008: SongInfo(40008, "sg", stat="power", amount=2, specialty_priority=5),
    40009: SongInfo(40009, "sg", stat="guts", amount=1, support_event_chance=1),
    40010: SongInfo(40010, "sg", stat="stamina", amount=1, support_event_chance=1),
    40011: SongInfo(40011, "sg", stat="speed", amount=2, specialty_priority=5),
    40012: SongInfo(40012, "stat", stat="stamina", amount=22, friendship=5),
    40013: SongInfo(40013, "sg", stat="guts", amount=2, specialty_priority=5),
    40014: SongInfo(40014, "stat", stat="guts", amount=22, friendship=5),
    40015: SongInfo(40015, "stat", stat="wit", amount=22, friendship=5),
    40016: SongInfo(40016, "stat", stat="power", amount=22, friendship=5),
    40017: SongInfo(40017, "sg", stat="stamina", amount=2, specialty_priority=5),
    40018: SongInfo(40018, "stat", stat="guts", amount=26, friendship=10),
    40019: SongInfo(40019, "stat", stat="speed", amount=26, friendship=10),
    40020: SongInfo(40020, "sg", stat="speed", amount=1, support_event_chance=1),
}

SESSION_1_TARGETS = {40001, 40002, 40003}
SESSION_2_TARGETS = {40000}
SESSION_3_TARGETS = {40004}
FRIENDSHIP_10 = {sid for sid, info in UNIQUE_SONGS.items() if info.friendship >= 10}
FRIENDSHIP_5 = {sid for sid, info in UNIQUE_SONGS.items() if info.friendship == 5}
FRIENDSHIP_SONGS = FRIENDSHIP_10 | FRIENDSHIP_5
SP_SONGS = {sid for sid, info in UNIQUE_SONGS.items() if info.specialty_priority >= 5}
SKILLPT_PLUS_SONGS = {40000, 40004}

# When token inventories are close, spend expendable tokens first and preserve
# Dance/Visual most.  Higher value = preferred spend.
COMMON_CLOSE_TOKEN_ORDER = {
    VOCAL: 5,
    PASSION: 4,
    MENTAL: 3,
    DANCE: 2,
    VISUAL: 1,
}


@dataclass
class SquarePolicyContext:
    turn: int = 0
    bought_song_ids: set[int] = field(default_factory=set)
    session_song_counts: dict[int, int] = field(default_factory=dict)
    config: dict = field(default_factory=dict)


def _cfg_int(context, key, default):
    return _int((getattr(context, "config", {}) or {}).get(key), default)


def concert_session(turn):
    turn = _int(turn)
    if 12 <= turn <= 23:
        return 1, 24
    if 25 <= turn <= 35:
        return 2, 36
    if 37 <= turn <= 47:
        return 3, 48
    if 49 <= turn <= 59:
        return 4, 60
    if 61 <= turn <= 69:
        return 5, 72
    if 70 <= turn <= 78:
        return 6, 78
    return 0, 0


def unique_ids_from_live_state(live_state):
    """Best-effort server-state song id extraction.

    Captures have used several arrays around live/song state.  Only values that
    look exactly like documented 40000..40020 square ids are trusted; strategy
    purchase tracking fills the gap when the server exposes live ids instead.
    """
    ids: set[int] = set()
    raw = getattr(live_state, "raw", {}) or {}
    for attr in ("master_live_ids", "next_live_ids", "effected_live_ids"):
        for value in getattr(live_state, attr, []) or []:
            sid = _int(value)
            if sid in UNIQUE_SONGS:
                ids.add(sid)
    for key in (
        "master_live_id_array",
        "next_live_id_array",
        "effected_live_id_array",
        "effected_master_live_id_array",
        "bought_square_id_array",
    ):
        for value in raw.get(key) or []:
            sid = _int(value.get("square_id") if isinstance(value, dict) else value)
            if sid in UNIQUE_SONGS:
                ids.add(sid)
    return ids


def context_bought_song_ids(live_state, context=None):
    ids = unique_ids_from_live_state(live_state)
    if context is not None:
        ids |= {_int(sid) for sid in getattr(context, "bought_song_ids", set()) if _int(sid)}
    return ids


def _dominant_cost_token(cost):
    if not cost:
        return 0
    return max((_int(value), _int(ptype)) for ptype, value in cost.items())[1]


def common_square_key(entry, live_state, *, finale=False):
    tokens = live_state.tokens
    cost = entry.get("cost") or {}
    cost_tokens = [_int(ptype) for ptype in cost]
    inventory_values = [tokens.get(ptype, 0) for ptype in cost_tokens] or [0]
    spread = max(tokens.values() or [0]) - min(tokens.values() or [0])
    dominant = _dominant_cost_token(cost)
    spend_score = COMMON_CLOSE_TOKEN_ORDER.get(dominant, 0) if spread < 5 else max(inventory_values)
    parameter_priority = 1 if finale and _int(entry.get("square_type")) == SQUARE_PARAMETER else 0
    return (
        parameter_priority,
        -_int(entry.get("cost_total")),
        spend_score,
        COMMON_CLOSE_TOKEN_ORDER.get(dominant, 0),
        -_int(entry.get("square_id")),
    )


def best_common_square(entries, live_state, *, finale=False):
    common = [entry for entry in entries if _int(entry.get("square_type")) != SQUARE_SONG]
    if not common:
        return None
    return max(common, key=lambda entry: common_square_key(entry, live_state, finale=finale))


def _base_unique_tier(info: SongInfo):
    if info.square_id in SKILLPT_PLUS_SONGS:
        return 300
    if info.friendship >= 10:
        return 290
    if info.friendship == 5:
        return 280
    if info.specialty_priority >= 5:
        return 200
    return 100


def _remaining_song_key(info: SongInfo):
    sg_pref = {"speed": 50, "wit": 40, "wisdom": 40, "power": 30, "stamina": 20, "guts": 20}
    return sg_pref.get(info.stat, 0) + _int(info.amount)


def _session_unique_allowed(info: SongInfo, context: SquarePolicyContext, bought: set[int], offers_have_tier0: bool):
    session, _deadline = concert_session(context.turn)
    sid = info.square_id
    session_count = _int((context.session_song_counts or {}).get(session))
    if session == 1:
        if SESSION_1_TARGETS - bought:
            return sid in SESSION_1_TARGETS or sid in SKILLPT_PLUS_SONGS or info.friendship
        return session_count < 4
    if session == 2:
        if 40000 not in bought:
            return sid == 40000 or _base_unique_tier(info) >= 280
        return session_count < 3
    if session == 3:
        if 40004 not in bought:
            return sid == 40004 or _base_unique_tier(info) >= 280
        return session_count < 3
    if session == 4:
        if sid in (FRIENDSHIP_SONGS - bought):
            return True
        return session_count < 3
    if session == 5:
        return session_count < 2 and (sid in (FRIENDSHIP_SONGS | SP_SONGS | SKILLPT_PLUS_SONGS) or not offers_have_tier0)
    return True


def unique_square_key(entry, context: SquarePolicyContext, bought: set[int], *, panic=False, offers_have_tier0=False):
    sid = _int(entry.get("square_id"))
    info = UNIQUE_SONGS.get(sid)
    if not info or sid in bought:
        return None
    if panic:
        return (1000, -_int(entry.get("cost_total")), _base_unique_tier(info), -sid)
    if not _session_unique_allowed(info, context, bought, offers_have_tier0):
        return None
    session, _deadline = concert_session(context.turn)
    session_bonus = 0
    if session == 1 and sid in SESSION_1_TARGETS:
        session_bonus = 120
    elif session == 2 and sid == 40000:
        session_bonus = 140
    elif session == 3 and sid == 40004:
        session_bonus = 140
    elif session == 4 and info.friendship:
        session_bonus = 120 + info.friendship
    elif session == 5 and info.friendship:
        session_bonus = 90 + info.friendship

    tier = _base_unique_tier(info)
    if tier == 200 and offers_have_tier0:
        return None
    return (
        tier + session_bonus,
        info.amount if info.kind == "skillpt" else 0,
        info.friendship,
        info.specialty_priority,
        _remaining_song_key(info),
        -_int(entry.get("cost_total")),
        -sid,
    )


def choose_contextual_square(affordable, live_state, context: SquarePolicyContext):
    """Return ``(entry, reason)`` for the tuned in-run policy."""
    context = context or SquarePolicyContext()
    session, deadline = concert_session(context.turn)
    bought = context_bought_song_ids(live_state, context)
    uniques = [entry for entry in affordable if _int(entry.get("square_type")) == SQUARE_SONG]
    common = [entry for entry in affordable if _int(entry.get("square_type")) != SQUARE_SONG]
    if session == 6:
        best = best_common_square(common, live_state, finale=True)
        if best:
            return best, "finale token dump: cheap Parameter/common square"

    session_count = _int((context.session_song_counts or {}).get(session))
    panic_turns = _cfg_int(context, "grand_live_panic_turns_before_concert", 3)
    panic_min_songs = _cfg_int(context, "grand_live_panic_min_session_songs", 3)
    panic = bool(deadline and deadline - _int(context.turn) <= panic_turns and session_count < panic_min_songs)
    if uniques:
        offers_have_tier0 = any(_base_unique_tier(UNIQUE_SONGS.get(_int(e.get("square_id")), SongInfo(0, ""))) >= 280 for e in uniques)
        keyed = []
        for entry in uniques:
            key = unique_square_key(entry, context, bought, panic=panic, offers_have_tier0=offers_have_tier0)
            if key is not None:
                keyed.append((key, entry))
        if keyed:
            _key, best = max(keyed, key=lambda row: row[0])
            sid = _int(best.get("square_id"))
            info = UNIQUE_SONGS.get(sid)
            tag = "panic unique" if panic else "unique song"
            detail = f"{info.kind}" if info else "song"
            if info and info.friendship:
                detail += f" Friendship+{info.friendship}"
            if info and info.specialty_priority:
                detail += f" SP+{info.specialty_priority}"
            return best, f"{tag}: {sid} {detail}"

    # Common squares are pathing: buy the cheapest affordable one, spending the
    # fullest inventory token and preserving Dance/Visual on close inventories.
    if common and not _should_hold_tokens(context, bought):
        return best_common_square(common, live_state), "cheap common path square"
    return None, "holding Grand Live tokens for priority unique songs"


def _should_hold_tokens(context: SquarePolicyContext, bought: set[int]):
    session, _deadline = concert_session(context.turn)
    session_count = _int((context.session_song_counts or {}).get(session))
    if session == 1:
        return session_count >= 4 and not (SESSION_1_TARGETS - bought)
    if session == 2:
        return session_count >= 4 or (session_count >= 3 and 40000 in bought)
    if session == 3:
        return session_count >= 3 and 40004 in bought
    if session == 5:
        return session_count >= 2
    return False