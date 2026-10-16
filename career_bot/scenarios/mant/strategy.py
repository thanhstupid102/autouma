from career_bot.game_calendar import SUMMER_CAMP_TURNS as GAME_SUMMER_CAMP_TURNS
from career_bot.scenarios.base import (
    Decision,
    LATE_AGGRESSIVE_TURN,
    LATE_UNCOVERED_FAILURE_REST,
    ScenarioStrategy,
    TRAINING_COMMANDS,
)
from career_bot.scenarios.mant.outings import SiriusThroneOutingsMixin
from career_bot.scenarios.mant.rescue import MantRescueMixin
from career_bot.scenarios.scoring import TrainingScoreMixin


SUMMER_CAMP_TURNS = set(GAME_SUMMER_CAMP_TURNS)
SUMMER_CONSERVE_TURNS = {36, 60}
SUMMER_CONSERVE_ENERGY = 60
ENERGY_FAST_MEDIC = 80
ENERGY_MEDIC_GENERAL = 85
MEDIC_TANK_TURNS = 6
RACE_SKIP_TRAIN_STAT = 30
LATE_TRAIN_STAT_TARGET = 20
LATE_STAT_CAP = 1200
BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}


class MantStrategy(TrainingScoreMixin, SiriusThroneOutingsMixin, MantRescueMixin, ScenarioStrategy):
    scenario_id = 4
    display_label = "MANT / Trackblazer"
    # single_mode_* career-API path prefix.
    endpoint_prefix = "single_mode_free"
    handles_shop_items = True
    free_clock_retry = True
    prefers_rival_races = True
    SUMMER_CAMP_TURNS = SUMMER_CAMP_TURNS
    LATE_UNCOVERED_FAILURE_REST = LATE_UNCOVERED_FAILURE_REST

    @classmethod
    def apply_config_to_preset(cls, result, values):
        import copy
        mant_config = dict(result.get("mant_config") or {})
        for key, value in values.items():
            if key == "mant_config":
                mant_config.update(copy.deepcopy(value))
            else:
                result[key] = copy.deepcopy(value)
        result["mant_config"] = mant_config
        return result

    def __init__(self, race_planner=None):
        super().__init__(race_planner)
        self._early_group_card_clicked_slots = set()
        self._early_group_card_last_turn = None
        self._bad_status_first_turn = {}

    def reset_run_state(self):
        super().reset_run_state()
        self._early_group_card_clicked_slots.clear()
        self._early_group_card_last_turn = None
        self._bad_status_first_turn.clear()

    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        # Stash context for deferred event scoring (event choices are resolved
        # later via choose_from_event, which has no preset/chara of its own).
        self._last_preset = preset
        self._last_chara = chara
        decision = self._finish_common_decision(data, chara)
        if decision:
            return decision
        decision = self._event_decision(data, chara)
        if decision:
            return decision
        decision = self._career_end_decision(chara)
        if decision:
            return decision
        decision = self._race_state_decision(data, chara)
        if decision:
            return decision
        commands = home.get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        turn = int(chara.get("turn") or 0)
        scheduled = self._scheduled_recreation(enabled, turn, chara, preset)
        if scheduled:
            return self._command_decision(scheduled, chara)
        if self.race_planner:
            forced_program_id = self.race_planner.forced_program(state)
            if forced_program_id:
                return Decision("race", {"program_id": forced_program_id, "current_turn": chara.get("turn", 0), "_strategy": self}, self.race_planner.label(forced_program_id))
            forced_race_exhausted = getattr(self.race_planner, "forced_race_exhausted", None)
            if forced_race_exhausted and forced_race_exhausted(state):
                return Decision("idle", {}, f"forced race turn {turn}: server rejected every offered program")
            program_id = self.race_planner.choose(state, preset)
            if program_id:
                return Decision("race", {"program_id": program_id, "current_turn": chara.get("turn", 0), "_strategy": self}, self.race_planner.label(program_id))
        command = self._best_command(data, chara, preset)
        if command:
            return self._command_decision(command, chara)
        return Decision("idle", {}, "no action")

    def _best_command(self, data, chara, preset):
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        rest = self._rest_command(enabled)
        recreation = self._recreation_command(enabled)
        medic = self._medic_command(enabled)
        training = [cmd for cmd in enabled if cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS]
        turn = int(chara.get("turn") or 0)
        vital = int(chara.get("vital") or 0)
        motivation = int(chara.get("motivation") or 3)
        late_turn = int(preset.get("late_aggressive_turn") or LATE_AGGRESSIVE_TURN)
        high_failure = int(preset.get("high_failure_rest_threshold") or 35)
        medic_vital = int(preset.get("energy_medic_general") or ENERGY_MEDIC_GENERAL)
        medic_ready = bool(medic and self._medic_ready_after_tank(chara, preset))
        scheduled = self._scheduled_recreation(enabled, turn, chara, preset)
        if scheduled:
            return scheduled
        if not training:
            if recreation:
                return recreation
            if medic_ready and vital <= medic_vital:
                return medic
            return rest
        early = self._early_group_card_command(training, chara, turn, preset)
        if early:
            best_score, best = self._score_command(early, data, chara, preset), early
        else:
            best_score, best = self._pick_scored_training(training, data, chara, preset, turn)
        rest_threshold = int(preset.get("rest_threshold") or 48)
        failure = int(best.get("failure_rate") or 0)
        summer_rest_threshold = int(preset.get("summer_recreate_vital_threshold") or 40)
        if turn in SUMMER_CAMP_TURNS and recreation and (vital <= summer_rest_threshold or failure >= high_failure or best_score < 0):
            if not self._can_rescue_training(data, chara, preset, best, best_score, vital, failure, summer_rest_threshold):
                return recreation
            # else: summer has the same rescue path as rest -- keep the strong turn,
            # let items/use.py spend the smallest sufficient Vita, then re-decision trains.
        if self._should_recreate(recreation, preset, turn, motivation, vital, best_score):
            return recreation
        if medic_ready and vital <= medic_vital and not self._good_training_over_medic(best, best_score, chara, preset):
            return medic
        failure_rest = failure >= high_failure or (turn >= late_turn and failure > int(preset.get("late_uncovered_failure_rest") or LATE_UNCOVERED_FAILURE_REST))
        if rest and (vital <= rest_threshold or failure_rest or best_score < 0):
            if not self._can_rescue_training(data, chara, preset, best, best_score, vital, failure, rest_threshold):
                return rest
            # else: a strong/rainbow turn we can charm or energy-up into. Don't rest
            # it away -- fall through to train it. items/use.py tops up energy with the
            # smallest sufficient Vita (+ charm) before the command executes, and the
            # post-item re-decision then runs the training at the restored energy.
        conserve = self._summer_conserve_command(enabled, turn, vital, best_score, preset, rest, recreation)
        if conserve:
            return conserve
        return best

    def _pick_scored_training(self, training, data, chara, preset, turn):
        scored = [(self._score_command(cmd, data, chara, preset), cmd) for cmd in training]
        if 48 < turn <= 72:
            stat_keys = ["speed", "stamina", "power", "guts", "wiz"]
            highest_idx = max(range(5), key=lambda idx: int(chara.get(stat_keys[idx]) or 0))
            scored = [(score * 0.95 if TRAINING_COMMANDS.get(cmd.get("command_id"), 0) == highest_idx and score > 0 else score, cmd) for score, cmd in scored]
        if turn <= 24 and preset.get("junior_bond_rush", True):
            # Junior bond-rush: on non-race training turns, prioritize the training
            # that gathers the most not-yet-maxed non-group support partners (the 4
            # normal cards) over taking an existing rainbow, using the normal score
            # only as a tiebreak. Sirius/Throne are handled only by the once-each
            # click rule above, then ignored for bond priority.
            return max(scored, key=lambda row: (self._bondable_count(row[1], chara, preset), row[0]))
        if turn <= 36:
            max_bondable = max(self._bondable_count(cmd, chara, preset) for _score, cmd in scored)
            return max(scored, key=lambda row: (TRAINING_COMMANDS.get(row[1].get("command_id")) == 4 and self._bondable_count(row[1], chara, preset) >= max_bondable, row[0]))
        return max(scored, key=lambda row: row[0])

    def _summer_conserve_command(self, enabled, turn, vital, best_score, preset, rest, recreation):
        conserve_turns = set(preset.get("summer_conserve_turns") or SUMMER_CONSERVE_TURNS)
        if turn not in conserve_turns:
            return None
        if best_score >= float(preset.get("summer_score_threshold") or 0.34):
            return None
        if vital < int(preset.get("summer_conserve_energy") or SUMMER_CONSERVE_ENERGY):
            if turn in SUMMER_CAMP_TURNS and recreation:
                return recreation
            return rest
        return self._enabled_training_idx(enabled, 4)

    def _curable_bad_status_keys(self, chara, preset):
        wanted = self._cure_condition_names(preset)
        if not wanted:
            return set()
        result = set()
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            key = self._condition_key(name)
            if key and key in wanted:
                result.add(key)
        return result

    def _medic_ready_after_tank(self, chara, preset):
        active = self._curable_bad_status_keys(chara, preset)
        if not active:
            self._bad_status_first_turn.clear()
            return False
        turn = int((chara or {}).get("turn") or 0)
        if self._bad_status_first_turn and turn < min(self._bad_status_first_turn.values()):
            self._bad_status_first_turn.clear()
        self._bad_status_first_turn = {k: v for k, v in self._bad_status_first_turn.items() if k in active}
        for key in active:
            self._bad_status_first_turn.setdefault(key, turn)
        # ponytail: resume mid-sickness restarts tank window; persist first-turn map if exact cross-restart age needed.
        tank_turns = int((preset or {}).get("medic_tank_turns", MEDIC_TANK_TURNS))
        return any(turn - first_turn >= tank_turns for first_turn in self._bad_status_first_turn.values())

    def _good_training_over_medic(self, command, score, chara, preset):
        if not command or int(command.get("command_type") or 0) != 1:
            return False
        if self._rainbow_count(command, chara) > 0:
            return True
        if self._command_stat_gain(command) >= float((preset or {}).get("medic_good_train_stat", (preset or {}).get("race_skip_train_stat", RACE_SKIP_TRAIN_STAT)) or 0):
            return True
        return float(score or 0) >= float((preset or {}).get("medic_good_train_score", (preset or {}).get("rescue_score_threshold", 0.55)) or 0.55)

    def _cure_condition_names(self, preset):
        result = set()
        names = preset.get("cure_asap_conditions") or []
        if isinstance(names, str):
            names = names.split(",")
        for name in names:
            key = self._condition_key(name)
            if key:
                result.add(key)
        return result

    def _condition_key(self, name):
        text = str(name or "").strip()
        if not text or text.startswith("("):
            return ""
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def _mood_threshold(self, turn, preset):
        if turn <= 36:
            return int(preset.get("motivation_threshold_year1") or 3)
        if turn <= 60:
            return int(preset.get("motivation_threshold_year2") or 4)
        return int(preset.get("motivation_threshold_year3") or 4)

    def _should_recreate(self, recreation, preset, turn, motivation, vital, best_score):
        if not recreation:
            return False
        if turn in SUMMER_CAMP_TURNS:
            return False
        if turn >= int(preset.get("late_aggressive_turn") or LATE_AGGRESSIVE_TURN) and not preset.get("late_allow_recreation", False):
            return False
        # Opt-in: proactively top mood up to GREAT (motivation 5) on weak, energy-spare
        # training turns -- a strong-run habit (the GREAT multiplier on the next good turn
        # outvalues a mediocre training now). Default off; never fires on a rainbow/strong
        # turn (gated by best_score) or when energy is near full.
        if preset.get("mood_target_recreate") and motivation < 5 and vital < 90 \
                and best_score <= float(preset.get("mood_recreate_max_score") or 0.30):
            return True
        if motivation < self._mood_threshold(turn, preset) and vital < 90 and best_score <= 0.3:
            return True
        if not preset.get("prioritize_recreation"):
            return False
        thresholds = preset.get("pal_thresholds") or []
        if not thresholds:
            return False
        stage = int(preset.get("_pal_event_stage") or 0)
        if stage >= len(thresholds):
            stage = 0
        row = thresholds[stage]
        if not isinstance(row, list) or len(row) < 2:
            return False
        mood_ok = motivation <= int(row[0])
        energy_ok = vital <= int(row[1])
        score_ok = True
        if len(row) > 2:
            score_ok = best_score <= float(row[2])
        return mood_ok and energy_ok and score_ok
