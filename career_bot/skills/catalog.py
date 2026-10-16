import json
import logging
from typing import TYPE_CHECKING

from career_bot.skills.data import *
from career_bot.skills.data import SkillBuyerState
from core.runtime_paths import resolve_master_json_path

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Type-only base: declares the SkillBuyer state / sibling-mixin helpers this
    # mixin borrows. At runtime the base is plain `object`, so the MRO is exactly
    # what `class SkillCatalogMixin:` would produce.
    _HostState = SkillBuyerState
else:
    _HostState = object


class SkillCatalogMixin(_HostState):

    def _load(self):
        path = resolve_master_json_path(
            self.base_dir,
            "skill_data.json",
            self.state_root,
        )
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.skill_names = {}
            self.skill_rarities = {}
            self.skill_costs = {}
            self.skill_grade_values = {}
            self.skill_to_group_id = {}
            for raw_id, raw_info in data.items():
                skill_id = int(raw_id)
                if isinstance(raw_info, dict):
                    self.skill_names[skill_id] = raw_info.get("name") or str(skill_id)
                    self.skill_rarities[skill_id] = int(raw_info.get("rarity") or 0)
                    self.skill_costs[skill_id] = int(raw_info.get("need_skill_point") or 0)
                    self.skill_grade_values[skill_id] = int(raw_info.get("grade_value") or 0)
                    group_id = int(raw_info.get("group_id") or 0)
                    if group_id:
                        self.skill_to_group_id[skill_id] = group_id
                else:
                    self.skill_names[skill_id] = raw_info
        # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads ->
        # ValueError; data.items() on a non-mapping -> AttributeError; int() over
        # untrusted keys/values -> TypeError / ValueError.
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning(f"Skill data load failed: {exc}")
            return
        self.skill_id_exists = set(self.skill_names)
        self.group_to_skill_ids = {}
        for skill_id in self.skill_names:
            group_id = self.skill_to_group_id.get(skill_id) or (skill_id if skill_id < 100000 else skill_id // 10)
            self.skill_to_group_id[skill_id] = group_id
            self.group_to_skill_ids.setdefault(group_id, []).append(skill_id)
        
        for group_id, ids in self.group_to_skill_ids.items():
            children = [sid for sid in ids if sid >= 100000]
            if children:
                self.group_to_skill_ids[group_id] = sorted(children, key=self._tier_sort_key)
            else:
                self.group_to_skill_ids[group_id] = sorted(ids, key=self._tier_sort_key)

    def _tier_sort_key(self, skill_id):
        grade_value = int(self.skill_grade_values.get(skill_id) or 0)
        return (
            int(self.skill_rarities.get(skill_id) or 99),
            1 if grade_value <= 0 else 0,
            grade_value if grade_value > 0 else 999999,
            int(skill_id),
        )

    def _tier_ids(self, group_id, rarity):
        ids = [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if self.skill_rarities.get(sid, 0) == rarity and self.skill_grade_values.get(sid, 0) > 0
        ]
        return sorted(ids, key=self._tier_sort_key)

    def _resolve_buyable_tier(self, group_id, rarity, owned_skill_ids):
        tiers = self._tier_ids(group_id, rarity)
        if not tiers:
            candidates = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if self.skill_rarities.get(sid, 0) == rarity and sid not in owned_skill_ids
            ]
            return sorted(candidates, key=self._tier_sort_key)[0] if candidates else 0
        for index, sid in enumerate(tiers):
            if sid in owned_skill_ids:
                continue
            if index == 0 or tiers[index - 1] in owned_skill_ids:
                return sid
            return 0
        return 0

    def _unowned_white_tiers(self, group_id, owned_skill_ids):
        return [sid for sid in self._tier_ids(group_id, 1) if sid not in owned_skill_ids]

    def _sync_fast_learner(self, chara):
        effect_ids = set()
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                effect_ids.add(int(effect_id))
            except (TypeError, ValueError):
                continue
        self.fast_learner = FAST_LEARNER_EFFECT_ID in effect_ids

    def _candidates(self, chara, preset):
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned |= self.bought  # skills already bought this career count as owned
        owned_groups = {self.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self._priority_context(preset)
        blacklist = self._blacklist(preset)
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            if not resolved or resolved.get("skip_reason"):
                continue
            result.append({
                "skill_id": resolved["resolved_skill_id"],
                "group_id": resolved["group_id"],
                "tip_rarity": resolved["tip_rarity"],
                "hint_level": resolved["hint_level"],
                "name": resolved["resolved_name"],
                "priority": resolved["priority"],
                "cost": resolved["cost"],
                "bundled_skill_ids": resolved.get("bundled_skill_ids") or [],
                "resolution_reason": resolved["resolution_reason"],
                "failed_scope": resolved["failed_scope"],
                "candidate_skill_ids": resolved["candidate_skill_ids"],
            })
        result.sort(key=lambda item: (item["priority"], -item["hint_level"], item["cost"], item["skill_id"]))
        
        deduped = []
        seen = set()
        for item in result:
            if item["skill_id"] not in seen:
                seen.add(item["skill_id"])
                deduped.append(item)
        result = deduped
        
        if preset.get("learn_skill_only_user_provided"):
            if not any(row for row in (preset.get("learn_skill_list") or [])):
                return []
            return [item for item in result if item["priority"] < 999]
        return result

    def _candidate_ids_for_tip(self, group_id, tip_rarity, owned_skill_ids):
        """Raw (pre-unobtainable-filter) candidate skill ids for a tip."""
        if tip_rarity:
            buyable_tier = self._resolve_buyable_tier(group_id, tip_rarity, owned_skill_ids)
            return [buyable_tier] if buyable_tier else []
        return [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if sid not in owned_skill_ids
        ]

    def _apply_blacklist(self, normal, blacklist):
        # Only a resolved skill can be blacklisted; an empty name means the
        # master is unknown (stale/incomplete skill_data.json) -> fall through
        # to the unknown_master path below instead of mislabeling "blacklist".
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            if s_name and (norm(s_name) in blacklist or norm(base_name) in blacklist):
                return True
        return False

    def _best_priority_variant(self, normal, priority):
        best_priority = 999
        reason = "first_valid_variant"
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            p_val = self._priority_value(sid, s_name, base_name, priority)
            if p_val < best_priority:
                best_priority = p_val
                reason = "priority_match"

        if best_priority == 999:
            for sid in normal:
                s_name = self.skill_names.get(sid, "")
                if any(s_name.endswith(m) for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE]):
                    best_priority = 500
                    reason = "circle_variant"
                    break
        return best_priority, reason

    def _bundle_cost(self, resolved, name, hint_level, group_id, owned_skill_ids):
        cost = self._estimate_cost({"skill_id": resolved, "hint_level": hint_level, "name": name})
        bundled_skill_ids = []
        if self.skill_rarities.get(resolved, 0) == 2:
            bundled_skill_ids = self._unowned_white_tiers(group_id, owned_skill_ids)
            for bundled_id in bundled_skill_ids:
                cost += self._estimate_cost({
                    "skill_id": bundled_id,
                    "hint_level": 0,
                    "name": self.skill_names.get(bundled_id, ""),
                })
        return cost, bundled_skill_ids

    def resolve_skill_tip(self, tip, owned_skill_ids, owned_groups, priority, blacklist, preset):
        group_id = int(tip.get("group_id") or 0)
        tip_rarity = int(tip.get("rarity") or 0)
        hint_level = int(tip.get("level") or 0)
        failed = self._failed_for_turn()
        candidate_skill_ids = self._candidate_ids_for_tip(group_id, tip_rarity, owned_skill_ids)
        had_candidates_before_unobtainable = bool(candidate_skill_ids)
        candidate_skill_ids = [sid for sid in candidate_skill_ids if sid not in self.unobtainable]

        row = {
            "group_id": group_id,
            "tip_rarity": tip_rarity,
            "hint_level": hint_level,
            "candidate_skill_ids": list(candidate_skill_ids),
            "resolved_skill_id": 0,
            "resolved_name": "",
            "cost": 0,
            "priority": 999,
            "resolution_reason": "",
            "master_exists": False,
            "skip_reason": None,
            "failed_scope": None,
        }
        # A skill group holds tiers of ONE skill (white ○ -> gold ◎, often a
        # different name e.g. "Corner Adept ○" r1 -> "Professor of Curvature" r2).
        # Owning a tier of EQUAL-OR-HIGHER rarity already satisfies the group, so a
        # lower tip must NOT be (re)bought: the server accepts it (result_code 1)
        # but grants nothing, silently draining SP. Owning a LOWER tier still allows
        # buying the higher one (the upgrade), so compare rarities, not bare membership.
        if tip_rarity:
            owned_group_rarity = max(
                (self.skill_rarities.get(sid, 0) for sid in owned_skill_ids
                 if self.skill_to_group_id.get(sid, sid // 10) == group_id),
                default=0,
            )
            if owned_group_rarity >= tip_rarity:
                row["skip_reason"] = "higher_tier_owned"
                return row
        if not candidate_skill_ids:
            row["skip_reason"] = "unobtainable" if had_candidates_before_unobtainable else "unknown_master"
            return row

        usable = [sid for sid in candidate_skill_ids if sid not in failed]
        if not usable:
            row["skip_reason"] = "failed_this_turn"
            row["failed_scope"] = "this_turn"
            return row

        normal = [sid for sid in usable if not (self.skill_names.get(sid, "").endswith(MARK_X) or self.skill_names.get(sid, "").endswith(MOJI_X))]
        if not normal:
            row["skip_reason"] = "no_normal_skills"
            return row

        normal.sort(key=self._tier_sort_key)
        resolved = normal[0]
        name = self.skill_names.get(resolved, "")

        if self._apply_blacklist(normal, blacklist):
            row["skip_reason"] = "blacklist"
            return row
        best_priority, reason = self._best_priority_variant(normal, priority)

        if not name:
            row["skip_reason"] = "unknown_master"
            return row

        is_double = name.endswith(MARK_DOUBLE_CIRCLE) or name.endswith(MOJI_DOUBLE_CIRCLE)
        if preset.get("skip_double_circle_unless_high_hint", False) and is_double and hint_level < 4:
            row["skip_reason"] = "rule_rejected"
            return row

        row["resolved_skill_id"] = resolved
        row["resolved_name"] = name
        cost, bundled_skill_ids = self._bundle_cost(resolved, name, hint_level, group_id, owned_skill_ids)

        row["priority"] = best_priority
        row["cost"] = cost
        row["bundled_skill_ids"] = bundled_skill_ids
        row["resolution_reason"] = reason
        row["master_exists"] = resolved in self.skill_id_exists
        if resolved in failed:
            row["failed_scope"] = "this_turn"

        return row

    def _priority(self, rows):
        result: dict[str, int] = {}
        for index, row in enumerate(rows):
            for name in row:
                key = norm(name)
                result[key] = min(index, result.get(key, index))
        return result

    def _priority_value(self, skill_id, name, base_name, priority):
        values = [priority.get(str(skill_id)), priority.get(norm(name)), priority.get(norm(base_name))]
        values = [v for v in values if v is not None]
        return min(values) if values else 999

    def _priority_context(self, preset):
        raw_priority = preset.get("learn_skill_list") or []
        if not raw_priority and not preset.get("learn_skill_only_user_provided"):
            raw_priority = SKILL_LEARN_PRIORITY_LIST
        return self._priority(raw_priority)

    def _blacklist(self, preset):
        # Drop entries that normalize to empty ("", whitespace, symbol-only): an
        # empty token matches every unresolved skill (name="") and would silently
        # blacklist the entire shop.
        return {n for item in (preset.get("learn_skill_blacklist") or []) if (n := norm(item))}

    def _select_skill_id(self, group_id, priority, owned, rarity=0):
        owned_groups = {self.skill_to_group_id.get(sid, sid // 10) for sid in owned}
        resolved = self.resolve_skill_tip({"group_id": group_id, "rarity": rarity, "level": 0}, set(owned), owned_groups, priority, set(), {})
        return int((resolved or {}).get("resolved_skill_id") or 0)

    def _estimate_cost(self, candidate):
        name = candidate.get("name") or ""
        skill_id = candidate.get("skill_id") or 0
        level = candidate.get("hint_level") or 0

        base = self.skill_costs.get(skill_id)
        if not base:
            is_circle = any(m in name for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE])
            if is_circle:
                base = 130
            elif skill_id >= 900000:
                base = 200
            else:
                base = 200 if self.skill_rarities.get(skill_id, 0) >= 2 else 160
        cost = int(base * (100 - HINT_COST_DISCOUNT[max(0, min(int(level), 5))]) / 100)
        if self.fast_learner:
            cost = int(cost * 90 / 100)
        return max(1, cost)

