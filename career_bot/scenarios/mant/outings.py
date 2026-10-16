"""Sirius/Throne ("two pal deck") tactics -- MANT-only strategy: the card ids,
the group-slot bond exclusions and the scripted outing schedule. Other
scenarios never see any of this; base only exposes the neutral
_ignored_group_bond_slots hook this mixin overrides."""

from typing import TYPE_CHECKING, AbstractSet, Any

from career_bot.scenarios.base import GROUP_OUTING_COMMAND_ID

TEAM_SIRIUS_SUPPORT_ID = 30081
THRONE_SUPPORT_ID = 30067
SIRIUS_THRONE_GROUP_IDS = (TEAM_SIRIUS_SUPPORT_ID, THRONE_SUPPORT_ID)
CARD_SIGNATURE_CHARA = {TEAM_SIRIUS_SUPPORT_ID: 1001, THRONE_SUPPORT_ID: 1017}
EARLY_GROUP_CARD_CLICK_TURN_LIMIT = 24
# turn -> (chara_id | None, support_id, label[, captured select_id]) -- rows are
# 3- or 4-wide, hence the variadic tuple type.
SIRIUS_THRONE_RECREATION_SCHEDULE: dict[int, tuple[Any, ...]] = {
    18: (1002, TEAM_SIRIUS_SUPPORT_ID, "Silence Suzuka"),
    22: (1016, TEAM_SIRIUS_SUPPORT_ID, "Narita Brian"),
    26: (1017, THRONE_SUPPORT_ID, "Symboli Rudolf"),
    28: (1030, TEAM_SIRIUS_SUPPORT_ID, "Rice Shower"),
    32: (1001, TEAM_SIRIUS_SUPPORT_ID, "Special Week"),
    36: (1003, THRONE_SUPPORT_ID, "Tokai Teio"),
    43: (1013, TEAM_SIRIUS_SUPPORT_ID, "Mejiro McQueen"),
    47: (1073, THRONE_SUPPORT_ID, "Tsurumaru Tsuyoshi"),
    51: (None, THRONE_SUPPORT_ID, "Throne outing", 1017),
    55: (1035, TEAM_SIRIUS_SUPPORT_ID, "Winning Ticket"),
    58: (None, TEAM_SIRIUS_SUPPORT_ID, "Team Sirius outing", 1001),
    59: (None, THRONE_SUPPORT_ID, "Throne outing", 1017),
}


