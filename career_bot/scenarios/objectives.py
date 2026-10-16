"""Mandatory trainee route race objectives from master data.

Most scenarios hand the trainee route objectives via single_mode_route_race;
MANT is the exception -- its point objectives (condition_type 2/7/8/9) are
server-driven and never read by the bot. Fan objectives (condition_type 3) are
also ignored; users schedule any optional races through race presets. A
scenario with route races owns a RouteObjectives instance and mixes in
RouteObjectivesMixin.
"""

from typing import Any, TypedDict

import uma_data

# single_mode_route_race.condition_type: 1 = race objective (condition_id is a
# race_group_id resolved through single_mode_race_group, unless target_type ==
# 3 -- the turn 74/76/78 finals, whose condition_id is a server-forced
# sentinel). Most groups identity-map to one program; JBC groups 20002/20003
# contain four year variants. Treating Copano Rickey's group 20003 as a program
# id caused the 2026-07-17 turn-69 QE2-instead-of-JBC failure. condition_type 3
# = ignored fan objective; 2/7/8/9 are ignored MANT-specific point objectives.
ROUTE_RACE_CONDITION_TYPE = 1
ROUTE_FINALS_TARGET_TYPE = 3


class RouteSchedule(TypedDict):
    """Turn -> mandatory-race schedule derived from one trainee's route ids.

    race_turns: turn -> candidate program ids (a race group can hold several).
    race_ranks: turn -> required finish rank (0 = none demanded).
    finals_turns: turns whose objective is a server-forced final.
    """

    race_turns: dict[int, tuple[int, ...]]
    race_ranks: dict[int, int]
    finals_turns: set[int]


def _empty_schedule() -> RouteSchedule:
    return {"race_turns": {}, "race_ranks": {}, "finals_turns": set()}


class RouteObjectives:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir
        self._objectives_cache: dict[Any, Any] | None = None
        self._race_groups_cache: dict[Any, Any] | None = None
        self._route_ids_cache: tuple[int, ...] | None = None
        self._schedule: RouteSchedule = _empty_schedule()

    def reset(self):
        self._route_ids_cache = None
        self._schedule = _empty_schedule()

    def objectives_map(self):
        if self._objectives_cache is None:
            objectives: dict[Any, Any] = {}
            race_groups: dict[Any, Any] = {}
            base_dir = self.base_dir
            if base_dir:
                try:
                    result = uma_data.load_route_race_objectives(base_dir)
                    objectives = (result or {}).get("objectives") or {}
                    race_groups = (result or {}).get("race_groups") or {}
                except Exception:
                    objectives = {}
                    race_groups = {}
            self._objectives_cache = objectives
            self._race_groups_cache = race_groups
        return self._objectives_cache

    def race_groups_map(self):
        # objectives_map populates both caches from one master-data load.
        self.objectives_map()
        return self._race_groups_cache or {}

    def _build_schedule(self, route_ids) -> RouteSchedule:
        objectives = self.objectives_map()
        race_groups = self.race_groups_map()
        race_turns: dict[int, tuple[int, ...]] = {}
        race_ranks: dict[int, int] = {}
        finals_turns: set[int] = set()
        for route_id in route_ids:
            row = objectives.get(route_id)
            if not row:
                continue
            condition_type = int(row.get("condition_type") or 0)
            target_type = int(row.get("target_type") or 0)
            turn = int(row.get("turn") or 0)
            if not turn:
                continue
            if condition_type == ROUTE_RACE_CONDITION_TYPE and target_type != ROUTE_FINALS_TARGET_TYPE:
                condition_id = int(row.get("condition_id") or 0)
                candidates = race_groups.get(condition_id) or [condition_id]
                candidates = tuple(int(program_id or 0) for program_id in candidates if int(program_id or 0))
                if candidates:
                    race_turns[turn] = candidates
                    # condition_value_1 = the required finish rank ("top N") for
                    # this objective; 0 = no rank demanded (e.g. the Junior Make
                    # Debut row -- losing it is not a failure, see
                    # required_rank_for_turn / career_bot/engine/racing.py _race).
                    race_ranks[turn] = int(row.get("condition_value_1") or 0)
            elif condition_type == ROUTE_RACE_CONDITION_TYPE and target_type == ROUTE_FINALS_TARGET_TYPE:
                finals_turns.add(turn)
            # condition_type 3 (fan objectives) and 2/7/8/9 (MANT point
            # objectives) are ignored.
        return {
            "race_turns": race_turns,
            "race_ranks": race_ranks,
            "finals_turns": finals_turns,
        }

    def _ensure_schedule(self, chara):
        route_ids = tuple(int(x) for x in (chara.get("route_race_id_array") or []) if x is not None)
        if route_ids != self._route_ids_cache:
            self._route_ids_cache = route_ids
            self._schedule = self._build_schedule(route_ids)
        return self._schedule

    def race_program_candidates_for_turn(self, chara, turn):
        schedule = self._ensure_schedule(chara)
        return tuple(schedule.get("race_turns", {}).get(int(turn or 0)) or ())

    def race_program_for_turn(self, chara, turn):
        """Compatibility shim returning the first candidate program, or 0."""
        candidates = self.race_program_candidates_for_turn(chara, turn)
        return candidates[0] if candidates else 0

    def required_rank_for_turn(self, chara, turn):
        """The finish rank a mandatory race at `turn` demands, or None if none
        is demanded (the trainee can lose without it counting as a failure --
        e.g. the Junior Make Debut, condition_value_1 = 0).

        Finals (target_type 3, turns 74/76/78) always demand rank 1 -- their
        condition_id is a server-forced sentinel, not real objective data, so
        this is hardcoded rather than trusting the row's value. A turn with no
        matching route-objective row at all (data gap) also defaults to 1,
        preserving the runner's old "force clocks on any mandatory race"
        behavior for anything not covered by this schedule."""
        schedule = self._ensure_schedule(chara)
        turn = int(turn or 0)
        if turn in (schedule.get("finals_turns") or set()):
            return 1
        if turn in (schedule.get("race_turns") or {}):
            value = int((schedule.get("race_ranks") or {}).get(turn) or 0)
            return value if value > 0 else None
        return 1


class RouteObjectivesMixin:
    """Shared route-schedule access for objective-carrying scenarios.

    Contract: the strategy sets `self.objectives = RouteObjectives(base_dir)`
    in __init__.
    """

    # Declared, never assigned here -- the concrete strategy owns the instance
    # (a bare annotation creates no class attribute, so this is type-only).
    objectives: RouteObjectives

    def _ensure_route_schedule(self, chara):
        """Legacy test-compat shim; new code should call self.objectives directly."""
        return self.objectives._ensure_schedule(chara)
