import json
from pathlib import Path
from typing import Any, Iterable

from core.runtime_paths import resolve_master_json_path


def _race_command_enabled(commands):
    return any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)


class RacePlanner:
    def __init__(self, base_dir, state_root=None):
        self.base_dir = Path(base_dir)
        self.state_root = Path(state_root).resolve() if state_root is not None else None
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        self._load()

    def _load(self):
        path = resolve_master_json_path(
            self.base_dir,
            "race_map.json",
            self.state_root,
        )
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.meta = {int(k): v for k, v in (data.get("meta") or {}).items()}
        self.program = {int(k): v for k, v in (data.get("program") or {}).items()}
        self.instance = {int(k): [int(item) for item in v] for k, v in (data.get("instance") or {}).items()}

    def get_rival_race_map(self, state):
        rivals = (
            state.get("data", {})
            .get("free_data_set", {})
            .get("rival_race_info_array", [])
        )
        return {
            int(r["program_id"]): int(r["chara_id"])
            for r in rivals
            if "program_id" in r and "chara_id" in r
        }

    def wanted_programs(self, preset, turn=None):
        result = []
        seen = set()
        current_turn = int(turn or 0)
        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            
            pids = []
            if race_id in self.meta:
                info = self.meta[race_id]
                occurrence_turn = int(info.get("turn") or 0)
                if current_turn and occurrence_turn and occurrence_turn != current_turn:
                    continue
                pid = info.get("program_id")
                if pid:
                    pids.append(pid)
            elif race_id in self.program:
                pids.append(race_id)
            else:
                for program_id in self.instance.get(race_id, []):
                    pids.append(program_id)
            
            for pid in pids:
                if pid not in seen:
                    seen.add(pid)
                    result.append(pid)
        return result

    def available_programs(self, state):
        data = state.get("data") or {}
        rca = data.get("race_condition_array") or []
        available = set()
        for item in rca:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.add(pid)
        return available

    def forced_program(self, state, preferred=None):
        """Program id the server forces this turn (only command_type 4/401 is
        enabled, e.g. an objective race or a finals turn), or 0 if racing isn't
        forced. When multiple programs are listed in race_condition_array (or a
        preferred candidate happens not to be listed), `preferred` -- one id or
        an ordered iterable of ids -- steers the pick to the first candidate
        present and not rejected this turn. Otherwise the first non-rejected
        listed program remains the fallback (unchanged default behavior for
        callers such as MantStrategy)."""
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = _race_command_enabled(commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return 0
        pids = []
        for item in data.get("race_condition_array") or []:
            pid = int(item.get("program_id") or 0)
            if pid:
                pids.append(pid)
        preferred_values: Iterable[Any]
        if preferred is None:
            preferred_values = ()
        elif isinstance(preferred, int):
            preferred_values = (preferred,)
        else:
            preferred_values = preferred
        preferred_pids = [int(value or 0) for value in preferred_values if int(value or 0)]
        for preferred_pid in preferred_pids:
            if preferred_pid in pids and (turn, preferred_pid) not in self.rejected:
                return preferred_pid
        for pid in pids:
            if (turn, pid) not in self.rejected:
                return pid
        race = data.get("race_start_info") or {}
        program_id = int(race.get("program_id") or 0)
        if program_id and (turn, program_id) not in self.rejected:
            return program_id
        return 0

    def forced_race_exhausted(self, state):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        race_enabled = _race_command_enabled(commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return False

        program_ids = [
            int(condition.get("program_id") or 0)
            for condition in data.get("race_condition_array") or []
            if int(condition.get("program_id") or 0)
        ]
        if not program_ids:
            fallback_id = int((data.get("race_start_info") or {}).get("program_id") or 0)
            if fallback_id:
                program_ids.append(fallback_id)
        return bool(program_ids) and all((turn, program_id) in self.rejected for program_id in program_ids)

    def choose(self, state, preset):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = _race_command_enabled(commands)
        if not race_enabled:
            return 0

        available = self.available_programs(state)
        if not available:
            return 0

        wanted = self.wanted_programs(preset, turn)
        valid_wanted = [pid for pid in wanted if pid in available and (turn, pid) not in self.rejected]

        if not valid_wanted:
            return 0

        sid = int((data.get("chara_info") or {}).get("scenario_id") or 0)
        from career_bot.scenarios import get_strategy_class  # lazy: races <-> scenarios
        prefers_rivals = bool(getattr(get_strategy_class(sid), "prefers_rival_races", False))
        if not prefers_rivals:
            return valid_wanted[0]

        main_race_id = valid_wanted[0]
        rival_map = self.get_rival_race_map(state)

        if main_race_id in rival_map:
            return main_race_id

        for overwrite_pid in valid_wanted[1:]:
            if overwrite_pid in rival_map:
                return overwrite_pid

        return main_race_id

    def reject(self, turn, program_id):
        self.rejected.add((int(turn or 0), int(program_id or 0)))

    def label(self, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        name = info.get("name") or ""
        race_instance_id = info.get("race_instance_id") or ""
        return f"{program_id} {race_instance_id} {name}".strip()