class SiriusThroneOutingsMixin:
    # Run state created by the host strategy's __init__/reset_run_state (see
    # mant/strategy.py) and read+updated here; bare annotations, so no runtime
    # class attribute is created.
    _early_group_card_clicked_slots: set[int]
    _early_group_card_last_turn: int | None
    SUMMER_CAMP_TURNS: AbstractSet[int]

    if TYPE_CHECKING:
        # Host contract: supplied by ScenarioStrategy, which every host of this
        # mixin also inherits. TYPE_CHECKING-only, so no runtime member is added.
        def _command_partner_slots(self, command: Any) -> set[int]: ...

        def _command_stat_gain(self, command: Any) -> int: ...

    def _group_card_slots(self, chara):
        return [int(c.get("position") or 0) for c in chara.get("support_card_array") or []
                if int(c.get("support_card_id") or 0) in set(SIRIUS_THRONE_GROUP_IDS)]

    def _ignored_group_bond_slots(self, chara, turn, preset=None):
        return set(self._group_card_slots(chara)) if (preset or {}).get("two_pal_deck") is True else set()

    def _early_group_card_command(self, training, chara, turn, preset=None):
        if (preset or {}).get("two_pal_deck") is not True:
            return None
        if int(turn or 0) > EARLY_GROUP_CARD_CLICK_TURN_LIMIT:
            return None
        if self._early_group_card_last_turn is not None and int(turn or 0) < self._early_group_card_last_turn:
            self._early_group_card_clicked_slots.clear()
        slots = set(self._group_card_slots(chara))
        missing = slots - self._early_group_card_clicked_slots
        if not missing:
            return None
        candidates = [cmd for cmd in training if self._command_partner_slots(cmd) & missing]
        if not candidates:
            return None
        return max(candidates, key=lambda cmd: (len(self._command_partner_slots(cmd) & missing), self._command_stat_gain(cmd)))

    def _mark_early_group_card_command(self, command, chara):
        turn = int((chara or {}).get("turn") or 0)
        if turn > EARLY_GROUP_CARD_CLICK_TURN_LIMIT or int((command or {}).get("command_type") or 0) != 1:
            return
        if self._early_group_card_last_turn is not None and turn < self._early_group_card_last_turn:
            self._early_group_card_clicked_slots.clear()
        self._early_group_card_last_turn = turn
        self._early_group_card_clicked_slots |= self._command_partner_slots(command) & set(self._group_card_slots(chara))

    def _slot_row(self, chara, slot):
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) == int(slot or 0):
                return row
        return None

    def _support_slot(self, chara, support_id):
        for c in chara.get("support_card_array") or []:
            if int(c.get("support_card_id") or 0) == int(support_id):
                return int(c.get("position") or 0)
        return None

    def _card_outing_select_id(self, support_id):
        return int(CARD_SIGNATURE_CHARA.get(int(support_id), 0))

    def _char_outing_state(self, chara, chara_id):
        for row in chara.get("evaluation_info_array") or []:
            for outing in row.get("group_outing_info_array") or []:
                if int(outing.get("chara_id") or 0) == int(chara_id):
                    return int(outing.get("is_outing") or 0), int(outing.get("story_step") or 0)
        return 0, 0

    def _card_row_state(self, chara, support_id):
        row = self._slot_row(chara, self._support_slot(chara, support_id))
        if not row:
            return 0, 0
        return int(row.get("is_outing") or 0), int(row.get("story_step") or 0)

    def _outing_plan(self):
        plan: list[dict[str, Any]] = []
        card_step: dict[int, int] = {}
        for turn in sorted(SIRIUS_THRONE_RECREATION_SCHEDULE):
            chara_id, support_id, _label, *captured_select_id = SIRIUS_THRONE_RECREATION_SCHEDULE[turn]
            if chara_id is not None:
                plan.append({"turn": turn, "kind": "char", "support_id": support_id, "chara_id": int(chara_id), "select_id": int(chara_id)})
            else:
                card_step[support_id] = card_step.get(support_id, 0) + 1
                plan.append({"turn": turn, "kind": "card", "support_id": support_id, "step": card_step[support_id], "select_id": int(captured_select_id[0] if captured_select_id else self._card_outing_select_id(support_id))})
        return plan

    def _outing_step_done(self, chara, step):
        if step["kind"] == "char":
            return self._char_outing_state(chara, step["chara_id"])[1] >= 1
        return self._card_row_state(chara, step["support_id"])[1] >= step["step"]

    def _outing_step_available(self, chara, step):
        if self._outing_step_done(chara, step):
            return False
        if step["kind"] == "char":
            return self._char_outing_state(chara, step["chara_id"])[0] == 1
        card_is_outing, _card_story_step = self._card_row_state(chara, step["support_id"])
        return card_is_outing == 1 and self._char_outing_state(chara, step["select_id"])[1] >= 1

    def debug_scheduled_recreation(self, enabled, turn, chara, preset):
        if int(turn or 0) not in SIRIUS_THRONE_RECREATION_SCHEDULE:
            return None
        enabled = [cmd for cmd in (enabled or []) if cmd.get("is_enable", 1)]
        outing_cmd = next((cmd for cmd in enabled if cmd.get("command_type") == 3 and int(cmd.get("command_id") or 0) == GROUP_OUTING_COMMAND_ID), None)
        plan = self._outing_plan()
        scheduled = self._scheduled_recreation(enabled, turn, chara, preset)
        canonical = next((step for step in plan if step["turn"] == int(turn or 0)), None)
        rows = []
        for step in plan:
            if step["turn"] > int(turn or 0):
                continue
            row = dict(step)
            row["done"] = self._outing_step_done(chara, step)
            row["available"] = self._outing_step_available(chara, step)
            row["block_reason"] = "done" if row["done"] else "not_outing_enabled"
            if step["kind"] == "char":
                is_outing, story_step = self._char_outing_state(chara, step["chara_id"])
                row.update({"char_is_outing": is_outing, "char_story_step": story_step})
                if not row["done"] and is_outing == 1:
                    row["block_reason"] = "available"
            else:
                card_is_outing, card_story_step = self._card_row_state(chara, step["support_id"])
                sig_is_outing, sig_story_step = self._char_outing_state(chara, step["select_id"])
                row.update({
                    "card_is_outing": card_is_outing,
                    "card_story_step": card_story_step,
                    "signature_is_outing": sig_is_outing,
                    "signature_story_step": sig_story_step,
                })
                if not row["done"]:
                    row["block_reason"] = "available" if row["available"] else "card_not_outing" if card_is_outing != 1 else "signature_story_step_lt_1"
            rows.append(row)
        return {
            "turn": int(turn or 0),
            "two_pal_deck": (preset or {}).get("two_pal_deck") is True,
            "schedule_enabled": (preset or {}).get("sirius_throne_schedule", True) is not False,
            "outing_cmd_enabled": outing_cmd is not None,
            "current_step": canonical,
            "scheduled_select_id": (scheduled or {}).get("select_id"),
            "skip_reason": "scheduled" if scheduled else "schedule_disabled" if (preset or {}).get("sirius_throne_schedule", True) is False else "not_two_pal_deck" if (preset or {}).get("two_pal_deck") is not True else "summer_camp" if int(turn or 0) in self.SUMMER_CAMP_TURNS else "outing_cmd_disabled" if outing_cmd is None else "current_step_unavailable",
            "schedule_rows": rows,
        }

    def _scheduled_recreation(self, enabled, turn, chara, preset):
        if preset.get("sirius_throne_schedule", True) is False:
            return None
        if preset.get("two_pal_deck") is not True:
            return None
        if turn not in SIRIUS_THRONE_RECREATION_SCHEDULE:
            return None
        if turn in self.SUMMER_CAMP_TURNS:
            return None
        outing_cmd = next((cmd for cmd in enabled if cmd.get("command_type") == 3 and int(cmd.get("command_id") or 0) == GROUP_OUTING_COMMAND_ID), None)
        if not outing_cmd:
            return None
        plan = self._outing_plan()
        canonical = next((step for step in plan if step["turn"] == turn), None)
        if canonical and self._outing_step_available(chara, canonical):
            return self._outing_command(outing_cmd, canonical["select_id"])
        for step in plan:
            if step["support_id"] == TEAM_SIRIUS_SUPPORT_ID and step["turn"] <= turn and self._outing_step_available(chara, step):
                return self._outing_command(outing_cmd, step["select_id"])
        for step in plan:
            if step["support_id"] == THRONE_SUPPORT_ID and self._outing_step_available(chara, step):
                return self._outing_command(outing_cmd, step["select_id"])
        return None

    def _outing_command(self, outing_cmd, select_id):
        chosen = dict(outing_cmd)
        chosen["select_id"] = int(select_id)
        return chosen
