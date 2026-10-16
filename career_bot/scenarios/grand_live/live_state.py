"""Grand Live (scenario 3) live_data_set state model.

`live_data_set` is the scenario's central state object; start/load and most
turn/race responses carry it (docs/scenarios/grand-live-endpoints.md, DTO
`SingleModeLiveDataSet`). It holds the five performance tokens the trainee
earns from training, the tree squares currently offered, the live schedule
state, and the per-command token preview.

Merge semantics are deliberate. The metadata dump could not tell us whether
every response ships a complete `live_data_set` or only the parts it touched
(that is an explicit open question in the endpoint doc), and the 2026-07-26
capture is request-only so it cannot settle it either. `LiveState.update`
therefore treats an absent key as "unchanged" and only overwrites what the
payload actually carries, which is correct under both readings.
"""

from __future__ import annotations

# Gallop.SingleModeScenarioLiveDefine.Performance
DANCE = 1
PASSION = 2
VOCAL = 3
VISUAL = 4
MENTAL = 5

PERFORMANCE_NAMES = {
    DANCE: "Dance",
    PASSION: "Passion",
    VOCAL: "Vocal",
    VISUAL: "Visual",
    MENTAL: "Mental",
}

# live_performance_info field prefix per performance type; the DTO carries a
# `max_<name>` companion for each.
PERFORMANCE_FIELDS = {
    DANCE: "dance",
    PASSION: "passion",
    VOCAL: "vocal",
    VISUAL: "visual",
    MENTAL: "mental",
}

# MasterSingleModeLiveSquare.SquareType
SQUARE_PARAMETER = 1
SQUARE_SKILL = 2
SQUARE_HP = 3
SQUARE_SONG = 4

SQUARE_TYPE_NAMES = {
    SQUARE_PARAMETER: "Parameter",
    SQUARE_SKILL: "Skill",
    SQUARE_HP: "Hp",
    SQUARE_SONG: "Song",
}

# SingleModeScenarioLiveDefine.LiveResult
LIVE_RESULT_NONE = 0
LIVE_RESULT_SUCCESS = 1
LIVE_RESULT_GREAT_SUCCESS = 2

# Tree squares unlock once the scenario's guild opens
# (SingleModeScenarioLiveDefine.TUTORIAL_GUILD_OPEN_TURN). The 2026-07-26
# capture's first master_square landed on turn 7, consistent with this.
GUILD_OPEN_TURN = 5


