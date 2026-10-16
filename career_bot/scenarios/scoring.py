"""Preset-driven training scorer, reusable by any scenario.

All weights come from the preset (score_value / base_score /
stat_value_multiplier / extra_weight / ...); the class attributes below are
the scenario-tunable calendar/late-game knobs.

The game-domain primitives this shares with the Unity Cup scorer (deck slots,
bond thresholds/tiers, facility indices, param target types) come from
career_bot/scenarios/score_primitives.py. Everything below them is this
scorer's own MODEL and is deliberately NOT shared -- see the "divergence"
comments at each site.
"""

from typing import TYPE_CHECKING, AbstractSet, Any

from career_bot.scenarios.base import DECK_PARTNERS, LATE_AGGRESSIVE_TURN, STAT_TARGETS, TRAINING_COMMANDS
from career_bot.scenarios.score_primitives import (
    BOND_TIER_HIGH,
    BOND_TIER_MAX,
    ENERGY_PARAM_TARGET_TYPE,
    MAX_BOND,
    SKILL_POINT_STAT_IDX,
    WIT_FACILITY_IDX,
    bond_tier,
)


class TrainingScoreMixin:
    LATE_AGGRESSIVE_TURN = LATE_AGGRESSIVE_TURN
    LATE_STAT_CAP = 1200
    SUMMER_CAMP_TURNS: AbstractSet[int] = frozenset()

    if TYPE_CHECKING:
        # Host contract: this mixin is always combined with ScenarioStrategy,
        # which supplies these. Declared under TYPE_CHECKING so the mixin gains
        # no runtime members and the MRO is untouched.
        def _bond_map(self, chara: Any) -> dict[Any, Any]: ...

        def _ignored_group_bond_slots(self, chara: Any, turn: Any, preset: Any = None) -> AbstractSet[int]: ...

        def _current_stat(self, chara: Any, target: Any) -> float: ...

    def _score_command(self, command, data, chara, preset):
        turn = int(chara.get("turn") or 0)
        late_turn = int(preset.get("late_aggressive_turn") or self.LATE_AGGRESSIVE_TURN)
        weights = self._period_row(preset.get("score_value"), turn, [0.11, 0.10, 0.006, 0.09])
        base = preset.get("base_score") or [0, 0, 0, 0, 0]
        targets = preset.get("expect_attribute") or [9999, 9999, 9999, 9999, 9999]
        idx = TRAINING_COMMANDS.get(command.get("command_id"), 0)
        score = float(base[idx] if idx < len(base) else 0)
        w_lv1 = float(weights[0] if len(weights) > 0 else 0.11)
        w_lv2 = float(weights[1] if len(weights) > 1 else 0.10)
        w_energy = float(weights[2] if len(weights) > 2 else 0.006)
        w_hint = float(weights[3] if len(weights) > 3 else 0.09)
        stat_mult = preset.get("stat_value_multiplier") or [0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
        bonds = self._bond_map(chara)
        partners = command.get("training_partner_array") or []
        hints = set(command.get("tips_event_partner_array") or [])
        ignored_group_bond_slots = self._ignored_group_bond_slots(chara, turn, preset)
        hint_count = 0
        rainbow_count = 0
        useful_stat_score = 0.0
        # DIVERGENCE (vs Unity): partners are iterated as the RAW
        # training_partner_array -- duplicates count twice and NPC ids take the
        # _npc_score path. Unity iterates the deduplicated int slot set from
        # _command_partner_slots and drops non-deck ids outright.
        for partner_id in partners:
            bond = bonds.get(partner_id, 0)
            if partner_id in hints:
                hint_count += 1

            tier = bond_tier(bond)
            if tier == BOND_TIER_MAX:
                # Maxed support on this training is delivering a rainbow (friendship
                # training) this turn. There is no more bond to build, so it adds no
                # bond value, but we count it for the explicit rainbow reward below.
                # DIVERGENCE (vs Unity): a maxed deck partner rainbows on ANY
                # facility here; Unity additionally requires the support's type to
                # match the facility (_unity_is_matching_support_type).
                if partner_id in DECK_PARTNERS:
                    rainbow_count += 1
                continue

            time_decay = max(0.0, (72 - turn) / 72.0)
            efficiency_boost = 1.0 + (bond / float(MAX_BOND)) * 0.5 if tier == BOND_TIER_HIGH else 1.0

            weight = time_decay * efficiency_boost

            if partner_id not in DECK_PARTNERS:
                yield_val = self._npc_score(bond, turn, preset)
                score += yield_val * weight
                continue

            if partner_id in ignored_group_bond_slots:
                continue

            ratio = min(1.0, bond / float(MAX_BOND))
            yield_val = w_lv1 + (w_lv2 - w_lv1) * ratio
            score += yield_val * weight
        if hint_count:
            # More skill hints on one training = more skill points / discounts, so scale
            # the hint reward by how many partners are hinting (gently, capped at 4)
            # instead of a flat bonus for "at least one hint".
            hint_scale = float(preset.get("hint_count_scale") or 0.5)
            score += w_hint * (1.0 + hint_scale * (min(hint_count, 4) - 1))
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if item.get("target_type") == ENERGY_PARAM_TARGET_TYPE:
                # DIVERGENCE (vs Unity): energy is scored here as a weighted
                # param delta. Unity ignores the energy param entirely and only
                # penalises Wit at near-full vital (_unity_wit_full_energy_penalty).
                energy_score = value * w_energy
                if int(chara.get("vital") or 0) >= 80 and value < 0:
                    energy_score *= 0.9
                score += energy_score
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None:
                continue
            if target == SKILL_POINT_STAT_IDX:
                # Skill points are NOT scored by default -- the bot chases the biggest raw
                # STAT gain instead, and whatever SP accumulates is spent at career end by
                # the leftover-SP skill dump. Opt back in with preset "score_skill_points"
                # (uses stat_value_multiplier[5] * skill_point_weight) if you want training
                # to actively favour SP-rich turns.
                if preset.get("score_skill_points", False) and value > 0:
                    sp_mult = float(stat_mult[5] if len(stat_mult) > 5 else 0.005)
                    sp_score = value * sp_mult * float(preset.get("skill_point_weight") or 1.0)
                    score += sp_score
                    useful_stat_score += max(0.0, sp_score)
                continue

            stat_gain_score = value * float(stat_mult[target] if target < len(stat_mult) else 0.01)
            # DIVERGENCE (vs Unity): the cap model here is a RATIO of the
            # preset's per-stat target (expect_attribute), attenuating the stat
            # gain in bands (>1.0 / >=0.95 / >=0.85) plus an under-target boost.
            # Unity instead divides the WHOLE facility score by a fixed
            # soft/hard-cap divisor (_unity_apply_cap). Neither is expressible
            # in the other's terms.
            cap = float(targets[target] if target < len(targets) else 9999)
            if turn >= late_turn:
                cap = float(preset.get("late_stat_cap") or self.LATE_STAT_CAP)
            if cap > 0 and target < SKILL_POINT_STAT_IDX:
                current = self._current_stat(chara, target)
                ratio = current / cap
                if turn >= late_turn:
                    if ratio > 1.0:
                        stat_gain_score *= 0.0
                    elif ratio >= 0.95:
                        stat_gain_score *= float(preset.get("late_cap_95_multiplier") or 0.35)
                    elif ratio >= 0.90:
                        stat_gain_score *= float(preset.get("late_cap_90_multiplier") or 0.90)
                elif ratio > 1.0:
                    stat_gain_score *= 0.0
                elif ratio >= 0.95:
                    stat_gain_score *= 0.55
                elif ratio >= 0.85:
                    stat_gain_score *= 1.0 - ((ratio - 0.85) / 0.10) * 0.15
                elif preset.get("stat_balance", True) and cap < 9000:
                    # Under-target boost: nudge the bot to FILL a stat that sits far
                    # below 85% target instead of piling onto near-capped stats, so the
                    # final build is balanced (not lopsided). The further under 85%,
                    # the bigger the nudge (capped). Only when a real target is set
                    # (cap != the 9999 "no target" default); complements the cap-based
                    # down-weighting above.
                    thr = float(preset.get("stat_balance_threshold") or 0.85)
                    if ratio < thr:
                        stat_gain_score *= 1.0 + (thr - ratio) * float(preset.get("stat_balance_boost") or 0.6)
            score += stat_gain_score
            useful_stat_score += max(0.0, stat_gain_score)
        if rainbow_count and preset.get("rainbow_explicit", True):
            # Explicit rainbow (friendship-training) reward. The reported stat gain
            # already includes the friendship bonus, but the bond loop gives a maxed
            # support zero value, which can make the bot pass up a multi-rainbow turn
            # to keep building bond elsewhere. Add a tunable per-rainbow bonus,
            # attenuated by the useful (non-capped) stat this turn yields so the bot
            # never chases a rainbow on already-capped stats. Failure compensation,
            # period extra-weight and deck multipliers below still apply to it.
            ref = float(preset.get("rainbow_useful_ref") or 0.12)
            atten = 1.0 if ref <= 0 else min(1.0, useful_stat_score / ref)
            per = float(preset.get("rainbow_bonus") or 0.12)
            stack = float(preset.get("rainbow_stack_bonus") or 0.06)
            score += (per * rainbow_count + stack * max(0, rainbow_count - 1)) * atten
        if preset.get("compensate_failure", True):
            # DIVERGENCE (vs Unity): failure is a MULTIPLICATIVE discount on the
            # whole score, reading failure_rate on its raw percent scale. Unity
            # normalises failure_rate to 0..1 (_normalized_failure) and SUBTRACTS
            # a flat penalty. Same input field, incompatible models.
            denominator = float(preset.get("failure_penalty_denominator") or 25.0)
            if denominator > 0:
                score *= max(0.0, 1.0 - (float(command.get("failure_rate") or 0) / denominator))
        if idx == WIT_FACILITY_IDX:
            vital = int(chara.get("vital") or 0)
            max_vital = int(chara.get("max_vital") or 100)
            gain: float = 0
            for item in command.get("params_inc_dec_info_array") or []:
                if item.get("target_type") == ENERGY_PARAM_TARGET_TYPE:
                    gain = float(item.get("value") or 0)
                    break
            if vital >= max_vital or (gain > 0 and vital + gain > max_vital):
                score *= float(preset.get("wit_overcap_late_multiplier") or 0.35) if turn > 72 else float(preset.get("wit_overcap_multiplier") or 0.75)
            elif vital < int(preset.get("wit_energy_target") or 85):
                # Wit also restores energy, so prefer it MORE the lower energy gets --
                # recovering via Wit (which still trains + gives skills/SP) beats wasting
                # a whole rest turn. Scales from ~1.0 near full to a tunable cap when low.
                target_vital = int(preset.get("wit_energy_target") or 85)
                low = (target_vital - vital) / max(1.0, float(target_vital))
                score *= 1.0 + low * float(preset.get("wit_energy_boost") or 0.25)
        extra = self._extra_weight(idx, turn, preset)
        if extra == -1:
            return -999.0
        score *= max(0.0, min(2.0, 1.0 + extra))

        if turn < 60:
            deck_mults = preset.get("_deck_multipliers")
            if deck_mults and len(deck_mults) > idx:
                score *= float(deck_mults[idx])

        return score

    def _npc_score(self, bond, turn, preset):
        # DIVERGENCE (vs Unity): NPC (non-deck) partners still carry bond value
        # here. Unity skips them entirely for bond and only scores them through
        # the soul-colour arrays.
        if bond >= MAX_BOND:
            return 0.0
        row = self._period_row(preset.get("npc_score_value"), turn, [0.05, 0.05, 0.05])
        v1 = float(row[0] if len(row) > 0 else 0.05)
        v2 = float(row[1] if len(row) > 1 else v1)
        ratio = min(1.0, bond / float(MAX_BOND))
        return v1 + (v2 - v1) * ratio

    def _period_index(self, turn):
        if turn <= 24:
            return 0
        if turn <= 48:
            return 1
        if turn <= 60:
            return 2
        if turn <= 72:
            return 3
        return 4

    def _period_row(self, rows, turn, fallback):
        if not isinstance(rows, list) or not rows:
            return fallback
        idx = min(self._period_index(turn), len(rows) - 1)
        row = rows[idx]
        return row if isinstance(row, list) else fallback

    def _extra_weight(self, idx, turn, preset):
        rows = preset.get("extra_weight") or [[0, 0, 0, 0, 0]] * 4
        if turn <= 24:
            row_idx = 0
        elif turn <= 48:
            row_idx = 1
        elif turn in self.SUMMER_CAMP_TURNS and len(rows) >= 4:
            row_idx = 3
        else:
            row_idx = 2
        if row_idx >= len(rows) or not isinstance(rows[row_idx], list) or idx >= len(rows[row_idx]):
            return 0.0
        return float(rows[row_idx][idx] or 0)
