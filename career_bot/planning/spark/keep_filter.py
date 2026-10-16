"""Self-spark keep-filter for auto-deleting a just-trained uma."""

import json
from pathlib import Path
from typing import Any

from career_bot.planning.factors import parse_factor_ids
from core.runtime_paths import resolve_master_json_path


_COLOUR_BY_CATEGORY = {
    "stat": "blue",
    "aptitude": "pink",
    "skill": "white",
    "race": "white",
    "scenario": "white",
    "unique": "green",
}

_FACTOR_MAP = None
_SKILL_DATA = None


def colour_of(category):
    return _COLOUR_BY_CATEGORY.get(category)


def _normalize(name):
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _count_stars(factors, colour):
    return sum(
        int(f.get("stars") or 0)
        for f in factors
        if colour_of(f.get("category")) == colour
    )


def _has(factors, name, min_stars):
    target = _normalize(name)
    if not target:
        return False
    return any(
        _normalize(f.get("name")) == target and int(f.get("stars") or 0) >= min_stars
        for f in factors
    )


def _condition_met(factors, condition):
    """exclude = absent · otherwise (>= / legacy "has") = stars >= min_stars."""
    name = condition.get("name")
    mode = condition.get("mode", "atleast")
    min_stars = int(condition.get("min_stars", condition.get("minStars", 1)) or 1)
    if mode == "exclude":
        return not _has(factors, name, 1)
    return _has(factors, name, min_stars)


def keep_filter_matches(factors, flt):
    """True if these self-factors satisfy the keep-filter, meaning keep the uma.

    Per-factor conditions combine OR within a colour and AND across colours; the
    Total-star thresholds AND on top.
    """
    factors = factors or []
    flt = flt or {}
    for colour, key in (
        ("blue", "min_blue"),
        ("pink", "min_pink"),
        ("white", "min_white"),
        ("green", "min_green"),
    ):
        need = int(flt.get(key) or 0)
        if need > 0 and _count_stars(factors, colour) < need:
            return False

    groups: dict[Any, list[Any]] = {}
    for condition in flt.get("conditions") or []:
        if not isinstance(condition, dict):
            continue
        if not _normalize(condition.get("name")):
            continue
        colour = condition.get("colour") or "other"
        groups.setdefault(colour, []).append(condition)

    for conditions in groups.values():
        if not any(_condition_met(factors, c) for c in conditions):
            return False
    return True


def _load_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    # exists()/read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError):
        pass
    return {}


def _repo_root():
    return Path(__file__).resolve().parents[3]


def _load_factor_map():
    global _FACTOR_MAP
    if _FACTOR_MAP is None:
        _FACTOR_MAP = _load_json(
            resolve_master_json_path(_repo_root(), "factor_map.json")
        )
    return _FACTOR_MAP


def _load_skill_data():
    global _SKILL_DATA
    if _SKILL_DATA is None:
        _SKILL_DATA = _load_json(
            resolve_master_json_path(_repo_root(), "skill_data.json")
        )
    return _SKILL_DATA


def self_factors(factor_id_array):
    """Parse the just-trained uma's own factor ids into UI-compatible factors."""
    return parse_factor_ids(
        factor_id_array or [],
        factor_map=_load_factor_map(),
        skill_data=_load_skill_data(),
    )