def live_data_set_of(response):
    """The live_data_set carried by a Grand Live API response, or {}."""
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if not isinstance(data, dict):
        data = response
    live_data_set = data.get("live_data_set")
    return live_data_set if isinstance(live_data_set, dict) else {}


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class LiveState:
    """Accumulated view of live_data_set across a career."""

    def __init__(self, live_data_set=None):
        self.raw = {}
        self.update(live_data_set)

    # --- ingest ---

    def update(self, live_data_set):
        """Merge live_data_set; absent keys stay unchanged and explicit null clears."""
        if not isinstance(live_data_set, dict):
            return self
        for key, value in live_data_set.items():
            self.raw[key] = value
        return self

    def update_from(self, response):
        self.update(live_data_set_of(response))
        if isinstance(response, dict):
            data = response.get("data")
            if not isinstance(data, dict):
                data = response
            if "not_up_parameter_info" in data:
                self.raw["not_up_parameter_info"] = data.get("not_up_parameter_info")
        return self

    # --- performance tokens (Da/Pa/Vo/Vi/Me) ---

    @property
    def tokens(self):
        info = self.raw.get("live_performance_info") or {}
        return {ptype: _int(info.get(field)) for ptype, field in PERFORMANCE_FIELDS.items()}

    @property
    def max_tokens(self):
        info = self.raw.get("live_performance_info") or {}
        return {ptype: _int(info.get(f"max_{field}")) for ptype, field in PERFORMANCE_FIELDS.items()}

    @property
    def capped_types(self):
        """Performance types the server says will not go up (LiveNotUpParameterInfo)."""
        info = self.raw.get("not_up_parameter_info") or {}
        return {_int(item) for item in (info.get("performance_type_array") or [])}

    def can_afford(self, cost):
        """True when every {perf_type: value} entry in `cost` is covered."""
        tokens = self.tokens
        return all(tokens.get(_int(ptype), 0) >= _int(value) for ptype, value in (cost or {}).items())

    def shortfall(self, cost):
        """{perf_type: missing} for the entries `cost` cannot cover."""
        tokens = self.tokens
        missing = {}
        for ptype, value in (cost or {}).items():
            gap = _int(value) - tokens.get(_int(ptype), 0)
            if gap > 0:
                missing[_int(ptype)] = gap
        return missing

    # --- tree squares ---

    @property
    def next_squares(self):
        """[{square_id, square_num}] currently offered by the tree."""
        rows = self.raw.get("next_square_info_array") or []
        return [row for row in rows if isinstance(row, dict) and _int(row.get("square_id"))]

    @property
    def next_square_ids(self):
        return [_int(row.get("square_id")) for row in self.next_squares]

    @property
    def reserve_square_id(self):
        return _int(self.raw.get("reserve_square_id"))

    # --- lives / songs ---

    @property
    def live_id(self):
        return _int((self.raw.get("live_info") or {}).get("live_id"))

    @property
    def master_live_ids(self):
        return [_int(item) for item in (self.raw.get("master_live_id_array") or [])]

    @property
    def next_live_ids(self):
        return [_int(item) for item in (self.raw.get("next_live_id_array") or [])]

    @property
    def effected_live_ids(self):
        ids = []
        for key in ("effected_live_id_array", "effected_master_live_id_array"):
            for item in self.raw.get(key) or []:
                ids.append(_int(item.get("live_id") if isinstance(item, dict) else item))
        return ids

    @property
    def live_results(self):
        """[{live_type, result_state}] -- result_state 2 is GreatSuccess."""
        rows = self.raw.get("live_result_array") or []
        return [row for row in rows if isinstance(row, dict)]

    @property
    def great_success_count(self):
        return sum(1 for row in self.live_results if _int(row.get("result_state")) == LIVE_RESULT_GREAT_SUCCESS)

    @property
    def training_bonus(self):
        """{target_type: effect_value} from training_bonus_array."""
        bonus = {}
        for row in self.raw.get("training_bonus_array") or []:
            if isinstance(row, dict):
                bonus[_int(row.get("target_type"))] = _int(row.get("effect_value"))
        return bonus

    # --- per-command token preview ---

    def command_token_gain(self, command_type, command_id):
        """{perf_type: value} a given training/command is previewed to award.

        This is how the trainee earns tokens: command_info_array mirrors the
        turn's commands and each entry carries performance_inc_dec_info_array.
        """
        for row in self.raw.get("command_info_array") or []:
            if not isinstance(row, dict):
                continue
            if _int(row.get("command_type")) != _int(command_type):
                continue
            if _int(row.get("command_id")) != _int(command_id):
                continue
            gain: dict[int, int] = {}
            for item in row.get("performance_inc_dec_info_array") or []:
                if isinstance(item, dict):
                    ptype = _int(item.get("performance_type"))
                    if ptype:
                        gain[ptype] = gain.get(ptype, 0) + _int(item.get("value"))
            return gain
        return {}

    def total_token_gain(self, command_type, command_id):
        return sum(self.command_token_gain(command_type, command_id).values())

    def describe_tokens(self):
        tokens = self.tokens
        return " ".join(f"{PERFORMANCE_NAMES[p]}={tokens[p]}" for p in sorted(tokens))

    def describe_tokens_short(self):
        """Compact inventory line: `Da=41 Pa=2 Vo=33 Vi=30 Me=19`."""
        tokens = self.tokens
        maxes = self.max_tokens
        parts = []
        for ptype in sorted(tokens):
            label = PERFORMANCE_NAMES[ptype][:2]
            cap = maxes.get(ptype) or 0
            parts.append(f"{label}={tokens[ptype]}" + (f"/{cap}" if cap else ""))
        return " ".join(parts)

    def token_delta(self, before):
        """`-14 Da -16 Vi` for the tokens spent since the `before` snapshot."""
        after = self.tokens
        spent = []
        for ptype in sorted(after):
            diff = int((before or {}).get(ptype, 0)) - after[ptype]
            if diff > 0:
                spent.append(f"-{diff} {PERFORMANCE_NAMES[ptype][:2]}")
        return " ".join(spent)
