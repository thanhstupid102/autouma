"""Pure event-choice scoring for the MANT career bot.

The game gives every event a set of choices, each with a hidden reward
(stat gains, skill hints, energy, mood, bond, status effects). gametora
publishes those rewards as short effect strings ("Skill hint +1, Power +20").

This module parses those strings and scores each choice so the EventManager can
pick the best option instead of blindly choosing option 1. It is intentionally
pure (no I/O, no game state) so it is cheap to unit-test; the EventManager wires
it to the scraped-effect database and live career context.

Ported/adapted from the Icarus fork's gametora-effect scorer.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, cast

from career_bot.game_calendar import SUMMER_CAMP_TURNS

STAT_KEYS = ["speed", "stamina", "power", "guts", "wiz"]

# Map effect-string stat words to our internal stat keys.
_EFFECT_STAT_MAP = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wisdom": "wiz",
    "wit": "wiz",
    "wiz": "wiz",
    "intelligence": "wiz",
}

# Scoring weights (mirror the reference Trackblazer event policy).
SKILL_HINT_BONUS = 25.0
BOND_GAIN_BONUS = 20.0
BOND_LOSS_PENALTY = -20.0
POSITIVE_STATUS_BONUS = 25.0
NEGATIVE_STATUS_PENALTY = -25.0
MOOD_LOSS_PENALTY = -150.0
MAX_VITAL_WEIGHT = 2.0
STAT_PRIORITY_BONUS_BY_RANK = (50.0, 40.0, 30.0, 20.0, 10.0)
MOOD_BONUS_BY_MOTIVATION = {1: 150.0, 2: 120.0, 3: 90.0, 4: 60.0, 5: 0.0}
# (hp_below, multiplier) — energy is worth more the lower the current HP.
LOW_ENERGY_MULTIPLIERS = ((30, 4), (50, 3), (70, 2), (90, 1))
ENERGY_PRIORITIZE_MULTIPLIER = 100.0
# Stat ceiling; positive stat rewards lose value as a stat nears it.
STAT_CAP = 1200.0
STAT_CAP_WINDOW = 250.0
# Summer-camp + finale turns where energy is most valuable.
_SUMMER_TURNS = frozenset(SUMMER_CAMP_TURNS)
_FINALE_LEAD_IN_TURN = 66

_TOKEN_RE = re.compile(r"([A-Za-z][A-Za-z .]*?)\s*([+-]\s*\d+)")


def parse_effect_string(text: Any) -> Optional[Dict[str, Any]]:
    """Parse a gametora effect string into a reward dict.

    Examples::

        "Bond +5, Power +20"            -> {"bond": 5, "power": 20}
        "Skill hint +1, Power +20"      -> {"hints": 1, "power": 20}
        "All stats +10"                 -> {speed..wiz: 10}
        "Energy +20"                    -> {"vital": 20}
        "Get Practice Perfect ○"        -> {"positive_status": True}

    Returns ``None`` when nothing scoreable is found.
    """
    if not text or not isinstance(text, str):
        return None
    reward: Dict[str, Any] = {}
    hints = 0
    if "○" in text or "◯" in text:
        reward["positive_status"] = True
    if "✕" in text or "×" in text:
        reward["negative_status"] = True
    for match in _TOKEN_RE.finditer(text):
        name = match.group(1).strip().lower()
        try:
            val = int(match.group(2).replace(" ", ""))
        except ValueError:
            continue
        # "hint" alone (the scrape now names the skill, e.g. "Long Straightaways
        # hint +1"), as well as the generic "Skill hint".
        if "hint" in name:
            hints += max(1, val)
            continue
        if "skill" in name and ("point" in name or "pt" in name):
            reward["skill_point"] = reward.get("skill_point", 0) + val
            continue
        if "max" in name and ("energy" in name or "vital" in name or "stamina" in name):
            reward["max_vital"] = reward.get("max_vital", 0) + val
            continue
        if "energy" in name or "vital" in name:
            reward["vital"] = reward.get("vital", 0) + val
            continue
        if "bond" in name or "friendship" in name:
            reward["bond"] = reward.get("bond", 0) + val
            continue
        if "motivation" in name or "mood" in name:
            reward["motivation"] = reward.get("motivation", 0) + val
            continue
        if "all stat" in name:
            for sk in STAT_KEYS:
                reward[sk] = reward.get(sk, 0) + val
            continue
        stat = None
        for token, sk in _EFFECT_STAT_MAP.items():
            if name == token or name.endswith(" " + token) or name.endswith(token):
                stat = sk
                break
        if stat:
            reward[stat] = reward.get(stat, 0) + val
    if hints:
        reward["hints"] = hints
    return reward or None


def stat_priority_from_targets(targets: Any) -> List[int]:
    """Order stat indices by descending target value (highest target first).

    ``targets`` is the preset ``expect_attribute`` = [speed, stamina, power,
    guts, wiz]. Ties keep their natural order. Falls back to [0,1,2,3,4].
    """
    if not targets:
        return [0, 1, 2, 3, 4]
    try:
        vals = [float(targets[i]) if i < len(targets) else -9999.0 for i in range(5)]
    except (TypeError, ValueError):
        return [0, 1, 2, 3, 4]
    return sorted(range(5), key=lambda i: vals[i], reverse=True)


def _priority_bonus(priority: Optional[Sequence[int]]) -> Dict[int, float]:
    if not priority:
        return {}
    out: Dict[int, float] = {}
    for rank, idx in enumerate(priority):
        if rank < len(STAT_PRIORITY_BONUS_BY_RANK):
            out[idx] = STAT_PRIORITY_BONUS_BY_RANK[rank]
        else:
            out[idx] = 0.0
    return out


def _cap_factor(chara: Any, idx: int) -> float:
    if not isinstance(chara, Mapping) or not (0 <= idx < len(STAT_KEYS)):
        return 1.0
    key = STAT_KEYS[idx]
    cur = chara.get(key)
    if cur is None and key == "wiz":
        cur = chara.get("wit")
    try:
        cur = float(cast(Any, cur))
    except (TypeError, ValueError):
        return 1.0
    if cur <= 0:
        return 1.0
    headroom = (STAT_CAP - cur) / STAT_CAP_WINDOW
    if headroom >= 1.0:
        return 1.0
    return max(0.1, headroom)


def _energy_multiplier(chara: Any) -> float:
    hp = _safe_int((chara or {}).get("vital"), 50) if isinstance(chara, Mapping) else 50
    for threshold, multiplier in LOW_ENERGY_MULTIPLIERS:
        if hp < threshold:
            return float(multiplier)
    if hp >= 90:
        return 0.0
    return 1.0


def _turn_energy_multiplier(turn: Any) -> float:
    try:
        t = int(turn or 0)
    except (TypeError, ValueError):
        return 1.0
    if t in _SUMMER_TURNS:
        return 1.25
    if t >= _FINALE_LEAD_IN_TURN:
        return 1.2
    return 1.0


def _energy_bonus(chara: Any, value: Any, turn: Any, prioritize: bool) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value == 0:
        return 0.0
    if value < 0:
        return value * max(1.0, _energy_multiplier(chara))
    tm = _turn_energy_multiplier(turn)
    if prioritize:
        return value * max(1.0, ENERGY_PRIORITIZE_MULTIPLIER) * tm
    hp = _safe_int((chara or {}).get("vital"), 50) if isinstance(chara, Mapping) else 50
    max_vital = _safe_int((chara or {}).get("max_vital"), 100) if isinstance(chara, Mapping) else 100
    if max_vital > 0 and hp >= max_vital:
        return 0.0
    return value * _energy_multiplier(chara) * tm


def _mood_bonus(chara: Any) -> float:
    mood = _safe_int((chara or {}).get("motivation"), 3) if isinstance(chara, Mapping) else 3
    return MOOD_BONUS_BY_MOTIVATION.get(mood, 80.0)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def score_reward(
    reward: Any,
    *,
    stat_priority: Optional[Sequence[int]] = None,
    chara: Any = None,
    turn: Any = 0,
    prioritize_energy: bool = False,
) -> float:
    """Score a parsed reward dict. Higher = better choice."""
    if not isinstance(reward, Mapping):
        return 0.0
    score = 0.0
    bonus = _priority_bonus(stat_priority)
    for idx, key in enumerate(STAT_KEYS):
        if key not in reward:
            continue
        try:
            val = float(reward[key])
        except (TypeError, ValueError):
            continue
        if val > 0:
            score += (val + bonus.get(idx, 0.0)) * _cap_factor(chara, idx)
        else:
            score += val
    if "skill_point" in reward:
        try:
            score += float(reward["skill_point"])
        except (TypeError, ValueError):
            pass
    hints = reward.get("hints")
    if hints:
        score += SKILL_HINT_BONUS * int(hints)
    if "bond" in reward:
        bond = _to_float(reward["bond"])
        if bond > 0:
            score += BOND_GAIN_BONUS
        elif bond < 0:
            score += BOND_LOSS_PENALTY
    if "motivation" in reward:
        mot = _to_float(reward["motivation"])
        if mot > 0:
            score += _mood_bonus(chara) * mot
        elif mot < 0:
            score += MOOD_LOSS_PENALTY * abs(mot)
    if "vital" in reward:
        score += _energy_bonus(chara, reward["vital"], turn, prioritize_energy)
    if "max_vital" in reward:
        score += max(0.0, _to_float(reward["max_vital"])) * MAX_VITAL_WEIGHT
    if reward.get("positive_status"):
        score += POSITIVE_STATUS_BONUS
    if reward.get("negative_status"):
        score += NEGATIVE_STATUS_PENALTY
    return score


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def best_choice_index(
    choices: Sequence[Mapping[str, Any]],
    effects_row: Any,
    *,
    stat_priority: Optional[Sequence[int]] = None,
    chara: Any = None,
    turn: Any = 0,
    prioritize_energy: bool = False,
) -> Optional[int]:
    """Return the list index of the best choice, or ``None`` when no choice has
    a parseable scraped effect (caller should fall back).

    ``choices`` is the game's ``choice_array`` (each item carries a
    ``select_index``); ``effects_row`` is the scraped-effects entry
    ``{"choices": {"1": {"effect": "..."}, ...}}``.
    """
    if not isinstance(effects_row, Mapping):
        return None
    row_choices = effects_row.get("choices")
    if not isinstance(row_choices, Mapping) or not row_choices:
        return None
    best_idx: Optional[int] = None
    best_score: Optional[float] = None
    found = False
    for i, choice in enumerate(choices):
        sel = str((choice or {}).get("select_index", i + 1))
        info = row_choices.get(sel)
        if not isinstance(info, Mapping):
            continue
        reward = parse_effect_string(info.get("effect"))
        if reward is None:
            continue
        found = True
        s = score_reward(
            reward,
            stat_priority=stat_priority,
            chara=chara,
            turn=turn,
            prioritize_energy=prioritize_energy,
        )
        if best_score is None or s > best_score:
            best_score = s
            best_idx = i
    return best_idx if found else None


def recommended_choice_position(
    effects_row: Any,
    *,
    stat_priority: Optional[Sequence[int]] = None,
    chara: Any = None,
    turn: Any = 0,
    prioritize_energy: bool = False,
) -> Optional[int]:
    """Return the 0-based POSITION (index into the select_index-sorted choices —
    the same order as the catalog ``choice_effects`` list) of the choice the bot
    would auto-pick, for the dashboard's "bot pick" marker. This matches the
    0-based choice_number the bot actually sends at runtime (see
    ``EventManager.choose``), so the marker lines up with the real pick. Returns
    ``None`` when the event has no scoreable scraped effects.
    """
    if not isinstance(effects_row, Mapping):
        return None
    row_choices = effects_row.get("choices")
    if not isinstance(row_choices, Mapping) or not row_choices:
        return None
    sels = sorted(row_choices.keys(), key=lambda s: int(s) if str(s).isdigit() else 0)
    choices = [
        {"select_index": int(s) if str(s).isdigit() else s} for s in sels
    ]
    return best_choice_index(
        choices,
        effects_row,
        stat_priority=stat_priority,
        chara=chara,
        turn=turn,
        prioritize_energy=prioritize_energy,
    )
