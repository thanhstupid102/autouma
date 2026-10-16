import copy
from dataclasses import dataclass
from typing import AbstractSet

from career_bot.events import EventManager
from career_bot.scenarios.score_primitives import (
    DECK_PARTNERS,
    SKILL_POINT_KEY,
    SKILL_POINT_PARAM_TARGET_TYPE,
    SKILL_POINT_STAT_IDX,
    STAT_KEYS,
    STAT_PARAM_TARGET_TYPES,
    is_max_bond,
)


# --- game-wide tables shared by every scenario ---
# The bond/facility/stat primitives themselves live in
# career_bot/scenarios/score_primitives.py (shared with the per-scenario
# scorers); DECK_PARTNERS is re-exported here so the historical
# `from career_bot.scenarios.base import DECK_PARTNERS` import keeps working.

STAT_TARGETS = {
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    SKILL_POINT_PARAM_TARGET_TYPE: SKILL_POINT_STAT_IDX,
}

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]
LATE_AGGRESSIVE_TURN = 65
LATE_UNCOVERED_FAILURE_REST = 30

# The group ("pal") outing command id. Generic recreation must never click it
# (it needs a select_id), so _recreation_command filters it out in every
# scenario. Which pal CARDS exist and how to play them (Sirius/Throne schedule,
# two_pal_deck bond exclusions) is MANT-only strategy -- scenarios/mant/outings.py;
# base carries no Sirius/Throne knowledge.
GROUP_OUTING_COMMAND_ID = 390


@dataclass
class Decision:
    action: str
    payload: dict
    reason: str


def command_stat_gain(command):
    """Raw stat points a training yields this turn (Speed/Stamina/Power/Guts/Wit).

    This is the "jumlah training" the player thinks in: a 2-rainbow turn lands
    around 30+. Skill points are not counted; the stat cap is not considered.
    """
    total = 0
    for item in (command or {}).get("params_inc_dec_info_array") or []:
        if item.get("target_type") in STAT_PARAM_TARGET_TYPES:
            total += int(item.get("value") or 0)
    if total == 0:
        for field in STAT_KEYS:
            total += int((command or {}).get(field) or 0)
    return total


