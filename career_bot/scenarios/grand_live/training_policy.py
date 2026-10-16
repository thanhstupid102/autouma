"""Grand Live-specific training and Light Hello outing policy."""

from __future__ import annotations

from dataclasses import dataclass

from career_bot.scenarios.base import DECK_PARTNERS, GROUP_OUTING_COMMAND_ID, STAT_TARGETS, TRAINING_COMMANDS
from career_bot.scenarios.score_primitives import ENERGY_PARAM_TARGET_TYPE, MAX_BOND, WIT_FACILITY_IDX


LIGHT_HELLO_SUPPORT_ID = 30052
# Captured from the live 1.33.0 client in uma_runtime/captures/gl_flow_01.jsonl:
# Light Hello group outing uses command_group_id=390 with select_id=9008 on
# every date step. Generic recreation can use select_id=0, but group outing 390
# with select_id=0 is rejected by the server (result_code 102).
LIGHT_HELLO_OUTING_SELECT_ID = 9008
GRAND_LIVE_GOOD_TRAINING_SCORE = 1.0
GRAND_LIVE_REST_SCORE = 1.05
GRAND_LIVE_WIT_BASE_SCORE = 1.0
GRAND_LIVE_WIT_FULL_VITAL_PENALTY_BEFORE_T24 = {98: 0.0, 99: 0.0, 100: 0.0}
GRAND_LIVE_WIT_FULL_VITAL_PENALTY_FROM_T24 = {98: 0.2, 99: 0.4, 100: 0.8}

FACILITY_SUPPORT_TYPES = {
    0: {"speed"},
    1: {"stamina"},
    2: {"power"},
    3: {"guts"},
    4: {"wit", "wisdom"},
}
WIT_SUPPORT_TYPES = FACILITY_SUPPORT_TYPES[WIT_FACILITY_IDX]


def _int(value, default=0):
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return int(default or 0)


