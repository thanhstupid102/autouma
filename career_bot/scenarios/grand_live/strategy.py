"""Grand Live (scenario 3) career strategy.

Turn shape, reconstructed from the 2026-07-26 manual capture
(uma_runtime/captures/gl_flow_01.jsonl, one full 78-turn career):

    check_event*  ->  [master_square*]  ->  exec_command | race  ->  check_event*
    ... and on a scheduled live turn, live_start runs AFTER that action:
    turn 24: exec_command -> ev* -> live_start -> ev*
    turn 48: ev -> square* -> race -> ev* -> live_start -> ev*

Two Grand-Live-only actions sit on top of the shared career flow:

* `live_square` spends performance tokens on a tree square. It does not consume
  the turn -- the capture bought up to eight squares in one turn -- so it is
  emitted as its own decision and the runner loops straight back here.
* `live_start` runs the scheduled performance on turns 24/36/48/60/72
  (single_mode_live_live_data.turn_num, which the capture matched exactly).

Training selection reuses the shared preset-driven scorer, then adds a small
Grand-Live-only performance-token overlay.  The overlay uses the server's own
per-command `performance_inc_dec_info_array` preview, so it can prefer a close
training that earns scarce Dance/Passion/Vocal/Visual/Mental without replacing
the mature shared training model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from career_bot.scenarios.base import (
    TRAINING_COMMANDS,
    Decision,
    ScenarioStrategy,
)
from career_bot.scenarios.grand_live.live_state import (
    PERFORMANCE_NAMES,
    LiveState,
)
from career_bot.scenarios.grand_live.song_policy import SquarePolicyContext, concert_session, UNIQUE_SONGS
from career_bot.scenarios.grand_live.squares import SquareCatalog, choose_square, describe_offers
from career_bot.scenarios.grand_live.training_policy import (
    GRAND_LIVE_GOOD_TRAINING_SCORE,
    GRAND_LIVE_REST_SCORE,
    LIGHT_HELLO_SUPPORT_ID,
    best_grand_live_training,
    grand_live_score_debug,
    grand_live_score_detail,
    light_hello_date_command,
)
from career_bot.scenarios.objectives import RouteObjectives, RouteObjectivesMixin
from career_bot.scenarios.scoring import TrainingScoreMixin
from core.settings import Settings


GRAND_LIVE_SCENARIO_ID = 3
log = logging.getLogger(__name__)

# Gallop.SingleModeDefine.PlayingState.LiveTop. The metadata dump names it
# (docs/scenarios/grand-live-endpoints.md) but the capture is request-only, so
# playing_state was never observed on the wire -- hence the schedule fallback
# in _live_start_due below.
LIVE_TOP_PLAYING_STATE = 10

# Runaway guard. The capture's busiest turn bought 8 squares; anything past
# this on one turn means the server is not decrementing tokens the way we
# think, and looping forever would be worse than stopping.
MAX_SQUARE_BUYS_PER_TURN = 12

# Small additive overlay on top of TrainingScoreMixin scores.  Typical shared
# training scores are in the 0.05..0.50 range; a weight of 0.01 lets a strong
# token preview break close ties while leaving safety gates and clearly better
# stat/rainbow turns in control.
TOKEN_SCORE_WEIGHT = 0.01
TOKEN_SCARCE_RATIO = 0.25
TOKEN_LOW_RATIO = 0.50
TOKEN_NEAR_CAP_RATIO = 0.90


class GrandLiveStrategy(TrainingScoreMixin, RouteObjectivesMixin, ScenarioStrategy):
    scenario_id = GRAND_LIVE_SCENARIO_ID
    display_label = "Grand Live"
    # single_mode_* career-API path prefix. Declaring it here is what routes
    # scenario 3: endpoint_prefix_by_id() feeds ApiRoutes._single_mode_prefix,
    # so no client-side scenario table needs editing.
    endpoint_prefix = "single_mode_live"
    verbose_response_log = True
    # LiveTop is a legitimate mid-turn state, not a blocked one.
    extra_playing_states = frozenset({LIVE_TOP_PLAYING_STATE})

    @classmethod
    def apply_config_to_preset(cls, result, values):
        """Flatten like MANT rather than hiding the values behind a private
        key: the four square-weight keys are already namespaced `grand_live_*`,
        so they cannot collide with another scenario's preset, and
        squares.resolve_weights reads them straight off the preset."""
        import copy

        for key, value in values.items():
            result[key] = copy.deepcopy(value)
        return result

    def __init__(self, race_planner=None):
        super().__init__(race_planner)
        base_dir = getattr(race_planner, "base_dir", None) if race_planner else None
        self._base_dir = Path(base_dir) if base_dir else Settings.BASE_DIR
        self.objectives = RouteObjectives(self._base_dir)
        self.squares = SquareCatalog(self._base_dir)
        self.live = LiveState()
        self._live_done_turns = set()
        self._square_buys = {}
        self._square_cap_warned_turns = set()
        self._missed_live_warned_turns = set()
        self._bought_song_ids = set()
        self._session_song_buys = {}
        self._tokens_logged_turn = None
        self._support_list_cache = None
        self._light_hello_first_training_done = False
        self._light_hello_first_training_turn = None
        self._light_hello_scoring_turn = None

    def reset_run_state(self):
        super().reset_run_state()
        self.objectives.reset()
        self.live = LiveState()
        self._live_done_turns.clear()
        self._square_buys.clear()
        self._square_cap_warned_turns.clear()
        self._missed_live_warned_turns.clear()
        self._bought_song_ids.clear()
        self._session_song_buys.clear()
        self._tokens_logged_turn = None
        self._light_hello_first_training_done = False
        self._light_hello_first_training_turn = None
        self._light_hello_scoring_turn = None

    def extra_action_handlers(self):
        from career_bot.scenarios.grand_live.live_actions import run_live_square, run_live_start
        return {"live_square": run_live_square, "live_start": run_live_start}

    # --- state bookkeeping, called by the action handlers ---

    def mark_live_done(self, turn):
        self._live_done_turns.add(int(turn or 0))

    def note_square_bought(self, turn, square_id=None):
        turn = int(turn or 0)
        self._square_buys[turn] = self._square_buys.get(turn, 0) + 1
        square_id = int(square_id or 0)
        if square_id in UNIQUE_SONGS:
            self._bought_song_ids.add(square_id)
            session, _deadline = concert_session(turn)
            self._session_song_buys[session] = self._session_song_buys.get(session, 0) + 1

    def _square_policy_context(self, turn):
        return SquarePolicyContext(
            turn=int(turn or 0),
            bought_song_ids=set(self._bought_song_ids),
            session_song_counts=dict(self._session_song_buys),
            config=dict(getattr(self, "_last_preset", None) or {}),
        )

    def squares_bought_this_turn(self, turn):
        return self._square_buys.get(int(turn or 0), 0)

    # --- console inventory ---

    def log_tokens(self, turn, note="", preset=None):
        """Print the five performance tokens plus what the tree is offering.

        Kept inside the scenario rather than runner._log_inventory_snapshot,
        which is gated on handles_shop_items (MANT's coin shop) and would need
        a runner change to reach. Format matches the runner's `T<turn> ...`
        console lines.
        """
        line = f"T{int(turn or 0)} Tokens {self.live.describe_tokens_short()}"
        if note:
            line += f" ({note})"
        offers = self.live.next_square_ids
        if offers:
            line += f" | tree: {describe_offers(self.squares, self.live, offers, preset)}"
        print(line, flush=True)
        return line

    def _log_tokens_on_new_turn(self, turn, preset):
        if turn and turn != self._tokens_logged_turn:
            self._tokens_logged_turn = turn
            self.log_tokens(turn, preset=preset)

    # --- Grand Live decisions ---

    def _live_start_due(self, turn, playing_state):
        """Should live_start fire now?

        playing_state LiveTop is the only trigger, mirroring how Unity Cup keys
        its team race off playing_state 7 rather than the turn number -- the
        capture shows live_start running AFTER the turn's command/race, and the
        turn number alone cannot tell those two moments apart. `is_live_turn`
        drives only the last-resort path in `_stuck_on_a_live_turn`.
        """
        if int(turn or 0) in self._live_done_turns:
            return False
        return int(playing_state or 0) == LIVE_TOP_PLAYING_STATE

    def _stuck_on_a_live_turn(self, turn):
        """Last resort for a scheduled live turn with nothing else to do.

        Only consulted where the strategy would otherwise return `idle`, which
        stops the run. It covers a scheduled turn after the server leaves no
        race, square, or command; it cannot recover a live skipped when the
        turn's real action advances straight to the next turn.
        """
        turn = int(turn or 0)
        return turn not in self._live_done_turns and self.squares.is_live_turn(turn)

    def _warn_scheduled_live_not_started(self, turn, playing_state):
        turn = int(turn or 0)
        if (
            turn in self._live_done_turns
            or turn in self._missed_live_warned_turns
            or not self.squares.is_live_turn(turn)
        ):
            return
        self._missed_live_warned_turns.add(turn)
        log.warning(
            "Scheduled Grand Live turn %s is returning its turn action before "
            "live_start; observed playing_state=%s",
            turn,
            int(playing_state or 0),
        )

    def _square_decision(self, chara, preset):
        turn = int(chara.get("turn") or 0)
        buy_count = self.squares_bought_this_turn(turn)
        if buy_count >= MAX_SQUARE_BUYS_PER_TURN:
            if turn not in self._square_cap_warned_turns:
                self._square_cap_warned_turns.add(turn)
                log.warning(
                    "Grand Live square-buy cap reached on turn %s after %s buys",
                    turn,
                    buy_count,
                )
            return None
        square_id, reason = choose_square(self.squares, self.live, preset=preset, context=self._square_policy_context(turn))
        if not square_id:
            return None
        return Decision(
            "live_square",
            {
                "square_id": square_id,
                "current_turn": turn,
                "_strategy": self,
                "_facility_label": "Live Tree",
            },
            f"{reason} | tokens {self.live.describe_tokens()}",
        )

    # --- main loop ---

    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        self._last_preset = preset
        self._last_chara = chara
        self.live.update_from(state)
        turn = int(chara.get("turn") or 0)
        playing_state = int(chara.get("playing_state") or 0)
        self._log_tokens_on_new_turn(turn, preset)

        decision = self._finish_common_decision(data, chara) or self._career_end_decision(chara, reason="finished")
        if decision:
            return decision
        decision = self._event_decision(data, chara)
        if decision:
            return decision
        decision = self._race_state_decision(data, chara)
        if decision:
            return decision

        if self._live_start_due(turn, playing_state):
            return Decision(
                "live_start",
                {"current_turn": turn, "_strategy": self, "_facility_label": "Grand Live"},
                f"Grand Live performance (turn {turn})",
            )

        # Races are decided BEFORE squares. A mandatory-race turn disables every
        # other command, and master_square answers without race_condition_array
        # or race_start_info, so buying first strands the race with nothing left
        # to act on (see live_actions._race_is_stranded -- this stopped the
        # 2026-07-27 run three times). Squares are a free action; they still get
        # bought on the same turn, just after the race resolves.
        if self.race_planner:
            candidates = self.objectives.race_program_candidates_for_turn(chara, turn)
            forced_program_id = self.race_planner.forced_program(state, preferred=candidates or None)
            if forced_program_id:
                payload = {"program_id": forced_program_id, "current_turn": turn, "_strategy": self, "_mandatory": True}
                required_rank = self.objectives.required_rank_for_turn(chara, turn)
                if required_rank is not None:
                    payload["_required_rank"] = required_rank
                self._warn_scheduled_live_not_started(turn, playing_state)
                return Decision("race", payload, self.race_planner.label(forced_program_id))
            forced_race_exhausted = getattr(self.race_planner, "forced_race_exhausted", None)
            if forced_race_exhausted and forced_race_exhausted(state):
                return Decision("idle", {}, f"forced race turn {turn}: server rejected every offered program")

            preset_program_id = self.race_planner.choose(state, preset)
            if preset_program_id and not self._is_excluded_race_program(preset_program_id):
                self._warn_scheduled_live_not_started(turn, playing_state)
                return Decision(
                    "race",
                    {"program_id": preset_program_id, "current_turn": turn, "_strategy": self},
                    self.race_planner.label(preset_program_id),
                )

        decision = self._square_decision(chara, preset)
        if decision:
            return decision

        command = self._best_command(data, chara, preset)
        if command:
            self._warn_scheduled_live_not_started(turn, playing_state)
            return self._command_decision(command, chara)

        if self._stuck_on_a_live_turn(turn):
            return Decision(
                "live_start",
                {"current_turn": turn, "_strategy": self, "_facility_label": "Grand Live"},
                f"Grand Live performance (turn {turn}, no other action available)",
            )
        # `idle` stops the run, so say exactly what the server offered. The
        # 2026-07-27 logs only recorded "no action", which hid the fact that a
        # forced race was sitting right there, enabled and unresolvable.
        return Decision("idle", {}, f"no action ({self._describe_commands(data)})")

    def _describe_commands(self, data):
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        if not commands:
            return "home_info carried no command_info_array"
        enabled = [f"{c.get('command_type')}:{c.get('command_id')}" for c in commands if c.get("is_enable", 1)]
        if not enabled:
            return f"all {len(commands)} commands disabled"
        has_race = any(c.get("command_type") == 4 and c.get("is_enable", 1) for c in commands)
        detail = f"enabled={enabled}"
        if has_race and not (data.get("race_condition_array") or data.get("race_start_info")):
            detail += " but no race_condition_array/race_start_info to resolve the race"
        return detail

    # --- command selection ---

    def _command_decision(self, command, chara):
        decision = super()._command_decision(command, chara)
        gain = self.live.command_token_gain(command.get("command_type"), command.get("command_id"))
        if gain:
            decision.payload["_score_detail"] = " ".join(
                f"{PERFORMANCE_NAMES.get(ptype, ptype)}+{value}" for ptype, value in sorted(gain.items())
            )
        elif command.get("_grand_live_score_detail"):
            decision.payload["_score_detail"] = command.get("_grand_live_score_detail")
        if command.get("_grand_live_score_debug"):
            decision.payload["_score_debug"] = command.get("_grand_live_score_debug")
        if command.get("_grand_live_light_hello_date"):
            decision.payload["_facility_label"] = "Light Hello date"
        if command.get("_grand_live_facility_label"):
            decision.payload["_facility_label"] = command.get("_grand_live_facility_label")
        return decision

    def _support_list(self):
        if self._support_list_cache is None:
            path = self._base_dir / "data" / "json" / "support_list.json"
            try:
                self._support_list_cache = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._support_list_cache = {}
        return self._support_list_cache

    def _support_type_map(self, chara):
        supports = self._support_list()
        result = {}
        for card in (chara or {}).get("support_card_array") or []:
            slot = int(card.get("position") or 0)
            support_id = str(int(card.get("support_card_id") or 0))
            result[slot] = str((supports.get(support_id) or {}).get("type") or "")
        return result

    def _light_hello_slot(self, chara):
        for card in (chara or {}).get("support_card_array") or []:
            if int(card.get("support_card_id") or 0) == LIGHT_HELLO_SUPPORT_ID:
                return int(card.get("position") or 0)
        return 0

    def _light_hello_training_bonus(self, facility_idx):
        if not self._light_hello_first_training_done or (
            self._light_hello_first_training_turn is not None
            and self._light_hello_first_training_turn == self._light_hello_scoring_turn
        ):
            return float((self._last_preset or {}).get("grand_live_light_hello_first_score", 1.25))
        key = "grand_live_light_hello_wit_score" if int(facility_idx or 0) == 4 else "grand_live_light_hello_non_wit_score"
        return float((self._last_preset or {}).get(key, 1.2 if int(facility_idx or 0) == 4 else 1.0))

    def _attach_grand_live_score(self, command, score):
        if not command or not score:
            return command
        enriched = dict(command)
        enriched["_grand_live_score_detail"] = grand_live_score_detail(score)
        enriched["_grand_live_score_debug"] = grand_live_score_debug(score)
        return enriched

    def _token_score_bonus(self, command, preset):
        """Small Grand-Live-only value for performance tokens from a training.

        The server previews token gain per command in live_data_set.  We value
        low-stock tokens a little more, ignore capped/not-up token types, and
        keep the result deliberately small so this remains an overlay instead of
        a second full training scorer.
        """
        gain = self.live.command_token_gain(command.get("command_type"), command.get("command_id"))
        if not gain:
            return 0.0
        weight = float(preset.get("grand_live_token_score_weight", TOKEN_SCORE_WEIGHT))
        if weight <= 0:
            return 0.0
        tokens = self.live.tokens
        max_tokens = self.live.max_tokens
        capped = self.live.capped_types
        value = 0.0
        for ptype, amount in gain.items():
            amount = max(0, int(amount or 0))
            if not amount or ptype in capped:
                continue
            cap = int(max_tokens.get(ptype) or 0)
            current = int(tokens.get(ptype) or 0)
            multiplier = 1.0
            if cap > 0:
                ratio = current / float(cap)
                if ratio >= TOKEN_NEAR_CAP_RATIO:
                    multiplier = 0.5
                elif ratio <= TOKEN_SCARCE_RATIO:
                    multiplier = 1.5
                elif ratio <= TOKEN_LOW_RATIO:
                    multiplier = 1.25
            value += amount * multiplier
        return value * weight

    def _best_command(self, data, chara, preset):
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        rest = self._rest_command(enabled)
        recreation = self._recreation_command(enabled)
        medic = self._medic_command(enabled)
        training = [cmd for cmd in enabled if cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS]

        vital = int(chara.get("vital") or 0)
        motivation = int(chara.get("motivation") or 3)
        rest_threshold = int(preset.get("rest_threshold") or 48)
        high_failure = int(preset.get("high_failure_rest_threshold") or 35)
        medic_vital = int(preset.get("energy_medic_general") or 85)

        self._light_hello_scoring_turn = int(chara.get("turn") or 0)
        if not training:
            date = light_hello_date_command(enabled, chara, [], preset=preset, rest=rest)
            return date or recreation or rest or medic

        best_score_obj, score_rows = best_grand_live_training(self, training, data, chara, preset)
        best_score = best_score_obj.score if best_score_obj else -999.0
        best = best_score_obj.command if best_score_obj else None
        failure = int((best or {}).get("failure_rate") or 0)
        date = light_hello_date_command(enabled, chara, score_rows, preset=preset, rest=rest)

        good_training_score = float(preset.get("grand_live_good_training_score", GRAND_LIVE_GOOD_TRAINING_SCORE))
        vital_min = int(preset.get("grand_live_light_hello_date_vital_min", 35))
        vital_max = int(preset.get("grand_live_light_hello_date_vital_max", 65))
        if date and (motivation < int(preset.get("grand_live_light_hello_date_motivation_below", 3)) or (vital_min < vital < vital_max and best_score <= good_training_score)):
            return date
        if recreation and motivation <= 2:
            return recreation
        if medic and self._has_bad_status(chara) and vital <= medic_vital:
            return medic
        rest_score = float(preset.get("grand_live_rest_score", GRAND_LIVE_REST_SCORE))
        low_vital = vital <= rest_threshold
        high_failure_rate = failure >= high_failure
        low_score = best_score < rest_score
        if rest and (low_vital or high_failure_rate or low_score):
            if date and low_score and not low_vital and not high_failure_rate:
                return date
            return rest
        if best_score_obj and best_score_obj.light_hello:
            self._light_hello_first_training_done = True
            self._light_hello_first_training_turn = int(chara.get("turn") or 0)
        return self._attach_grand_live_score(best, best_score_obj)

    def _has_bad_status(self, chara):
        """chara_effect_id_array is a flat list of effect ids (see
        scenarios/mant/strategy.py _curable_bad_status_keys), not objects."""
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                if int(effect_id) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False
