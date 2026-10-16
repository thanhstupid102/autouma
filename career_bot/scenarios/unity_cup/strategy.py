from dataclasses import dataclass  # noqa: F401 -- preserve the legacy strategy facade
import json
from pathlib import Path

from career_bot.bot_config import UNITY_CONFIG_KEY
from career_bot.scenarios.base import DECK_PARTNERS, Decision, ScenarioStrategy, TRAINING_COMMANDS
from career_bot.scenarios.objectives import RouteObjectives, RouteObjectivesMixin
from career_bot.scenarios.score_primitives import BOND_TIER_HIGH, BOND_TIER_LOW, bond_tier
from career_bot.scenarios.unity_cup.config import *
from career_bot.scenarios.unity_cup.config import _unity_cap_rule, _unity_config, _unity_int, _unity_num, _unity_penalty_table, _unity_sequence  # noqa: F401
from career_bot.scenarios.unity_cup.scoring import *
from career_bot.scenarios.unity_cup.scoring import _normalized_failure, _raw_training_stat_gain, _safe_int, _unity_apply_cap, _unity_blue_purple_soul_bonus, _unity_blue_purple_soul_stack_bonus, _unity_current_stat, _unity_facility_label, _unity_is_matching_support_type, _unity_score_debug, _unity_score_detail, _unity_wit_full_energy_penalty  # noqa: F401
from career_bot.scenarios.unity_cup.team_roster import TeamRosterBuilder
from core.runtime_paths import resolve_master_json_path
from uma_data import distance_label


