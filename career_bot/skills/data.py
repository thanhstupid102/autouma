import re
# Underscore-aliased so the `from ...skills.data import *` facades don't
# re-export typing names into the skill mixins.
from typing import TYPE_CHECKING as _TYPE_CHECKING, Any as _Any
from pathlib import Path as _Path

MARK_WHITE_CIRCLE = "○"
MARK_DOUBLE_CIRCLE = "◎"
MARK_X = "×"
MARK_LARGE_CIRCLE = "◯"
MOJI_WHITE_CIRCLE = "â—‹"
MOJI_LARGE_CIRCLE = "â—¯"
MOJI_DOUBLE_CIRCLE = "â—Ž"
MOJI_X = "Ã—"

# Server hint discount per hint level, verified EXACTLY against live traffic
# (trace 2026-07-15): cost = int(base * (100 - HINT_COST_DISCOUNT[lv]) / 100).
# NOT 10%/level: levels 4/5 are 35%/40%.
HINT_COST_DISCOUNT = {0: 0, 1: 10, 2: 20, 3: 30, 4: 35, 5: 40}

# master.mdb single_mode_chara_effect id 7 / text_data 142:7 "Fast Learner":
# -10% skill cost, multiplicative with the hint discount.
FAST_LEARNER_EFFECT_ID = 7

SKILL_LEARN_PRIORITY_LIST = [
    [
        'Corner Acceleration ○', 'Corner Adept ○', 'Slipstream', 'Tail Held High',
        'Straightaway Spurt', 'Ramp Up', 'Inside Scoop', 'Passing Pro', 'Homestretch Haste',
        'Fast-Paced', 'Outer Swell', 'Sprinting Gear', 'Slick Surge', 'Corner Recovery ○',
        'Hydrate', 'After-School Stroll', 'Clean Heart', 'Dominator', 'All-Seeing Eyes', 'Mystifying Murmur'
    ],
    [
        'Acceleration', 'Focus', 'Go with the Flow', 'I Can See Right Through You',
        'Nimble Navigator', 'Straightaway Recovery', 'Deep Breaths', 'Preferred Position',
        'Groundwork', 'Up-Tempo', 'Unyielding Spirit', 'Pressure', 'Strategist', 'Triple 7s',
        'Shake It Out', 'Intimidate', 'Stamina Eater', 'Intense Gaze', 'Speed Star',
        'Staggering Lead', 'Blinding Flash', 'Restless', 'Trackblazer', 'Meticulous Measures',
        'Keeping the Lead', 'Leader\'s Pride', 'Wait-and-See', 'A Small Breather'
    ],
    [
        'Levelheaded', 'Stop Right There!', 'Super Lucky Seven', 'Maverick ○', 'Sympathy',
        'Long Shot ○', 'Inner Post Proficiency ○', 'Outer Post Proficiency ○', 'Right-Handed ○',
        'Left-Handed ○', 'Firm Conditions ○', 'Wet Conditions ○', 'Standard Distance ○',
        'Non-Standard Distance ○', 'Competitive Spirit ○', 'Target in Sight ○', 'Lone Wolf'
    ]
]


def norm(text):
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def strip_mark(text):
    if not text:
        return ""
    for m in [MARK_WHITE_CIRCLE, MARK_DOUBLE_CIRCLE, MARK_X, MARK_LARGE_CIRCLE,
              MOJI_WHITE_CIRCLE, MOJI_DOUBLE_CIRCLE, MOJI_X, MOJI_LARGE_CIRCLE]:
        text = text.replace(m, "")
    return text.strip()


class SkillBuyerState:
    """Type-only contract of the state SkillBuyer owns and its mixins share.

    SkillBuyer.__init__ (career_bot/skills/__init__.py) creates every attribute
    below, and the catalog / purchase mixins call across to each other -- so
    from either mixin's point of view these names come "from the host". This
    class declares them once so mypy can check the mixin bodies.

    It is TYPE-ONLY: bare annotations plus a TYPE_CHECKING-guarded block, so it
    defines no runtime attribute or method, and the mixins inherit it only under
    TYPE_CHECKING (see the `_HostState` alias in each mixin module). At runtime
    every mixin's MRO is unchanged: (Mixin, object).
    """

    base_dir: _Path
    state_root: _Path
    skill_names: dict[int, _Any]
    skill_rarities: dict[int, int]
    skill_costs: dict[int, int]
    skill_grade_values: dict[int, int]
    skill_id_exists: set[int]
    group_to_skill_ids: dict[int, list[int]]
    skill_to_group_id: dict[int, int]
    failed_this_turn: dict[int, set[int]]
    current_turn: int | None
    last_candidates: list[dict[str, _Any]]
    last_selected: list[dict[str, _Any]]
    last_attempt: list[_Any]
    last_result: dict[str, _Any]
    recover_after_error: bool
    fast_learner: bool
    unobtainable: set[int]
    bought: set[int]
    attempt_events: list[dict[str, _Any]]

    if _TYPE_CHECKING:
        # --- helpers a mixin borrows from its sibling ---
        # The bodies below are unreachable at runtime (TYPE_CHECKING is False);
        # the real implementations live in the module named above each group.
        # catalog.py
        def _candidates(self, chara: _Any, preset: _Any) -> list[dict[str, _Any]]:
            raise NotImplementedError

        def _estimate_cost(self, candidate: _Any) -> int:
            raise NotImplementedError

        def _sync_fast_learner(self, chara: _Any) -> None:
            raise NotImplementedError

        # purchase.py
        def _failed_for_turn(self, turn: _Any = None) -> set[int]:
            raise NotImplementedError