class ScenarioStrategy:
    scenario_id = 0
    display_label = ""
    config_preset_key = "_bot_config"
    # single_mode_* career-API path prefix.
    endpoint_prefix = "single_mode_free"

    # --- capabilities the runner consults (overridden per scenario) ---
    handles_shop_items = False
    verbose_response_log = False
    extra_playing_states: AbstractSet[int] = frozenset()
    # Clock (continue) policy: True = the runner's legacy "force clocks until
    # rank 1" behavior for _should_force_clocks-matched races (MANT). False =
    # the runner instead honors Decision.payload["_required_rank"] set by the
    # scenario (route-objective-aware retries only -- see career_bot/engine/
    # racing.py _race and career_bot/scenarios/unity_cup/strategy.py).
    free_clock_retry = False
    # True = this scenario prefers, among the turn's wanted races, one that is a
    # rival race (MANT's rival-race objective). False = just take the first
    # wanted race. RacePlanner.choose() consults this instead of hardcoding
    # scenario_id == 4.
    prefers_rival_races = False

    @classmethod
    def apply_config_to_preset(cls, result, values):
        """Attach this scenario's resolved bot-config `values` into the runtime
        preset dict `result` and return it. Default = attach under the private
        cls.config_preset_key; scenarios that consume config as top-level preset
        keys (MANT) override this."""
        result[cls.config_preset_key] = copy.deepcopy(values)
        return result

    def extra_action_handlers(self):
        """Map of extra Decision.action -> handler(runner, client, state, preset, payload).

        Lets a scenario add actions (e.g. Unity's team_race) without editing
        the runner's dispatch."""
        return {}

    def create_item_manager(self):
        """Build this scenario's item/shop handler (the runner consults it per
        run instead of hardcoding a concrete class). Default = the MANT
        coin-shop manager, the only implementation today; a scenario without a
        coin shop can override this (the runner still gates actual buy/use on
        `handles_shop_items`). Imported lazily to avoid an engine import cycle."""
        from career_bot.scenarios.mant.items import MantItemManager
        return MantItemManager()

    def __init__(self, race_planner=None):
        self.race_planner = race_planner
        self.event_manager = None
        self._last_preset = None
        self._last_chara = None
        if self.race_planner and self.race_planner.base_dir:
            self.event_manager = EventManager(
                self.race_planner.base_dir,
                self.race_planner.state_root,
            )

    def reset_run_state(self):
        """Per-career state reset hook; scenarios with run state override (and call super)."""

    def next_decision(self, state, preset):
        raise NotImplementedError

    # --- decision building blocks ---

    def _finish_common_decision(self, data, chara):
        if "single_mode_finish_common" in data:
            return Decision("finish", {"current_turn": chara.get("turn", 0)}, "finished")
        return None

    def _career_end_decision(self, chara, reason="ready to finish"):
        if chara.get("state") == 3:
            return Decision("finish", {"current_turn": chara.get("turn", 0)}, reason)
        return None

    def _event_decision(self, data, chara):
        events = data.get("unchecked_event_array") or []
        if not events:
            return None
        event = events[0] or {}
        choice = self._choice(event)
        turn = chara.get("turn", 0)
        payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": turn}
        if choice is None:
            payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": turn}
        return Decision("event", payload, "event")

    def _race_state_decision(self, data, chara):
        race = data.get("race_start_info")
        playing_state = int(chara.get("playing_state") or 0)
        turn = chara.get("turn", 0)
        if playing_state == 3:
            return Decision("race_progress", {"current_turn": turn, "phase": "start", "race_start_info": race, "chara_info": chara}, "resume race start")
        if playing_state == 5:
            return Decision("finish", {"current_turn": turn}, "goal failed / career end")
        if race and race.get("program_id") and playing_state in (2, 4):
            return Decision("race_progress", {"current_turn": turn, "phase": "start", "race_start_info": race, "chara_info": chara}, "race start")
        return None

    # --- events ---

    def _choice(self, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if len(choices) > 1:
            return None
        return 0

    def choose_from_event(self, event, current_turn):
        if self.event_manager:
            return self.event_manager.choose(
                event,
                preset=getattr(self, "_last_preset", None),
                current_turn=current_turn,
                chara=getattr(self, "_last_chara", None),
            )
        return 1

    def describe_event_choice(self, event, position):
        """(event_name, effect_text) of the bot's pick, for the per-turn log.
        Falls back to ("", "") when there is no scraped data to describe it."""
        if self.event_manager:
            return self.event_manager.describe_choice(event, position)
        return "", ""

    # --- command helpers ---

    def _command_decision(self, command, chara):
        command_type = command.get("command_type", 1)
        command_id = command.get("command_id")
        command_group_id = command.get("command_group_id", 0)
        reason = self._command_reason(command, chara)
        if command_type == 3:
            command_group_id = command_id
            command_id = 0
        return Decision("command", {
            "command_type": command_type,
            "command_id": command_id,
            "command_group_id": command_group_id,
            "select_id": command.get("select_id", 0),
            "current_turn": chara.get("turn", 0),
            "current_vital": chara.get("vital", 0),
        }, reason)

    def _command_reason(self, command, chara=None):
        command_type = command.get("command_type")
        command_id = command.get("command_id")
        if command_id in TRAINING_COMMANDS:
            label = f"training {TRAINING_NAMES[TRAINING_COMMANDS.get(command_id, 0)]} {command_id}"
            if chara is not None:
                rc = self._rainbow_count(command, chara)
                if rc:
                    label += f" [{rc} rainbow]"
            return label
        if command_type == 7 and command_id == 701:
            return f"rest {command_id}"
        if command_type == 3:
            return f"recreation {command_id}"
        if command_type == 8 and command_id == 801:
            return "medic 801"
        return f"command {command_type}:{command_id}"

    def _rest_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 7 and cmd.get("command_id") == 701:
                return cmd
        return None

    def _recreation_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 3 and int(cmd.get("command_id") or 0) != GROUP_OUTING_COMMAND_ID:
                return cmd
        return None

    def _medic_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 8 and cmd.get("command_id") == 801:
                return cmd
        return None

    def _enabled_training_idx(self, commands, idx):
        for cmd in commands:
            if cmd.get("command_type") == 1 and TRAINING_COMMANDS.get(cmd.get("command_id")) == idx:
                return cmd
        return None

    # --- support cards / bonds ---

    def _ignored_group_bond_slots(self, chara, turn, preset=None):
        """Support-card slots excluded from bond value this turn. Neutral here
        (NEW code, not a move): the Sirius/Throne two-pal-deck tactic only
        works well in MANT, so only scenarios/mant/outings.py overrides this."""
        return set()

    def _command_partner_slots(self, command):
        return {int(p or 0) for p in (command or {}).get("training_partner_array") or []}

    def _bond_map(self, chara):
        result = {}
        for row in chara.get("evaluation_info_array") or []:
            result[row.get("target_id", 0)] = row.get("evaluation", 0)
        return result

    def _bondable_count(self, command, chara, preset=None):
        """How many deck support partners on this training still need bonding.

        A partner already at max bond (>= 80) contributes a rainbow but no longer
        builds friendship, so it does not count toward the Junior bond-rush. Slots
        returned by the _ignored_group_bond_slots scenario hook are excluded from
        bond priority.
        """
        bonds = self._bond_map(chara)
        group_slots = self._ignored_group_bond_slots(chara, int(chara.get("turn") or 0), preset)
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            if partner_id in DECK_PARTNERS and partner_id not in group_slots and not is_max_bond(int(bonds.get(partner_id, 0) or 0)):
                count += 1
        return count

    def _rainbow_count(self, command, chara):
        """How many deck supports on this training are at max bond (>=80) = rainbows.

        A maxed support present on a training delivers a friendship-training
        ("rainbow") bonus; stacking several on one training is the biggest stat turn
        in the game. NPCs (not in DECK_PARTNERS) don't trigger friendship training.
        """
        bonds = self._bond_map(chara)
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            if partner_id in DECK_PARTNERS and is_max_bond(int(bonds.get(partner_id, 0) or 0)):
                count += 1
        return count

    def _command_stat_gain(self, command):
        return command_stat_gain(command)

    def _current_stat(self, chara, target):
        keys = list(STAT_KEYS) + [SKILL_POINT_KEY]
        return float(chara.get(keys[target], 0) or 0)

    # --- race eligibility / result hooks (neutral here; see unity_cup/strategy.py) ---

    def _is_excluded_race_program(self, program_id):
        """Should preset race selection skip `program_id` right now?

        Neutral here (always eligible). Unity Cup overrides this to exclude Maiden
        races once the trainee has won the Junior Make Debut or a prior Maiden race
        (a won debut/maiden removes Maiden races from the pool for good -- the bot
        must never request one again)."""
        return False

    def record_race_result(self, program_id, rank):
        """Called by the runner after every race with the final rank (post any
        clock retries), so a strategy can track state that depends on race
        outcomes (e.g. Unity Cup's debut/maiden win tracking, since most turns'
        server responses don't carry `race_history`). No-op here."""