class UnityCupStrategy(RouteObjectivesMixin, ScenarioStrategy):
    scenario_id = UNITY_CUP_SCENARIO_ID
    display_label = "Unity Cup"
    config_preset_key = UNITY_CONFIG_KEY
    # single_mode_* career-API path prefix.
    endpoint_prefix = "single_mode_team"
    verbose_response_log = True
    # 7/8/9 = the post-training team-race phases (ready/started/ended); the
    # runner must not treat them as blocked states (see 2026-07-08 capture).
    extra_playing_states = frozenset({7, 8, 9})

    def __init__(self, race_planner=None):
        super().__init__(race_planner)
        base_dir = getattr(race_planner, "base_dir", None) if race_planner else None
        self._base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[3]
        self._state_root = getattr(race_planner, "state_root", None)
        self.objectives = RouteObjectives(base_dir)
        self.team_roster = TeamRosterBuilder(base_dir)
        self._debut_maiden_ids_cache = None
        self._debut_or_maiden_won = False
        self._maiden_recovery_forced_off_aptitude = False
        self._support_list_cache = None

    def extra_action_handlers(self):
        from career_bot.scenarios.unity_cup.team_race import run_team_race
        return {"team_race": run_team_race}

    def reset_run_state(self):
        super().reset_run_state()
        self._team_race_done_turns = set()
        self.objectives.reset()
        self._debut_or_maiden_won = False
        self._maiden_recovery_forced_off_aptitude = False

    # --- R1: Maiden races drop out of the pool for good once the trainee has
    # won the Junior Make Debut or a prior Maiden race (see tests/test_unity_race_rules.py) ---

    def _debut_maiden_program_ids(self):
        """(debut_program_ids, maiden_program_ids), cached. Name match mirrors
        career_bot/engine/racing.py _should_force_clocks's convention ("make debut"
        / "maiden race" substrings, case-insensitive) so both stay in lockstep."""
        if self._debut_maiden_ids_cache is None:
            debut_ids, maiden_ids = set(), set()
            programs = (self.race_planner.program if self.race_planner else {}) or {}
            for pid, info in programs.items():
                name = str((info or {}).get("name") or "").lower()
                if "make debut" in name:
                    debut_ids.add(int(pid))
                elif "maiden race" in name:
                    maiden_ids.add(int(pid))
            self._debut_maiden_ids_cache = (debut_ids, maiden_ids)
        return self._debut_maiden_ids_cache

    def _is_excluded_race_program(self, program_id):
        if not self._debut_or_maiden_won:
            return False
        _debut_ids, maiden_ids = self._debut_maiden_program_ids()
        return int(program_id or 0) in maiden_ids

    def record_race_result(self, program_id, rank):
        try:
            program_id = int(program_id or 0)
            rank = int(rank or 0)
        except (TypeError, ValueError):
            return
        if rank != 1 or not program_id:
            return
        debut_ids, maiden_ids = self._debut_maiden_program_ids()
        if program_id in debut_ids or program_id in maiden_ids:
            self._debut_or_maiden_won = True

    def _scan_race_history(self, data):
        """Server race_history (present on `load`/race_end responses, absent on
        most other turns -- see tests/test_unity_race_rules.py) is the ground
        truth for a resumed/reloaded career; record_race_result covers the live
        in-run case those other turns don't carry it on."""
        history = data.get("race_history") or []
        if not history:
            return
        debut_ids, maiden_ids = self._debut_maiden_program_ids()
        for entry in history:
            try:
                pid = int((entry or {}).get("program_id") or 0)
                rank = int((entry or {}).get("result_rank") or 0)
            except (TypeError, ValueError):
                continue
            if rank == 1 and (pid in debut_ids or pid in maiden_ids):
                self._debut_or_maiden_won = True
                break

    def _maiden_recovery_program(self, state, preset=None, objective_program_candidates=None):
        """Recover from a lost debut before later mandatory objectives.

        A lost debut leaves the trainee in maiden class, where mandatory
        objectives cannot be entered and the career fails unless a Maiden race
        is won first. Prefer training unless an offered recovery race fits both
        surface and distance aptitude; a race-only server turn must still pick
        the best offered recovery program so the career can advance.
        """
        self._maiden_recovery_forced_off_aptitude = False
        if self._debut_or_maiden_won or self.race_planner is None:
            return 0

        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(
            command.get("command_type") == 4
            and command.get("command_id") == 401
            and command.get("is_enable", 0)
            for command in commands
        )
        if not race_enabled:
            return 0
        forced_turn = not any(
            command.get("is_enable", 0)
            and (
                command.get("command_type") != 4
                or command.get("command_id") != 401
            )
            for command in commands
        )

        debut_ids, maiden_ids = self._debut_maiden_program_ids()
        recovery_ids = debut_ids | maiden_ids
        offered = []
        for condition in data.get("race_condition_array") or []:
            program_id = int(condition.get("program_id") or 0)
            if program_id in recovery_ids:
                offered.append(program_id)
        offered = [
            program_id
            for program_id in offered
            if (turn, program_id) not in self.race_planner.rejected
        ]
        if not offered:
            return 0

        objective_program_ids = {
            int(program_id or 0)
            for program_id in (objective_program_candidates or ())
            if int(program_id or 0)
        }

        chara = data.get("chara_info") or {}
        ground_aptitudes = {
            1: _safe_int(chara.get("proper_ground_turf")),
            2: _safe_int(chara.get("proper_ground_dirt")),
        }
        distance_bands = ("Sprint", "Mile", "Medium", "Long")
        distance_aptitudes = {
            "Sprint": _safe_int(chara.get("proper_distance_short")),
            "Mile": _safe_int(chara.get("proper_distance_mile")),
            "Medium": _safe_int(chara.get("proper_distance_middle")),
            "Long": _safe_int(chara.get("proper_distance_long")),
        }
        has_distance_aptitude = any(distance_aptitudes.values())

        best_distance_indexes = []
        if has_distance_aptitude:
            best_distance = max(distance_aptitudes.values())
            best_distance_indexes = [
                index for index, band in enumerate(distance_bands)
                if distance_aptitudes[band] == best_distance
            ]

        def program_metadata(program_id):
            program_info = self.race_planner.program.get(program_id)
            if not isinstance(program_info, dict):
                return False, 0, 0
            ground = _safe_int(program_info.get("ground"))
            distance = _safe_int(program_info.get("distance"))
            return bool(program_info) and ground > 0 and distance > 0, ground, distance

        def program_aptitudes(program_id):
            _has_metadata, ground, distance = program_metadata(program_id)
            band = distance_label(distance) if distance > 0 else None
            return ground_aptitudes.get(ground, 0), distance_aptitudes.get(band, 0)

        def recovery_key(program_id):
            ground_aptitude, _distance_aptitude = program_aptitudes(program_id)
            distance_gap = 0
            _has_metadata, _ground, distance = program_metadata(program_id)
            if has_distance_aptitude:
                if distance > 0:
                    band_index = distance_bands.index(distance_label(distance))
                    distance_gap = min(
                        abs(band_index - best_index)
                        for best_index in best_distance_indexes
                    )
                else:
                    distance_gap = len(distance_bands)
            return (-ground_aptitude, distance_gap, program_id)

        def objective_recovery_key(program_id):
            return (program_id not in objective_program_ids, recovery_key(program_id))

        if all(aptitude <= 0 for aptitude in (*ground_aptitudes.values(), *distance_aptitudes.values())):
            # Unknown aptitude data is not a known bad fit, so do not apply the gate.
            return min(offered, key=objective_recovery_key)

        min_aptitude = _unity_int(
            _unity_config(preset),
            "maiden_recovery_min_aptitude",
            UNITY_MAIDEN_RECOVERY_MIN_APTITUDE,
        )
        passing = []
        for program_id in offered:
            has_metadata, _ground, _distance = program_metadata(program_id)
            if not has_metadata or all(
                aptitude >= min_aptitude for aptitude in program_aptitudes(program_id)
            ):
                passing.append((program_id, has_metadata))
        if passing:
            # Unknown race metadata passes, but a known fitting race is preferred.
            return min(
                passing,
                key=lambda item: (
                    item[0] not in objective_program_ids,
                    not item[1],
                    recovery_key(item[0]),
                ),
            )[0]
        if not forced_turn:
            return 0

        # The server permits no training/rest command, so advance off-aptitude.
        self._maiden_recovery_forced_off_aptitude = True
        return min(offered, key=objective_recovery_key)

    def _team_done(self):
        if not hasattr(self, "_team_race_done_turns"):
            self._team_race_done_turns = set()
        return self._team_race_done_turns

    def _is_team_race_due(self, turn, playing_state):
        # Team race fires on the server's playing_state 7 -- the post-training
        # team race phase -- NOT on the turn number. Verified against a real
        # client capture (2026-07-08): turn 24 goes exec_command (training) ->
        # check_event 201029 -> playing_state 7 -> team_edit -> opponent_list.
        # Entering team_edit before playing_state 7 gets a 102 from
        # opponent_list (live failure career_log_lewpie_20260708_225115).
        # 8/9 = a previous run died mid team-race; the runner resumes the
        # remaining calls from the payload's playing_state.
        return int(playing_state or 0) in (7, 8, 9) and int(turn or 0) not in self._team_done()

    def mark_team_race_done(self, turn):
        self._team_done().add(int(turn or 0))

    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        self._last_preset = preset
        self._last_chara = chara
        turn = int(chara.get("turn") or 0)
        self._scan_race_history(data)

        decision = self._finish_common_decision(data, chara) or self._career_end_decision(chara, reason="finished")
        if decision:
            return decision
        decision = self._event_decision(data, chara)
        if decision:
            return decision

        playing_state = int(chara.get("playing_state") or 0)
        if self._is_team_race_due(turn, playing_state):
            return Decision("team_race", {"current_turn": turn, "playing_state": playing_state, "_strategy": self, "_facility": "Unity Cup team race"}, "Unity Cup team race")
        decision = self._race_state_decision(data, chara)
        if decision:
            return decision

        candidates = ()
        if self.race_planner:
            candidates = self.objectives.race_program_candidates_for_turn(chara, turn)

        if self.race_planner and not self._debut_or_maiden_won:
            recovery_pid = self._maiden_recovery_program(
                state,
                preset,
                objective_program_candidates=candidates,
            )
            if recovery_pid:
                recovery_label = (
                    " (maiden recovery, forced, off-aptitude)"
                    if self._maiden_recovery_forced_off_aptitude
                    else " (maiden recovery)"
                )
                return Decision(
                    "race",
                    {"program_id": recovery_pid, "current_turn": turn, "_strategy": self},
                    self.race_planner.label(recovery_pid) + recovery_label,
                )

        if self.race_planner:
            forced_program_id = self.race_planner.forced_program(state, preferred=candidates or None)
            if forced_program_id:
                payload = {"program_id": forced_program_id, "current_turn": turn, "_strategy": self, "_mandatory": True}
                required_rank = self.objectives.required_rank_for_turn(chara, turn)
                if required_rank is not None:
                    payload["_required_rank"] = required_rank
                return Decision("race", payload, self.race_planner.label(forced_program_id))
            forced_race_exhausted = getattr(self.race_planner, "forced_race_exhausted", None)
            if forced_race_exhausted and forced_race_exhausted(state):
                return Decision("idle", {}, f"forced race turn {turn}: server rejected every offered program")

        if self.race_planner:
            # Preset extra races (race preset from the UI) are optional but
            # user-chosen -- race them when available. Objectives/finals
            # (forced above) and the team race always take priority. Preset
            # picks skip Maiden races once R1's won-state guard trips (see
            # _is_excluded_race_program).
            preset_program_id = self.race_planner.choose(state, preset)
            if preset_program_id and not self._is_excluded_race_program(preset_program_id):
                return Decision("race", {"program_id": preset_program_id, "current_turn": turn, "_strategy": self}, self.race_planner.label(preset_program_id))

        command = self._unity_best_command(data, chara, preset)
        if command:
            return self._command_decision(command, chara)
        return Decision("idle", {}, "no action")

    def _command_decision(self, command, chara):
        decision = super()._command_decision(command, chara)
        payload = decision.payload
        if "_unity_score_detail" in command:
            payload["_score_detail"] = command["_unity_score_detail"]
        if "_unity_score_debug" in command:
            payload["_score_debug"] = command["_unity_score_debug"]
        if "_unity_facility_label" in command:
            payload["_facility_label"] = command["_unity_facility_label"]
        return decision

    def _unity_attach_score_debug(self, command, selected_score, tie_break_score=None):
        if not selected_score or not command:
            return command
        command_id = _safe_int((command or {}).get("command_id"))
        if _safe_int((command or {}).get("command_type")) != 1 or command_id not in TRAINING_COMMANDS:
            return command
        enriched = dict(command)
        enriched["_unity_score_detail"] = _unity_score_detail(selected_score, tie_break_score)
        enriched["_unity_score_debug"] = _unity_score_debug(selected_score, tie_break_score)
        enriched["_unity_facility_label"] = _unity_facility_label(selected_score)
        return enriched

    def _unity_best_command(self, data, chara, preset):
        cfg = _unity_config(preset)
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        rest = self._rest_command(enabled)
        recreation = self._recreation_command(enabled)
        medic = self._medic_command(enabled)
        training = [cmd for cmd in enabled if cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS]
        turn = _safe_int(chara.get("turn"))
        vital = _safe_int(chara.get("vital"))
        motivation = _safe_int(chara.get("motivation"), 5)

        if not training:
            return self._unity_no_training_command(rest, recreation, medic, turn, chara, motivation, preset, cfg)
        scores = [self._unity_score_training(cmd, data, chara, preset) for cmd in training]
        eligible_scores = [score for score in scores if score.score >= _unity_num(cfg, "min_train_score", UNITY_MIN_TRAIN_SCORE)]
        best, best_tie = self._unity_pick_with_context(eligible_scores, turn, preset)
        wit, wit_tie = self._unity_best_wit_with_context(eligible_scores, preset)
        purple, _purple_tie = self._unity_best_purple_with_context(eligible_scores, preset)

        if self._summer_bad_status_rest(turn, chara, preset) and rest:
            return rest
        medic_command = self._unity_medic_override_command(medic, chara, turn, preset, best, wit, purple, cfg)
        if medic_command:
            return medic_command
        if not eligible_scores:
            return self._unity_no_eligible_scores_command(recreation, motivation, rest, medic, cfg)
        if turn in set(_unity_sequence(cfg, "final_train_turns", UNITY_FINAL_TRAIN_TURNS)):
            return self._unity_final_train_turn_command(cfg, vital, purple, rest, eligible_scores, wit, wit_tie, best, best_tie, turn, preset)
        if turn >= _unity_int(cfg, "late_turn", 65):
            return self._unity_late_turn_command(cfg, vital, purple, rest, best, best_tie, wit, wit_tie, turn, eligible_scores, preset)
        if vital < _unity_int(cfg, "low_energy_vital_threshold", 50):
            low_energy = self._unity_low_energy_command(eligible_scores, rest, recreation, turn, vital, motivation, preset)
            if low_energy:
                return low_energy
        recreation_command = self._unity_recreation_safe_wit_command(recreation, motivation, wit, wit_tie, best, cfg)
        if recreation_command:
            return recreation_command
        if self._unity_should_recreate(recreation, turn, motivation, best, wit, preset):
            return recreation
        return self._unity_attach_score_debug(best.command, best, best_tie) if best else rest or recreation or medic

    def _unity_no_training_command(self, rest, recreation, medic, turn, chara, motivation, preset, cfg):
        if self._summer_bad_status_rest(turn, chara, preset) and rest:
            return rest
        if recreation and motivation < _unity_int(cfg, "recreation_motivation_threshold", 3):
            return recreation
        if medic and self._has_bad_status(chara) and not self._defer_medic_until_summer(turn, chara, preset):
            return medic
        return rest or recreation or medic

    def _unity_medic_override_command(self, medic, chara, turn, preset, best, wit, purple, cfg):
        if not (medic and self._has_bad_status(chara) and not self._defer_medic_until_summer(turn, chara, preset)):
            return None
        safe_wit = wit and wit.failure < _unity_num(cfg, "safe_wit_failure_max", 0.10) and wit.score >= (_unity_num(cfg, "safe_wit_score_early", UNITY_SAFE_WIT_SCORE_EARLY) if turn < 24 else _unity_num(cfg, "safe_wit_score_late", UNITY_SAFE_WIT_SCORE_LATE))
        safe_late = turn >= _unity_int(cfg, "late_turn", 65) and best and (best.is_wit or best.failure <= _unity_num(cfg, "medic_safe_late_failure_max", 0.10) or best.purple_count)
        if not (purple and purple.score > _unity_num(cfg, "medic_safe_purple_score_threshold", 3.0)) and not safe_wit and not safe_late:
            return medic
        return None

    def _unity_no_eligible_scores_command(self, recreation, motivation, rest, medic, cfg):
        if recreation and motivation < _unity_int(cfg, "recreation_motivation_threshold", 3):
            return recreation
        return rest or recreation or medic

    def _unity_final_train_turn_command(self, cfg, vital, purple, rest, eligible_scores, wit, wit_tie, best, best_tie, turn, preset):
        if vital < _unity_int(cfg, "final_train_min_vital", 10) and not purple and rest:
            return rest
        non_wit, non_wit_tie = self._unity_pick_with_context([s for s in eligible_scores if not s.is_wit and s.failure <= _unity_num(cfg, "near_tie_non_wit_failure_max", 0.10)], turn, preset)
        if non_wit:
            return self._unity_attach_score_debug(non_wit.command, non_wit, non_wit_tie)
        if wit and vital > _unity_int(cfg, "final_train_min_vital", 10) and not self._late_low_energy_wit_blocked(wit, turn, vital, preset):
            return self._unity_attach_score_debug(wit.command, wit, wit_tie)
        return self._unity_attach_score_debug(best.command, best, best_tie) if best and not self._late_low_energy_wit_blocked(best, turn, vital, preset) else rest

    def _unity_late_turn_command(self, cfg, vital, purple, rest, best, best_tie, wit, wit_tie, turn, eligible_scores, preset):
        if vital < _unity_int(cfg, "late_min_vital", 10) and not purple and rest:
            return rest
        if self._late_low_energy_wit_blocked(best, turn, vital, preset):
            best, best_tie = self._unity_pick_with_context([score for score in eligible_scores if not score.is_wit], turn, preset)
            wit = None
            wit_tie = None
        selected = best or wit
        selected_tie = best_tie if best else wit_tie
        return self._unity_attach_score_debug(selected.command, selected, selected_tie) if selected else rest

    def _unity_recreation_safe_wit_command(self, recreation, motivation, wit, wit_tie, best, cfg):
        if recreation and motivation < _unity_int(cfg, "recreation_motivation_threshold", 3) and wit and wit.score >= _unity_num(cfg, "recreation_safe_wit_score", 1.0) and wit.failure < _unity_num(cfg, "safe_wit_failure_max", 0.10) and best and best.failure > _unity_num(cfg, "recreation_best_failure_threshold", 0.25):
            return self._unity_attach_score_debug(wit.command, wit, wit_tie)
        return None

    def _support_list(self):
        if self._support_list_cache is None:
            path = resolve_master_json_path(
                self._base_dir,
                "support_list.json",
                self._state_root,
            )
            try:
                self._support_list_cache = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._support_list_cache = {}
        return self._support_list_cache

    def _support_type_map(self, chara):
        supports = self._support_list()
        result = {}
        for card in (chara or {}).get("support_card_array") or []:
            slot = _safe_int(card.get("position"))
            support_id = str(_safe_int(card.get("support_card_id")))
            result[slot] = str((supports.get(support_id) or {}).get("type") or "")
        return result

    def _team_command_by_id(self, data):
        return {
            _safe_int(cmd.get("command_id")): cmd
            for cmd in ((data.get("team_data_set") or {}).get("command_info_array") or [])
            if _safe_int(cmd.get("command_id"))
        }

    @staticmethod
    def _strict_int(value):
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, float) and not value.is_integer():
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _strict_positive_int(cls, value):
        parsed = cls._strict_int(value)
        return parsed if parsed is not None and parsed > 0 else None

    def _partner_ids_from_sources(self, key, command, team_command):
        source = team_command if team_command and key in team_command else command
        return {
            partner_id
            for value in ((source or {}).get(key) or [])
            if (partner_id := self._strict_positive_int(value)) is not None
        }

    def _facility_guide_partner_ids(self, command, team_command):
        return self._partner_ids_from_sources("guide_event_partner_array", command, team_command)

    def _facility_soul_event_partner_ids(self, command, team_command):
        return self._partner_ids_from_sources("soul_event_partner_array", command, team_command)

    def _facility_sp_soul_event_partner_ids(self, command, team_command):
        return self._partner_ids_from_sources("sp_soul_event_partner_array", command, team_command)

    def _unity_classify_facility_souls(self, command, team_command, _data=None):
        white_ids = self._facility_guide_partner_ids(command, team_command)
        blue_ids = self._facility_soul_event_partner_ids(command, team_command)
        purple_ids = self._facility_sp_soul_event_partner_ids(command, team_command)
        return white_ids, blue_ids, purple_ids

    def _unity_score_training(self, command, data, chara, preset):
        cfg = _unity_config(preset)
        command_id = _safe_int(command.get("command_id"))
        facility_idx = TRAINING_COMMANDS[command_id]
        is_wit = facility_idx == UNITY_WIT_FACILITY_IDX or command_id in UNITY_WIT_COMMANDS
        failure = _normalized_failure(command)
        team_command = self._team_command_by_id(data).get(command_id, {})
        white_ids, blue_ids, purple_ids = self._unity_classify_facility_souls(command, team_command, data)

        white_count = len(white_ids)
        blue_count = len(blue_ids)
        purple_count = len(purple_ids)
        if purple_count:
            failure = 0.0
        soul_count = white_count + blue_count + purple_count
        score = _unity_num(cfg, "white_soul_score", 0.525) * white_count
        blue_purple_count = 0
        for _partner_id in sorted(blue_ids):
            score += _unity_num(cfg, "blue_soul_score", 1.0) + _unity_blue_purple_soul_bonus(facility_idx, blue_purple_count, cfg)
            blue_purple_count += 1
        for _partner_id in sorted(purple_ids):
            score += _unity_num(cfg, "purple_soul_score", 1.3) + _unity_blue_purple_soul_bonus(facility_idx, blue_purple_count, cfg)
            blue_purple_count += 1

        bonds = self._bond_map(chara)
        support_types = self._support_type_map(chara)
        bondable_count = 0
        rainbow_count = 0
        has_wit_rainbow = False
        # DIVERGENCE (vs MANT): partners come from the deduplicated int slot set
        # and non-deck ids are dropped here -- Unity scores team members only
        # through the soul-colour arrays above, never as bond. MANT walks the raw
        # training_partner_array and gives NPCs an _npc_score.
        for partner_id in self._command_partner_slots(command):
            if partner_id not in DECK_PARTNERS:
                continue
            bond = _safe_int(bonds.get(partner_id))
            support_type = support_types.get(partner_id, "").lower()
            is_wit_support = support_type in UNITY_WIT_SUPPORT_TYPES
            is_matching_support = _unity_is_matching_support_type(support_type, facility_idx)
            tier = bond_tier(bond)
            if tier == BOND_TIER_LOW:
                score += _unity_num(cfg, "support_bond_low_score", 1.0)
                bondable_count += 1
            elif tier == BOND_TIER_HIGH:
                score += _unity_num(cfg, "support_bond_mid_score", 1.3)
                bondable_count += 1
            # DIVERGENCE (vs MANT): a maxed support only rainbows when its type
            # matches the facility; an off-type maxed support gets the small
            # off_type_high_bond_score instead. MANT counts every maxed deck
            # partner as a rainbow regardless of type.
            elif is_matching_support:
                rainbow_count += 1
                if is_wit and is_wit_support:
                    has_wit_rainbow = True
                    score += _unity_num(cfg, "wit_rainbow_score_late", 2.0) if _safe_int((chara or {}).get("turn")) >= _unity_int(cfg, "late_turn", 65) else _unity_num(cfg, "wit_rainbow_score_early", 1.3)
                else:
                    score += _unity_num(cfg, "matching_rainbow_score", 1.45)
            else:
                score += _unity_num(cfg, "off_type_high_bond_score", 0.25)
        turn = _safe_int((chara or {}).get("turn"))
        if is_wit:
            score += _unity_num(cfg, "wit_base_score", UNITY_WIT_BASE_SCORE)
        score = _unity_apply_cap(score, facility_idx, chara, cfg) - (failure * _unity_num(cfg, "failure_score_penalty", UNITY_FAILURE_SCORE_PENALTY))
        if is_wit:
            score -= _unity_wit_full_energy_penalty(
                turn,
                (chara or {}).get("vital"),
                (chara or {}).get("max_vital", 100),
                cfg,
            )
        return UnityTrainingScore(
            command=command,
            command_id=command_id,
            facility_idx=facility_idx,
            is_wit=is_wit,
            score=score,
            failure=failure,
            raw_gain=_raw_training_stat_gain(command),
            bondable_count=bondable_count,
            purple_count=purple_count,
            blue_count=blue_count,
            soul_count=soul_count,
            has_wit_rainbow=has_wit_rainbow,
            white_count=white_count,
            rainbow_count=rainbow_count,
        )

    def _unity_pick_best_training(self, scores, turn, preset=None):
        selected, _tie_break = self._unity_pick_with_context(scores, turn, preset)
        return selected

    def _unity_pick_with_context(self, scores, turn, preset=None):
        if not scores:
            return None, None
        cfg = _unity_config(preset)
        top_two = sorted(scores, key=lambda score: score.score, reverse=True)[:2]
        if len(top_two) == 1 or top_two[0].score - top_two[1].score > _unity_num(cfg, "near_tie_gap", 0.5):
            return top_two[0], None
        first, second = top_two
        if first.is_wit != second.is_wit:
            non_wit = first if not first.is_wit else second
            wit = second if non_wit is first else first
            selected = non_wit if non_wit.failure <= _unity_num(cfg, "near_tie_non_wit_failure_max", 0.10) else wit
            return selected, second if selected is first else first
        first_metadata = (first.purple_count, first.blue_count, first.bondable_count, first.raw_gain)
        second_metadata = (second.purple_count, second.blue_count, second.bondable_count, second.raw_gain)
        selected = first if first_metadata >= second_metadata else second
        return selected, second if selected is first else first

    def _unity_best_wit_with_context(self, scores, preset=None):
        return self._unity_pick_with_context([score for score in scores if score.is_wit], 0, preset)

    def _unity_best_purple_with_context(self, scores, preset=None):
        return self._unity_pick_with_context([score for score in scores if score.purple_count >= 1], 0, preset)

    def _late_low_energy_wit_blocked(self, score, turn, vital, preset=None):
        cfg = _unity_config(preset)
        return bool(score and turn >= _unity_int(cfg, "late_turn", 65) and vital < _unity_int(cfg, "late_low_energy_vital_threshold", 30) and score.is_wit and score.score <= _unity_num(cfg, "late_low_energy_wit_score_min", UNITY_LATE_LOW_ENERGY_WIT_SCORE_MIN))

    def _has_bad_status(self, chara):
        return any(_safe_int(effect_id) in UNITY_BAD_STATUS_IDS for effect_id in (chara or {}).get("chara_effect_id_array") or [])

    def _defer_medic_until_summer(self, turn, chara, preset=None):
        ranges = _unity_sequence(_unity_config(preset), "medic_defer_ranges", UNITY_MEDIC_DEFER_RANGES)
        return self._has_bad_status(chara) and any(len(row) >= 2 and int(row[0]) <= turn <= int(row[1]) for row in ranges)

    def _summer_bad_status_rest(self, turn, chara, preset=None):
        return self._has_bad_status(chara) and turn in set(_unity_sequence(_unity_config(preset), "summer_bad_status_turns", UNITY_SUMMER_BAD_STATUS_TURNS))

    def _unity_should_recreate(self, recreation, turn, motivation, best, wit, preset=None):
        cfg = _unity_config(preset)
        if not recreation or motivation >= _unity_int(cfg, "recreation_motivation_threshold", 3):
            return False
        if wit and wit.score >= _unity_num(cfg, "recreation_safe_wit_score", 1.0) and wit.failure < _unity_num(cfg, "safe_wit_failure_max", 0.10):
            return False
        if best is None:
            return True
        return best.score < _unity_num(cfg, "recreation_best_score_threshold", 3.0) or ((not best.is_wit or best.purple_count or best.blue_count) and best.failure > _unity_num(cfg, "recreation_best_failure_threshold", 0.25))

    def _unity_low_energy_command(self, scores, rest, recreation, turn, vital, motivation, preset=None):
        cfg = _unity_config(preset)
        purple, purple_tie = self._unity_best_purple_with_context(scores, preset)
        if purple and purple.score > _unity_num(cfg, "low_energy_purple_score_threshold", 3.0):
            return self._unity_attach_score_debug(purple.command, purple, purple_tie)
        wit, wit_tie = self._unity_best_wit_with_context(scores, preset)
        if self._late_low_energy_wit_blocked(wit, turn, vital, preset):
            wit = None
            wit_tie = None
        if wit and wit.failure < _unity_num(cfg, "safe_wit_failure_max", 0.10) and wit.score >= (_unity_num(cfg, "safe_wit_score_early", UNITY_SAFE_WIT_SCORE_EARLY) if turn < 24 else _unity_num(cfg, "safe_wit_score_late", UNITY_SAFE_WIT_SCORE_LATE)):
            return self._unity_attach_score_debug(wit.command, wit, wit_tie)
        best, _best_tie = self._unity_pick_with_context(scores, turn, preset)
        if self._unity_should_recreate(recreation, turn, motivation, best, wit, preset):
            return recreation
        return rest
