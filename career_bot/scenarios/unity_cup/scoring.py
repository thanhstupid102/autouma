"""Unity Cup training-score value object + the pure helpers behind it.

Shares the game-domain primitives (facility indices, stat keys, param target
types, bond thresholds) with MANT through
career_bot/scenarios/score_primitives.py; the scoring MODEL below (soul
colours, flat cap divisors, subtractive failure penalty) is Unity's own and is
deliberately not shared -- see the "divergence" comments here and in
career_bot/scenarios/scoring.py.
"""

from dataclasses import dataclass

from career_bot.scenarios.score_primitives import STAT_KEYS, STAT_PARAM_TARGET_TYPES
from career_bot.scenarios.unity_cup.config import (
    UNITY_FACILITY_SHORT_LABELS,
    UNITY_FACILITY_SUPPORT_TYPES,
    UNITY_GUTS_BLUE_PURPLE_SOUL_BONUS,
    UNITY_GUTS_BLUE_PURPLE_SOUL_STACK_BONUS_STEP,
    UNITY_GUTS_FACILITY_IDX,
    UNITY_NORMAL_CAP_RULE,
    UNITY_POWER_BLUE_PURPLE_SOUL_BONUS,
    UNITY_POWER_BLUE_PURPLE_SOUL_STACK_BONUS_STEP,
    UNITY_POWER_FACILITY_IDX,
    UNITY_SPEED_BLUE_PURPLE_SOUL_BONUS,
    UNITY_SPEED_BLUE_PURPLE_SOUL_STACK_BONUS_STEP,
    UNITY_SPEED_FACILITY_IDX,
    UNITY_STAMINA_BLUE_PURPLE_SOUL_BONUS,
    UNITY_STAMINA_BLUE_PURPLE_SOUL_FALLOFF,
    UNITY_STAMINA_BLUE_PURPLE_SOUL_STACK_BONUS_STEP,
    UNITY_STAMINA_FACILITY_IDX,
    UNITY_STAT_KEYS,
    UNITY_WIT_BLUE_PURPLE_SOUL_BONUS,
    UNITY_WIT_BLUE_PURPLE_SOUL_STACK_BONUS_STEP,
    UNITY_WIT_CAP_RULE,
    UNITY_WIT_FACILITY_IDX,
    UNITY_WIT_FULL_ENERGY_PENALTY_EARLY,
    UNITY_WIT_FULL_ENERGY_PENALTY_LATE,
    _unity_cap_rule,
    _unity_num,
    _unity_penalty_table,
)


@dataclass(frozen=True)
class UnityTrainingScore:
    command: dict
    command_id: int
    facility_idx: int
    is_wit: bool
    score: float
    failure: float
    raw_gain: int
    bondable_count: int
    purple_count: int
    blue_count: int
    soul_count: int
    has_wit_rainbow: bool
    white_count: int = 0
    rainbow_count: int = 0


def _unity_facility_label(score_or_facility_idx):
    facility_idx = score_or_facility_idx.facility_idx if isinstance(score_or_facility_idx, UnityTrainingScore) else score_or_facility_idx
    return UNITY_FACILITY_SHORT_LABELS.get(_safe_int(facility_idx), str(facility_idx))


def _unity_score_detail(score, tie_break=None):
    failure_percent = int(round((score.failure or 0.0) * 100))
    parts = [
        f"{score.bondable_count}B",
        f"{score.rainbow_count}RB",
        f"{score.white_count}Ws",
        f"{score.blue_count}Bs",
        f"{score.purple_count}Ps",
        f"{failure_percent}F",
    ]
    detail = f"Score: {score.score:.1f} ({', '.join(parts)}"
    if tie_break is not None:
        detail += f" - TB w/ {_unity_facility_label(tie_break)}: {tie_break.score:.1f}"
    return f"{detail})"


def _unity_score_debug(score, tie_break=None):
    return {
        "score": round(float(score.score), 1),
        "bondable_count": int(score.bondable_count),
        "rainbow_count": int(score.rainbow_count),
        "white_count": int(score.white_count),
        "blue_count": int(score.blue_count),
        "purple_count": int(score.purple_count),
        "failure_percent": int(round((score.failure or 0.0) * 100)),
        "tie_break": (
            {"facility": _unity_facility_label(tie_break), "score": round(float(tie_break.score), 1)}
            if tie_break is not None else None
        ),
    }


def _raw_training_stat_gain(command):
    # DIVERGENCE (vs base.command_stat_gain, which MANT uses): this clamps every
    # contribution at >= 0 and walks three fallback key families (params ->
    # gain_* -> bare stat keys, "wit" included). MANT's helper sums signed
    # values and has a single fallback family. Same intent, different totals.
    gain = 0
    for item in (command or {}).get("params_inc_dec_info_array") or []:
        if int(item.get("target_type") or 0) in STAT_PARAM_TARGET_TYPES:
            gain += max(0, int(item.get("value") or 0))
    if gain:
        return gain
    for key in ("gain_speed", "gain_stamina", "gain_power", "gain_guts", "gain_wiz", "gain_wit"):
        gain += max(0, int((command or {}).get(key) or 0))
    if gain:
        return gain
    return sum(max(0, int((command or {}).get(key) or 0)) for key in STAT_KEYS + ("wit",))


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_failure(command):
    # DIVERGENCE (vs MANT): failure_rate is coerced onto a 0..1 scale here and
    # later SUBTRACTED from the score; MANT keeps the raw percent scale and
    # applies it as a multiplicative discount (scenarios/scoring.py).
    try:
        failure = float((command or {}).get("failure_rate") or 0)
    except (TypeError, ValueError):
        failure = 0.0
    if failure > 1.0:
        failure /= 100.0
    return max(0.0, failure)


