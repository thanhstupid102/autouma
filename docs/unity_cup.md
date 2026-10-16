# Unity Cup scenario notes

Source log: `uma_runtime/captures/unity_cup_20260707_105932.jsonl`.

## Key differences from MANT

- Endpoint prefix: `single_mode_team/*`, not `single_mode_free/*`.
- Scenario id: `2`.
- Start cost in captured run: `use_tp: 60`.
- Team race exists every 12 turns: `24, 36, 48, 60, 72`.
- Team race can use clock/continue: `single_mode_team/team_race_continue`.
- Final spark flow same shape, new prefix: `factor_select` -> `factor_lottery` -> `finish`.

## Start flow

Observed sequence:

```text
pre_single_mode/index
pre_single_mode/friend_support_card_reload  # repeated while paging friend list
single_mode_team/start
support_card_deck/change_party              # may fire after start when deck saved
```

`single_mode_team/start` payload shape:

```json
{
  "start_chara": {
    "card_id": 100101,
    "support_card_ids": [30028, 20012, 30036, 20015, 30054],
    "friend_support_card_info": {"viewer_id": "<redacted>", "support_card_id": 30107},
    "succession_trained_chara_id_1": 3073,
    "succession_trained_chara_id_2": 0,
    "rental_succession_trained_chara": {
      "viewer_id": "<redacted>",
      "trained_chara_id": 4158,
      "is_circle_member": false,
      "is_event_rental": false
    },
    "scenario_id": 2,
    "selected_difficulty_info": {"difficulty_id": 0, "difficulty": 0, "is_boost": 0},
    "select_deck_id": 9,
    "boost_story_event_id": 1016,
    "boost_factor_research_event_id": 0,
    "is_play_training_challenge": false,
    "training_challenge_mode": 0
  },
  "tp_info": {"current_tp": 100, "max_tp": 100, "max_recovery_time": 1782823638},
  "current_money": 12054100,
  "use_tp": 60,
  "current_succession_rank_point": 249
}
```

Implementation note: reuse existing start payload builder, but choose endpoint by `scenario_id == 2` and allow 5 own supports + 1 friend support.

## Normal turn actions

### Event choice

Endpoint:

```text
single_mode_team/check_event
```

Payload:

```json
{"event_id": 201103, "chara_id": 0, "choice_number": 2, "current_turn": 3}
```

Same meaning as MANT/free: select event option, then server advances or unlocks next action.

### Training / rest / medic / outing

Endpoint:

```text
single_mode_team/exec_command
```

Payload:

```json
{
  "command_type": 1,
  "command_id": 106,
  "command_group_id": 0,
  "select_id": 0,
  "current_turn": 1,
  "current_vital": 100
}
```

Observed command ids:

| Action | command_type | command_id | command_group_id | select_id |
|---|---:|---:|---:|---:|
| Normal training | `1` | `101..106`, `601`, `605` | `0` | `0` |
| Rest | `7` | `701` | `0` | `0` |
| Medic | `8` | `801` | `0` | `0` |
| Group outing | `3` | `0` | `390` | `9006` |
| Recreation/date | `3` | `0` | `304` | `0` |

`current_vital` must be current server value before command.

#### Training evaluation data sources

Unity Cup keeps support-card placement separate from team soul markers:

- `home_info.command_info_array[*].training_partner_array` drives bond and rainbow scoring. Only deck support slots `1..6` can add bond/rainbow value; NPC or team-member ids outside those slots never do.
- `team_data_set.command_info_array[*].guide_event_partner_array` counts active **white** souls for that facility.
- `team_data_set.command_info_array[*].soul_event_partner_array` counts active **blue** souls for that facility.
- `team_data_set.command_info_array[*].sp_soul_event_partner_array` counts active **purple** souls for that facility.
- `team_data_set.evaluation_info_array[*].soul_event_state` is only optional log/debug metadata about whether the target currently has soul fire. It is not a scoring gate, threshold check, color classifier, or failure-zeroing condition. The active color is already known from the three facility arrays above.

Team targets outside deck slots `1..6` can still add white, blue, or purple soul value when the team arrays identify them, but they cannot add bond or rainbow value. A deck support may contribute both bond/rainbow and a soul on the same facility when the server supplies both markers. Any training with at least one `sp_soul_event_partner_array` purple soul is failure-free for scoring and debug output, regardless of the raw `failure_rate` on the home command.

## Career race flow

Endpoint sequence:

```text
single_mode_team/race_entry  {"program_id": 624, "current_turn": 23}
single_mode_team/race_start  {"is_short": 1, "current_turn": 23}
single_mode_team/race_end    {"current_turn": 23}
single_mode_team/race_out    {"current_turn": 23}
```

`program_id` comes from `data/json/race_map.json` / master race program table.