def _num(preset, key, default):
    try:
        return float((preset or {}).get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _cfg(preset, key, default):
    return (preset or {}).get(key, default)


def _penalty_table(preset, key, default):
    value = _cfg(preset, key, default)
    if not isinstance(value, dict):
        value = default
    result = {}
    for percent, penalty in value.items():
        try:
            result[int(percent)] = float(penalty)
        except (TypeError, ValueError):
            continue
    return result


@dataclass(frozen=True)
class GrandLiveTrainingScore:
    command: dict
    command_id: int
    facility_idx: int
    score: float
    stat_score: float
    support_score: float
    token_score: float
    failure: int
    bondable_count: int = 0
    rainbow_count: int = 0
    npc_count: int = 0
    light_hello: bool = False
    light_hello_bonus: float = 0.0

    @property
    def is_wit(self):
        return self.facility_idx == WIT_FACILITY_IDX


def grand_live_score_detail(score: GrandLiveTrainingScore):
    parts = [
        f"Score:{score.score:.2f}",
        f"Stat:{score.stat_score:.2f}",
        f"Sup:{score.support_score:.2f}",
        f"Tok:{score.token_score:.2f}",
        f"{score.bondable_count}B",
        f"{score.rainbow_count}RB",
        f"{score.npc_count}NPC",
        f"{score.failure}F",
    ]
    if score.light_hello:
        parts.append(f"LH:{score.light_hello_bonus:.2f}")
    return " ".join(parts)


def grand_live_score_debug(score: GrandLiveTrainingScore):
    return {
        "score": round(score.score, 3),
        "stat_score": round(score.stat_score, 3),
        "support_score": round(score.support_score, 3),
        "token_score": round(score.token_score, 3),
        "failure_percent": int(score.failure),
        "bondable_count": int(score.bondable_count),
        "rainbow_count": int(score.rainbow_count),
        "npc_count": int(score.npc_count),
        "light_hello": bool(score.light_hello),
        "light_hello_bonus": round(score.light_hello_bonus, 3),
    }


def score_grand_live_training(strategy, command, data, chara, preset):
    command_id = _int(command.get("command_id"))
    facility_idx = TRAINING_COMMANDS[command_id]
    stat_score = _stat_score(strategy, command, chara, preset)
    support_score, bondable_count, rainbow_count, npc_count, light_hello, light_hello_bonus = _support_score(
        strategy, command, chara, facility_idx, preset
    )
    token_score = strategy._token_score_bonus(command, preset)
    score = stat_score + support_score + token_score
    if facility_idx == WIT_FACILITY_IDX:
        score += _num(preset, "grand_live_wit_base_score", GRAND_LIVE_WIT_BASE_SCORE)
    failure = _int(command.get("failure_rate"))
    if failure:
        denominator = _num(preset, "grand_live_failure_penalty_denominator", 50.0)
        if denominator > 0:
            score *= max(0.0, 1.0 - (failure / denominator))
    if facility_idx == WIT_FACILITY_IDX:
        score -= _wit_full_vital_penalty(chara, preset)
    return GrandLiveTrainingScore(
        command=command,
        command_id=command_id,
        facility_idx=facility_idx,
        score=score,
        stat_score=stat_score,
        support_score=support_score,
        token_score=token_score,
        failure=failure,
        bondable_count=bondable_count,
        rainbow_count=rainbow_count,
        npc_count=npc_count,
        light_hello=light_hello,
        light_hello_bonus=light_hello_bonus,
    )


def _stat_score(strategy, command, chara, preset):
    stat_mult = (preset or {}).get("stat_value_multiplier") or [0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
    targets = (preset or {}).get("expect_attribute") or [9999, 9999, 9999, 9999, 9999]
    score = 0.0
    for item in command.get("params_inc_dec_info_array") or []:
        if _int(item.get("target_type")) == ENERGY_PARAM_TARGET_TYPE:
            score += float(item.get("value") or 0) * 0.006
            continue
        target = STAT_TARGETS.get(item.get("target_type"))
        if target is None:
            continue
        value = float(item.get("value") or 0)
        mult = float(stat_mult[target] if target < len(stat_mult) else 0.01)
        current = strategy._current_stat(chara, target) if target < 5 else 0.0
        cap = float(targets[target] if target < len(targets) else 9999)
        if cap > 0 and target < 5 and current >= cap:
            mult *= 0.1
        score += value * mult
    return score


def _support_score(strategy, command, chara, facility_idx, preset=None):
    preset = preset or getattr(strategy, "_last_preset", None) or {}
    bonds = strategy._bond_map(chara)
    support_types = strategy._support_type_map(chara)
    light_hello_slot = strategy._light_hello_slot(chara)
    score = 0.0
    bondable_count = rainbow_count = npc_count = 0
    light_hello = False
    light_hello_bonus = 0.0
    non_lh_rainbows = 0
    low_or_mid_seen = 0
    for partner_id in command.get("training_partner_array") or []:
        partner_id = _int(partner_id)
        if partner_id == light_hello_slot:
            light_hello = True
            light_hello_bonus = strategy._light_hello_training_bonus(facility_idx)
            score += light_hello_bonus
            continue
        if partner_id not in DECK_PARTNERS:
            npc_count += 1
            score += _num(preset, "grand_live_npc_score", 0.05)
            continue
        bond = _int(bonds.get(partner_id))
        support_type = str(support_types.get(partner_id) or "").lower()
        if bond < 60:
            score += _num(preset, "grand_live_support_bond_low_score", 0.5) + _num(preset, "grand_live_support_stack_bonus", 0.1) * low_or_mid_seen
            low_or_mid_seen += 1
            bondable_count += 1
        elif bond < MAX_BOND:
            score += _num(preset, "grand_live_support_bond_mid_score", 0.75) + _num(preset, "grand_live_support_stack_bonus", 0.1) * low_or_mid_seen
            low_or_mid_seen += 1
            bondable_count += 1
        elif _is_matching_support_type(support_type, facility_idx):
            rainbow_count += 1
            base = _num(preset, "grand_live_wit_rainbow_score", 1.2) if facility_idx == WIT_FACILITY_IDX and support_type in WIT_SUPPORT_TYPES else _num(preset, "grand_live_matching_rainbow_score", 1.0)
            score += base if non_lh_rainbows == 0 else _num(preset, "grand_live_rainbow_stack_bonus", 0.25)
            non_lh_rainbows += 1
        else:
            score += _num(preset, "grand_live_off_type_max_bond_score", 0.05)
    return score, bondable_count, rainbow_count, npc_count, light_hello, light_hello_bonus


def _wit_full_vital_penalty(chara, preset=None):
    turn = _int((chara or {}).get("turn"))
    vital = _int((chara or {}).get("vital"))
    max_vital = _int((chara or {}).get("max_vital"), 100)
    if max_vital <= 0:
        max_vital = 100
    vital_percent = min(100, vital * 100 // max_vital)
    key = "grand_live_wit_full_vital_penalty_from_t24" if turn >= 24 else "grand_live_wit_full_vital_penalty_before_t24"
    default = GRAND_LIVE_WIT_FULL_VITAL_PENALTY_FROM_T24 if turn >= 24 else GRAND_LIVE_WIT_FULL_VITAL_PENALTY_BEFORE_T24
    return _penalty_table(preset, key, default).get(vital_percent, 0.0)


def _is_matching_support_type(support_type, facility_idx):
    return str(support_type or "").lower() in FACILITY_SUPPORT_TYPES.get(_int(facility_idx), set())


def best_grand_live_training(strategy, training, data, chara, preset):
    scores = [score_grand_live_training(strategy, cmd, data, chara, preset) for cmd in training]
    if not scores:
        return None, []
    indexed = list(enumerate(scores))
    _idx, best = max(indexed, key=lambda row: (row[1].score, -row[1].failure, -row[0]))
    return best, scores


def clone_light_hello_outing_command(outing_cmd, select_id):
    chosen = dict(outing_cmd or {})
    chosen["command_type"] = 3
    chosen["command_id"] = GROUP_OUTING_COMMAND_ID
    chosen["select_id"] = _int(select_id)
    chosen["_grand_live_light_hello_date"] = True
    return chosen


def light_hello_outing_select_id(chara, fallback=LIGHT_HELLO_OUTING_SELECT_ID):
    """Discover the select_id from group_outing_info_array.

    For support-card outings the API command is command_type=3, command_id=390,
    with select_id=9008 for Light Hello (captured from the live client).  If the
    server ever exposes an explicit select_id, prefer it; otherwise only fall
    back to the captured id once the Light Hello outing is visibly unlocked.
    """
    light_slot = None
    light_row = None
    for card in (chara or {}).get("support_card_array") or []:
        if _int(card.get("support_card_id")) == LIGHT_HELLO_SUPPORT_ID:
            light_slot = _int(card.get("position"))
            break
    for row in (chara or {}).get("evaluation_info_array") or []:
        target_id = _int(row.get("target_id"))
        if target_id == light_slot:
            light_row = row
        for outing in row.get("group_outing_info_array") or []:
            if not isinstance(outing, dict):
                continue
            is_outing = _int(outing.get("is_outing"), 1)
            if is_outing != 1:
                continue
            if target_id == light_slot or _int(outing.get("support_card_id")) == LIGHT_HELLO_SUPPORT_ID:
                select_id = _int(outing.get("select_id"))
                return select_id if select_id > 0 else _int(fallback)
    if light_row and _int(light_row.get("is_outing")) == 1:
        return _int(fallback)
    return None


def light_hello_date_command(enabled, chara, best_scores, *, preset=None, rest=None):
    has_light_hello = any(
        _int(card.get("support_card_id")) == LIGHT_HELLO_SUPPORT_ID
        for card in (chara or {}).get("support_card_array") or []
    )
    if not has_light_hello:
        return None
    outing_cmd = next(
        (
            cmd for cmd in enabled
            if _int(cmd.get("command_type")) == 3 and _int(cmd.get("command_id")) == GROUP_OUTING_COMMAND_ID
        ),
        None,
    )
    if not outing_cmd:
        return None
    motivation = _int((chara or {}).get("motivation"), 3)
    vital = _int((chara or {}).get("vital"))
    preset = preset or {}
    select_id = light_hello_outing_select_id(chara)
    if select_id is None:
        return None
    if motivation < _int(_cfg(preset, "grand_live_light_hello_date_motivation_below", 3), 3):
        return clone_light_hello_outing_command(outing_cmd, select_id)
    vital_min = _int(_cfg(preset, "grand_live_light_hello_date_vital_min", 25), 25)
    vital_max = _int(_cfg(preset, "grand_live_light_hello_date_vital_max", 65), 65)
    good_score = _num(preset, "grand_live_good_training_score", GRAND_LIVE_GOOD_TRAINING_SCORE)
    if vital_min < vital < vital_max and not any(_score_without_wit_energy(score, preset) > good_score for score in best_scores or []):
        return clone_light_hello_outing_command(outing_cmd, select_id)
    return None


def _score_without_wit_energy(score: GrandLiveTrainingScore, preset=None):
    if not score.is_wit:
        return score.score
    energy_component = 0.0
    for item in score.command.get("params_inc_dec_info_array") or []:
        if _int(item.get("target_type")) == ENERGY_PARAM_TARGET_TYPE and float(item.get("value") or 0) > 0:
            energy_component += float(item.get("value") or 0) * 0.006
    return score.score - _num(preset, "grand_live_wit_base_score", GRAND_LIVE_WIT_BASE_SCORE) - energy_component