def _unity_current_stat(chara, facility_idx):
    if 0 <= facility_idx < len(UNITY_STAT_KEYS):
        return _safe_int((chara or {}).get(UNITY_STAT_KEYS[facility_idx]))
    return 0


def _unity_apply_cap(score, facility_idx, chara, config=None):
    # DIVERGENCE (vs MANT): a flat soft/hard-cap divisor on the WHOLE facility
    # score. MANT attenuates each stat delta by its ratio against the preset's
    # per-stat target instead (scenarios/scoring.py).
    if score <= 0:
        return score
    soft_cap, soft_divisor, hard_cap, hard_divisor = _unity_cap_rule(
        config,
        "wit_cap_rule" if facility_idx == UNITY_WIT_FACILITY_IDX else "normal_cap_rule",
        UNITY_WIT_CAP_RULE if facility_idx == UNITY_WIT_FACILITY_IDX else UNITY_NORMAL_CAP_RULE,
    )
    current = _unity_current_stat(chara, facility_idx)
    if current >= hard_cap:
        return score / hard_divisor
    if current >= soft_cap:
        return score / soft_divisor
    return score


def _unity_blue_purple_soul_stack_bonus(facility_idx, blue_purple_count, config=None):
    if not blue_purple_count:
        return 0.0
    stack_keys = {
        UNITY_SPEED_FACILITY_IDX: ("speed_blue_purple_soul_stack_bonus_step", UNITY_SPEED_BLUE_PURPLE_SOUL_STACK_BONUS_STEP),
        UNITY_STAMINA_FACILITY_IDX: ("stamina_blue_purple_soul_stack_bonus_step", UNITY_STAMINA_BLUE_PURPLE_SOUL_STACK_BONUS_STEP),
        UNITY_POWER_FACILITY_IDX: ("power_blue_purple_soul_stack_bonus_step", UNITY_POWER_BLUE_PURPLE_SOUL_STACK_BONUS_STEP),
        UNITY_GUTS_FACILITY_IDX: ("guts_blue_purple_soul_stack_bonus_step", UNITY_GUTS_BLUE_PURPLE_SOUL_STACK_BONUS_STEP),
        UNITY_WIT_FACILITY_IDX: ("wit_blue_purple_soul_stack_bonus_step", UNITY_WIT_BLUE_PURPLE_SOUL_STACK_BONUS_STEP),
    }
    key, default = stack_keys.get(facility_idx, (None, 0.0))
    return _unity_num(config, key, default) * (blue_purple_count + 1) if key else 0.0


def _unity_blue_purple_soul_bonus(facility_idx, blue_purple_count, config=None):
    stack_bonus = _unity_blue_purple_soul_stack_bonus(facility_idx, blue_purple_count, config)
    if facility_idx == UNITY_SPEED_FACILITY_IDX:
        return _unity_num(config, "speed_blue_purple_soul_bonus", UNITY_SPEED_BLUE_PURPLE_SOUL_BONUS) + stack_bonus
    if facility_idx == UNITY_STAMINA_FACILITY_IDX:
        base_bonus = max(0.0, _unity_num(config, "stamina_blue_purple_soul_bonus", UNITY_STAMINA_BLUE_PURPLE_SOUL_BONUS) - _unity_num(config, "stamina_blue_purple_soul_falloff", UNITY_STAMINA_BLUE_PURPLE_SOUL_FALLOFF) * blue_purple_count)
        return base_bonus + stack_bonus
    if facility_idx == UNITY_POWER_FACILITY_IDX:
        return _unity_num(config, "power_blue_purple_soul_bonus", UNITY_POWER_BLUE_PURPLE_SOUL_BONUS) + stack_bonus
    if facility_idx == UNITY_GUTS_FACILITY_IDX:
        return _unity_num(config, "guts_blue_purple_soul_bonus", UNITY_GUTS_BLUE_PURPLE_SOUL_BONUS) + stack_bonus
    if facility_idx == UNITY_WIT_FACILITY_IDX:
        return _unity_num(config, "wit_blue_purple_soul_bonus", UNITY_WIT_BLUE_PURPLE_SOUL_BONUS) + stack_bonus
    return 0.0


def _unity_is_matching_support_type(support_type, facility_idx):
    return str(support_type or "").lower() in UNITY_FACILITY_SUPPORT_TYPES.get(_safe_int(facility_idx), set())


def _unity_wit_full_energy_penalty(turn, vital, max_vital=100, config=None):
    max_vital = _safe_int(max_vital, 100)
    if max_vital <= 0:
        max_vital = 100
    vital_percent = _safe_int(vital) * 100 // max_vital
    penalties = _unity_penalty_table(
        config,
        "wit_full_energy_penalty_early" if turn <= 24 else "wit_full_energy_penalty_late",
        UNITY_WIT_FULL_ENERGY_PENALTY_EARLY if turn <= 24 else UNITY_WIT_FULL_ENERGY_PENALTY_LATE,
    )
    return penalties.get(vital_percent, 0.0)