Observed captured career races:

| Turn | program_id | Race |
|---:|---:|---|
| 12 | 1069 | Junior Make Debut |
| 23 | 624 | Asahi Hai Futurity Stakes |
| 24 | 625 | Hopeful Stakes |
| 27 | 181 | Kisaragi Sho |
| 31 | 163 | Satsuki Sho |
| 33 | 164 | NHK Mile Cup |
| 34 | 166 | Tokyo Yushun (Japanese Derby) |
| 36 | 74 | Takarazuka Kinen |
| 37 | 1023 | Japan Dirt Derby |
| 44 | 168 | Kikuka Sho |
| 45 | 77 | Queen Elizabeth II Cup |
| 46 | 78 | Mile Championship |
| 54 | 3 | Osaka Hai |
| 56 | 4 | Tenno Sho (Spring) |
| 57 | 5 | Victoria Mile |
| 59 | 73 | Yasuda Kinen |
| 60 | 1022 | Teio Sho |
| 68 | 76 | Tenno Sho (Autumn) |
| 69 | 1026 | JBC Classic |
| 70 | 79 | Japan Cup |
| 71 | 80 | Champions Cup |
| 72 | 81 | Arima Kinen |
| 74 | 2022 | Final round 1 |
| 76 | 2123 | Final round 2 |
| 78 | 2224 | Final round 3 |

Race planning rule:

- Mandatory races = character required races from Gametora.
- User races = optional races chosen in frontend `race`/`rrace` schedule.
- If mandatory character race and user race share turn, mandatory character race wins.
- If no mandatory race exists on turn, bot may run user-selected race, otherwise use normal action scorer.
- Finals at turns `74, 76, 78` are scenario-required and should be treated as mandatory.

## Team race flow

Team race block appears every 12 turns: `24, 36, 48, 60, 72`.

Sequence:

```text
single_mode_team/team_edit
single_mode_team/opponent_list
single_mode_team/team_race_analyze
single_mode_team/team_race_start
single_mode_team/team_race_end
single_mode_team/team_race_out
```

`team_edit` payload shape:

```json
{
  "team_data_array": [
    {"distance_type": 1, "member_id": 1, "chara_id": 1028, "running_style": 2},
    {"distance_type": 2, "member_id": 1, "chara_id": 1004, "running_style": 1},
    {"distance_type": 3, "member_id": 1, "chara_id": 1001, "running_style": 3}
  ],
  "current_turn": 48
}
```

Observed team sizes:

| Turn | members |
|---:|---:|
| 24 | 10 |
| 36 | 13 |
| 48 | 15 |
| 60 | 15 |
| 72 | 15 |

`team_race_analyze` / `team_race_start` ids:

| Turn | race_set_id / team_race_set_id |
|---:|---:|
| 24 | 301 |
| 36 | 403 |
| 48 | 601 |
| 60 | 807 |
| 72 | 1000 |

Clock / continue path:

```text
single_mode_team/team_race_continue {"continue_type": 1, "current_turn": 60}
single_mode_team/team_race_analyze  {"race_set_id": 807, "current_turn": 60}
single_mode_team/team_race_start    {"team_race_set_id": 807, "current_turn": 60}
single_mode_team/team_race_end      {"current_turn": 60}
single_mode_team/team_race_out      {"current_turn": 60}
```

Implementation note: call continue only when server/UI says team race retry/clock is available. `continue_type: 1` observed.

## Skills

Endpoint:

```text
single_mode_team/gain_skills
```

Payload:

```json
{
  "gain_skill_info_array": [{"skill_id": 200702, "level": 1}],
  "current_turn": 23
}
```

Observed skill buys at turns `23, 34, 44, 56, 78`.

## Spark reroll / finish

Same payload shape as Spark Reroll, new prefix:

```text
single_mode_team/factor_select
single_mode_team/factor_lottery
single_mode_team/finish
```

Payloads:

```json
{"current_turn": 78, "skill_id_array": null}
```

```json
{"lottery_count": 1, "tp_info": {"current_tp": 43, "max_tp": 100, "max_recovery_time": 1783432899}, "use_tp": 30}
```

```json
{"is_force_delete": false, "current_turn": 78, "factor_lottery_id": 1}
```

## Minimal implementation plan

1. Add `UnityCupStrategy(ScenarioStrategy)` with `scenario_id = 2`.
2. Route client calls to `single_mode_team/*` when scenario id is `2`.
3. Reuse existing event, command, race, skill, spark finish payload builders; change prefix only.
4. Add team race handler for turns `24/36/48/60/72`.
5. Race planner merge order: `Gametora mandatory chara race > user FE race schedule > strategy-selected optional race > train/rest/medic`.

Skipped: response schema, because capture was request-only. Add when bot needs team member scoring from server response.