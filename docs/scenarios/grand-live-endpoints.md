# Grand Live career scenario API surface

Discovered: 2026-07-22 (Asia/Bangkok)

## Scope and source

This is a read-only metadata investigation. No bot code was changed and no
VMProtect VM/RVA reconstruction was attempted.

- Scenario name used by the game: Grand Live; the code-facing scenario name is
  `Live`.
- Scenario id: `Gallop.SingleModeDefine.ScenarioId.Live = 3`.
- Primary structure dump: `uma_runtime/re_rankpoint/il2cpp_bridge/dump.cs`,
  dated 2026-07-15.
- Installed metadata checked: `UmamusumePrettyDerby_Data/il2cpp_data/Metadata/global-metadata.dat`,
  dated 2026-07-22; Il2CppDumper identified metadata version 31.

The 2026-07-22 metadata was newer than `dump.cs`, so I tried a fresh
Il2CppDumper v6.7.46 run using the installed `GameAssembly.dll` and metadata.
It printed metadata/Il2Cpp version 31, then failed in the custom PE loader with
Win32 error 126. There is therefore no usable 1.33.0 re-dump and no valid
07-15-versus-1.33.0 structural diff to report. The existing 2026-07-15 dump is
the structural dump analyzed below; the endpoint literal scan was also run
against the current installed metadata string table.

Useful verification anchors:

```text
dump.cs:L203392-L203416       SingleModeLiveAPI methods
dump.cs:L215460-L215518       scenario, playing-state, and command enums
dump.cs:L342610-L343578       SingleModeLive HTTP request/response DTOs
dump.cs:L353025-L353095       live state DTOs
global-metadata.dat:L3408     NUL-delimited string-table route scan anchor
```

The route inventory command was:

```powershell
rg -a -o 'single_mode_live/[a-z_]+' global-metadata.dat |
  Sort-Object -Unique
```

It returned exactly the 23 paths listed below. No additional endpoint-shaped
literal with `grand_live/`, `live_`, or `single_mode_live_` was found.

## Endpoint surface

The class/method mapping comes from `Gallop.SingleModeLiveAPI` at
`dump.cs:L203392-L203416`, with `live_start` additionally surfaced by
`SingleModeScenarioLiveTopController.RequestLiveStart` at
`dump.cs:L205183-L205195` and `dump.cs:L205624-L205625`. The phase labels are
static-dump inferences from method and DTO names; exact sequencing still needs
a live capture.

| Full path | Class/method | Inferred phase | Already wired? |
|---|---|---|---|
| `single_mode_live/start` | `SingleModeLiveAPI.SendStart` | boot/create | No |
| `single_mode_live/load` | `SingleModeLiveAPI.SendLoadAsync` | boot/resume | No |
| `single_mode_live/exec_command` | `SingleModeLiveAPI.SendExecCommandAsync` | per-turn command | No |
| `single_mode_live/check_event` | `SingleModeLiveAPI.SendCheckEvent` | per-turn event | No |
| `single_mode_live/continue` | `SingleModeLiveAPI.SendContinueAsync` | per-turn continuation | No |
| `single_mode_live/gain_skills` | `SingleModeLiveAPI.SendGainSkills` | per-turn post-command | No |
| `single_mode_live/change_short_cut` | `SingleModeLiveAPI.SendChangeShortCut` | per-turn shortcut | No |
| `single_mode_live/minigame_end` | `SingleModeLiveAPI.SendMiniGameEnd` | per-turn minigame | No |
| `single_mode_live/get_choice_reward` | `SingleModeLiveAPI.SendGetChoiceRewardRequest` | event reward | No |
| `single_mode_live/master_square` | `SingleModeLiveAPI.SendSingleModeLiveMasterSquareRequest` | live tree-square choice | No |
| `single_mode_live/reserve_square` | `SingleModeLiveAPI.SendSingleModeLiveReserveSquareRequest` | live tree-square reservation | No |
| `single_mode_live/lottery_square` | `SingleModeLiveAPI.SendSingleModeLiveLotterySquareRequest` | live tree-square lottery | No |
| `single_mode_live/live_start` | `SingleModeScenarioLiveTopController.RequestLiveStart` | live performance start | No |
| `single_mode_live/multi_race_reserve` | `SingleModeRaceReserveConnect.LiveRequester.IRequester.Execute` | race deck reservation | No |
| `single_mode_live/race_entry` | `SingleModeLiveAPI.SendRaceEntryAsync` | race entry | No |
| `single_mode_live/race_start` | `SingleModeLiveAPI.SendRaceStart` | race/live start | No |
| `single_mode_live/race_analyze` | `SingleModeLiveAPI.SendAnalyzeRequest` | race analysis | No |
| `single_mode_live/change_running_style` | `SingleModeLiveAPI.SendChangeRunningStyleRequest` | race setup | No |
| `single_mode_live/race_end` | `SingleModeLiveAPI.SendRaceEndAsync` | race result | No |
| `single_mode_live/race_out` | `SingleModeLiveAPI.SendRaceOut` | race exit/continue | No |
| `single_mode_live/finish` | `SingleModeLiveAPI.SendFinish` | career end | No |
| `single_mode_live/factor_select` | `SingleModeLiveAPI.SendFactorSelect` | post-career factor selection | No |
| `single_mode_live/factor_lottery` | `SingleModeLiveAPI.SendFactorLottery` | post-career factor lottery | No |

### Likely command flow

The static ordering suggests `start` or `load`, then a repeating turn loop
centered on `exec_command`, with `check_event`, `continue`, `gain_skills`,
`change_short_cut`, `minigame_end`, and choice/tree-square routes as needed.
Race turns branch through `race_entry`, `race_start`, optional `race_analyze`
and `change_running_style`, then `race_end` or `race_out`. The dedicated live
performance screen calls `live_start`; `finish` closes the career, after which
`factor_select` and `factor_lottery` are available. This is an inference from
the API method names and the response state application methods around
`dump.cs:L45450-L45600`, not a captured protocol trace.

## Scenario id and routing enums

| Metadata symbol | Value | Meaning |
|---|---:|---|
| `ScenarioId.TeamRace` | 2 | Unity Cup/team namespace |
| `ScenarioId.Live` | **3** | Grand Live namespace |
| `ScenarioId.Free` | 4 | MANT/free namespace |
| `ScenarioId.Venus` | 5 | Venus scenario |
| `PlayingState.LiveTop` | 10 | live top/performance UI state |
| `CommandType.Live` | 10 | live command routing enum entry |
| `SingleModeLiveLiveData.GRAND_LIVE_TYPE` | 10 | master-data live type, not scenario namespace id |

The authoritative enum block is `dump.cs:L215460-L215518`. The separate
`GRAND_LIVE_TYPE = 10` constant and `get_IsGrandLive()` are at
`dump.cs:L29230-L29242`; do not confuse that live-data type with
`ScenarioId.Live = 3`. Existing client routing only maps ids 2 and 4 and
defaults unknown ids to `single_mode_free`, so id 3 is currently unrouted.

## Already-wired gap

The endpoint table marks every Grand Live route **No**.

> Path note (updated after the §12/§13 refactor; the RE facts above are
> unchanged): the routing map is no longer a literal in `uma_api/client.py`.
> Since §5.1 each scenario strategy declares its own `endpoint_prefix`, and
> `career_bot/scenarios/__init__.py::endpoint_prefix_by_id()` builds the
> `scenario_id -> prefix` map from the registry. `uma_api/routes.py`
> (`ApiRoutes._single_mode_prefix` / `_single_mode_ep`) resolves the prefix at
> call time and falls back to `single_mode_free` for an unknown id. Adding
> Grand Live therefore means registering a strategy with
> `endpoint_prefix = "single_mode_live"` under id 3, not editing the client.

The registry currently contains only team id 2 and free id 4, and the fallback
is free. Two engine recovery paths additionally hardcode the free prefix as a
last resort when the client facade lacks the method — `single_mode_free/load`
and `single_mode_free/minigame_end` in `career_bot/engine/recovery.py`
(`RunnerRecoveryMixin`) — so those would also need de-hardcoding.
A repository search found no `single_mode_live/` calls in `uma_api/` or
`career_bot/`; all 23 routes are new wiring for the future scenario layer.

## Request and response DTO reference

The following are the scenario-specific fields declared by each HTTP DTO.
Inherited `RequestBase`/`ResponseCommon` fields are omitted. Each response
wrapper has its typed `data` field at offset `0x18`; the nested `CommonResponse`
fields below are the payload fields.

The HTTP DTO family is named `SingleModeLive*`; the structural scan found no
`GrandLive*` request/response DTO and no `*LiveDeck` DTO. The `GrandLive`
classes are controller/view phase types, such as
`SingleModeScenarioLiveTopController.PhaseGrandLive`, rather than wire DTOs
(`dump.cs:L205344-L205454`).

| Route | Request class: fields | Response class: `data` fields | Dump anchor |
|---|---|---|---|
| `change_running_style` | `SingleModeLiveChangeRunningStyleRequest`: `program_id:int`, `running_style:int`, `current_turn:int` | `SingleModeLiveChangeRunningStyleResponse.CommonResponse`: none | `dump.cs:L342611-L342631` |
| `change_short_cut` | `SingleModeLiveChangeShortCutRequest`: `short_cut_state:int`, `current_turn:int` | `SingleModeLiveChangeShortCutResponse.CommonResponse`: `chara_info:SingleModeChara`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L342651-L342681` |
| `check_event` | `SingleModeLiveCheckEventRequest`: `event_id:int`, `chara_id:int`, `choice_number:int`, `current_turn:int` | `SingleModeLiveCheckEventResponse.CommonResponse`: `chara_info:SingleModeChara`, `not_up_parameter_info:NotUpParameterInfo`, `not_down_parameter_info:NotDownParameterInfo`, `home_info:SingleModeHomeInfo`, `unchecked_event_array:SingleModeEventInfo[]`, `event_effected_factor_array:SuccessionEffectedFactor[]`, `race_condition_array:SingleModeRaceCondition[]`, `race_start_info:SingleRaceStartInfo`, `race_running_style:int`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L342693-L342728` |
| `continue` | `SingleModeLiveContinueRequest`: `continue_type:int`, `current_turn:int` | `SingleModeLiveContinueResponse.CommonResponse`: `chara_info:SingleModeChara`, `home_info:SingleModeHomeInfo`, `race_start_info:SingleRaceStartInfo`, `unchecked_event_array:SingleModeEventInfo[]`, `user_item:UserItem`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L342744-L342773` |
| `exec_command` | `SingleModeLiveExecCommandRequest`: `command_type:int`, `command_id:int`, `command_group_id:int`, `select_id:int`, `current_turn:int`, `current_vital:int` | `SingleModeLiveExecCommandResponse.CommonResponse`: `chara_info:SingleModeChara`, `race_condition_array:SingleModeRaceCondition[]`, `not_up_parameter_info:NotUpParameterInfo`, `not_down_parameter_info:NotDownParameterInfo`, `home_info:SingleModeHomeInfo`, `command_result:SingleModeCommandResult`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L342789-L342824` |
| `factor_lottery` | `SingleModeLiveFactorLotteryRequest`: `lottery_count:int`, `tp_info:TpInfo`, `use_tp:int` | `SingleModeLiveFactorLotteryResponse.CommonResponse`: `single_mode_factor_lottery_common:SingleModeFactorLotteryCommon` | `dump.cs:L342840-L342865` |
| `factor_select` | `SingleModeLiveFactorSelectRequest`: `current_turn:int`, `skill_id_array:int[]` | `SingleModeLiveFactorSelectResponse.CommonResponse`: `single_mode_factor_select_common:SingleModeFactorSelectCommon` | `dump.cs:L342881-L342905` |
| `finish` | `SingleModeLiveFinishRequest`: `is_force_delete:bool`, `factor_lottery_id:int`, `current_turn:int` | `SingleModeLiveFinishResponse.CommonResponse`: `single_mode_finish_common:SingleModeFinishCommon` | `dump.cs:L342921-L342946` |
| `gain_skills` | `SingleModeLiveGainSkillsRequest`: `gain_skill_info_array:GainSkillInfo[]`, `current_turn:int` | `SingleModeLiveGainSkillsResponse.CommonResponse`: `chara_info:SingleModeChara`, `home_info:SingleModeHomeInfo`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L342962-L342988` |
| `get_choice_reward` | `SingleModeLiveGetChoiceRewardRequest`: `event_id:int` | `SingleModeLiveGetChoiceRewardResponse.CommonResponse`: `choice_reward_array:EventChoiceReward[]` | `dump.cs:L343004-L343027` |
| `live_start` | `SingleModeLiveLiveStartRequest`: `current_turn:int` | `SingleModeLiveLiveStartResponse.CommonResponse`: `chara_info:SingleModeChara`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet`, `add_music:UserMusic` | `dump.cs:L343043-L343069` |
| `load` | `SingleModeLiveLoadRequest`: no declared fields | `SingleModeLiveLoadResponse.CommonResponse`: `single_mode_load_common:SingleModeLoadCommon`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343085-L343109` |
| `lottery_square` | `SingleModeLiveLotterySquareRequest`: `square_id:int`, `current_turn:int` | `SingleModeLiveLotterySquareResponse.CommonResponse`: `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343125-L343149` |
| `master_square` | `SingleModeLiveMasterSquareRequest`: `square_id:int`, `current_turn:int` | `SingleModeLiveMasterSquareResponse.CommonResponse`: `chara_info:SingleModeChara`, `not_up_parameter_info:NotUpParameterInfo`, `home_info:SingleModeHomeInfo`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343165-L343193` |
| `minigame_end` | `SingleModeLiveMinigameEndRequest`: `result:MinigameResult`, `current_turn:int` | `SingleModeLiveMinigameEndResponse.CommonResponse`: `chara_info:SingleModeChara`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343209-L343235` |
| `multi_race_reserve` | `SingleModeLiveMultiRaceReserveRequest`: `deck_num:int`, `deck_name:string`, `add_race_array:SingleModeReservedRace[]`, `cancel_race_array:SingleModeReservedRace[]` | `SingleModeLiveMultiRaceReserveResponse.CommonResponse`: `reserved_race_array:SingleModeReservedRaceDeck[]` | `dump.cs:L343251-L343285` |
| `race_analyze` | `SingleModeLiveRaceAnalyzeRequest`: `program_id:int`, `current_turn:int` | `SingleModeLiveRaceAnalyzeResponse.CommonResponse`: `race_horse_data_array:RaceHorseData[]` | `dump.cs:L343293-L343317` |
| `race_end` | `SingleModeLiveRaceEndRequest`: `current_turn:int` | `SingleModeLiveRaceEndResponse.CommonResponse`: `race_reward_info:CharaRaceReward`, `chara_info:SingleModeChara`, `home_info:SingleModeHomeInfo`, `add_music:UserMusic`, `race_history:SingleRaceHistory[]`, `win_saddle_id_array:int[]`, `race_condition_array:SingleModeRaceCondition[]`, `add_trophy_info:LoginUserTrophyInfo`, `trophy_reward_info:RaceRewardData`, `reward_summary_info:RewardSummaryInfo`, `race_add_reward_info:SingleModeRaceAddRewardInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343333-L343367` |
| `race_entry` | `SingleModeLiveRaceEntryRequest`: `program_id:int`, `current_turn:int` | `SingleModeLiveRaceEntryResponse.CommonResponse`: `chara_info:SingleModeChara`, `home_info:SingleModeHomeInfo`, `race_start_info:SingleRaceStartInfo`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343383-L343411` |
| `race_out` | `SingleModeLiveRaceOutRequest`: `current_turn:int` | `SingleModeLiveRaceOutResponse.CommonResponse`: `chara_info:SingleModeChara`, `home_info:SingleModeHomeInfo`, `unchecked_event_array:SingleModeEventInfo[]`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343427-L343453` |
| `race_start` | `SingleModeLiveRaceStartRequest`: `is_short:int`, `current_turn:int` | `SingleModeLiveRaceStartResponse.CommonResponse`: `race_start_info:SingleRaceStartInfo`, `race_scenario:string` | `dump.cs:L343469-L343494` |
| `reserve_square` | `SingleModeLiveReserveSquareRequest`: `square_id:int`, `current_turn:int` | `SingleModeLiveReserveSquareResponse.CommonResponse`: none | `dump.cs:L343510-L343534` |
| `start` | `SingleModeLiveStartRequest`: `start_chara:SingleModeStartChara`, `tp_info:TpInfo`, `current_money:int`, `use_tp:int`, `current_succession_rank_point:int` | `SingleModeLiveStartResponse.CommonResponse`: `single_mode_start_common:SingleModeStartCommon`, `live_data_set:SingleModeLiveDataSet` | `dump.cs:L343550-L343578` |

## Central live state returned by the API

`SingleModeLiveDataSet` is the common state object carried by start/load and
most turn/race responses (`dump.cs:L353025-L353040`). Its declared fields are:

| Class | Fields | Dump anchor |
|---|---|---|
| `SingleModeLiveDataSet` | `live_info:SingleModeLiveInfo`; `live_performance_info:SingleModeLivePerformanceInfo`; `command_info_array:SingleModeLiveCommandInfo[]`; `evaluation_info_array:LiveEvaluationInfo[]`; `next_square_info_array:SingleModeLiveNextSquareInfo[]`; `master_live_id_array:int[]`; `next_live_id_array:int[]`; `effected_live_id_array:int[]`; `not_up_parameter_info:LiveNotUpParameterInfo`; `live_result_array:SingleModeLiveLiveResult[]`; `reserve_square_id:int`; `training_bonus_array:SingleModeLiveTrainingBonus[]` | `dump.cs:L353025-L353040` |
| `SingleModeLiveInfo` | `live_id:int` | `dump.cs:L353043-L353047` |
| `SingleModeLivePerformanceInfo` | `dance:int`, `max_dance:int`, `passion:int`, `max_passion:int`, `vocal:int`, `max_vocal:int`, `visual:int`, `max_visual:int`, `mental:int`, `max_mental:int` | `dump.cs:L353074-L353086` |
| `SingleModeLiveCommandInfo` | `command_type:int`, `command_id:int`, `performance_inc_dec_info_array:SingleModeLivePerformanceIncDecInfo[]`, `params_inc_dec_info_array:SingleModeParamsIncDecInfo[]` | `dump.cs:L353015-L353023` |
| `SingleModeLivePerformanceIncDecInfo` | `performance_type:int`, `value:int` | `dump.cs:L353066-L353071` |
| `SingleModeLiveNextSquareInfo` | `square_id:int`, `square_num:int` | `dump.cs:L353058-L353063` |
| `SingleModeLiveLiveResult` | `live_type:int`, `result_state:int` | `dump.cs:L353050-L353055` |
| `SingleModeLiveTrainingBonus` | `target_type:int`, `effect_value:int` | `dump.cs:L353090-L353095` |
| `LiveEvaluationInfo` | `target_id:int`, `chara_id:int`, `member_state:int` | `dump.cs:L351547-L351554` |
| `LiveNotUpParameterInfo` | `performance_type_array:int[]` | `dump.cs:L351556-L351561` |

`SingleModeLiveDataSet` is applied by the scenario state paths for live data,
command responses, race responses, check-event, load, continue, and minigame
responses around `dump.cs:L45450-L45600`. That makes it the primary state to
persist between requests, rather than treating the live screen as a separate
stateless action.

## Grand-Live-specific mechanics surfaced in metadata

These are the real names and values exposed by the static dump; no gameplay
values are inferred here.

### Performance, live results, and phases

- `Gallop.SingleModeScenarioLiveDefine.Performance` has `Dance = 1`,
  `Passion = 2`, `Vocal = 3`, `Visual = 4`, and `Mental = 5`
  (`dump.cs:L204429-L204436`).
- `SingleModeScenarioLiveDefine.LiveResult` has `None = 0`, `Success = 1`,
  and `GreatSuccess = 2`; `MemberState` has `None = 0` and `Joined = 1`
  (`dump.cs:L204441-L204455`).
- `SingleModeScenarioLiveDefine.MasterStringId` names `Join`, `JoinMember`,
  and `LiveBonusTagTraining` (`dump.cs:L204460-L204465`).
- `SingleModeScenarioLiveDefine` declares `TUTORIAL_GUILD_OPEN_TURN = 5` and
  `TRUE_GRANDLIVE_MUSIC_ID = 1029` (`dump.cs:L204470-L204474`).
- The live-top controller has explicit phases `In`, `Live`, `Out`,
  `GrandLiveIn`, `GrandLiveBackTop`, `GrandLiveAnimation`, `GrandLive`,
  `AfterGrandLive`, and `End` (`dump.cs:L205183-L205196`). These are UI/state
  phases, not additional HTTP namespaces.

### Master data and progression objects

- `MasterSingleModeLiveLiveData.SingleModeLiveLiveData` contains `Id`,
  `LiveType`, `TurnNum`, `GreatSuccessNum`, `SongNum`, `NormalMusicId`, and
  `SpecialMusicId`; its `GRAND_LIVE_TYPE` constant is 10 and it exposes
  `get_IsGrandLive()` (`dump.cs:L29230-L29242`). The backing table is
  `single_mode_live_live_data` (`dump.cs:L29256-L29263`).
- `MasterSingleModeLiveMasterBonus.SingleModeLiveMasterBonus` contains
  `Id`, `MasterBonusType`, `MasterBonusTypeValue`, and three gain groups:
  `MasterBonusGainType1` plus `MasterBonusGainValue11` through `14`, the
  corresponding `...Type2` plus `...Value21` through `24`, and `...Type3` plus
  `...Value31` through `34` (`dump.cs:L29329-L29349`). Its enums name bonus
  types `Parameter`, `Skill`, `Hp`, `Song`; gain types `Parameter`, `Skill`,
  `Hp`, `TrainingBonus`; parameter targets `Speed`, `Stamina`, `Power`,
  `Guts`, `Wiz`, `SkillPt`; and skill-hint targets `Random`, `SkillId`,
  `TagId` (`dump.cs:L29274-L29324`).
- `MasterSingleModeLiveSongList.SingleModeLiveSongList` contains `Id`,
  `CommandId`, `LiveId`, `Level`, `MasterBonusContentTextId`, `LiveBonusType`,
  and `LiveBonusValue`; `LiveBonusType` is `BestTraining`, `Event`, or
  `TagTraining` (`dump.cs:L29372-L29401`).
- `MasterSingleModeLiveSquare.SingleModeLiveSquare` contains `Id`,
  `SquareTitleTextId`, `SquareContentTextId`, `MasterBonusId`, `SquareType`,
  and five `PerfTypeN`/`PerfValueN` pairs. `SquareType` is `Parameter`,
  `Skill`, `Hp`, or `Song` (`dump.cs:L29427-L29465`).
- `MasterSingleModeLiveTrainingPlate.SingleModeLiveTrainingPlate` contains
  `Id`, `ValueMin`, and `ValueMax` (`dump.cs:L29486-L29491`).

### In-memory scenario work state

`Gallop.WorkSingleModeScenarioLive` tracks `NextMusicIdArray`,
`TotalMusicIdArray`, `NextLiveBonusEffect`, `CurrentLiveBonusEffect`,
`CurrentLiveBonusMusicIdArray`, `TreeSquareInfoArray`, `ReservedTreeSquareId`,
`TrainingBonusArray`, `EvaluationInfoList`, and `LiveResultList`, plus separate
`PerformanceData` and `PerformanceMax` objects
(`dump.cs:L46008-L46021`). The named operations include `GetLiveResult`,
`GetPerformance`, `GetPerformanceMax`, `CanGetTreeSquare`,
`GetExpectationGauge`, `GetNextExpectationGauge`, and `GetTrainingBonus`
(`dump.cs:L46040-L46050`).

Its nested classes expose the concrete shapes needed by a bot state model:

- `LiveBonusEffect`: `BestTraining`, `Event`, `TagTraining`, with
  `GetBonus(...)` (`dump.cs:L45888-L45902`).
- `PerformanceData`: `Vocal`, `Passion`, `Dance`, `Visual`, `Mental`, with
  `GetPerformance(...)`, `Set(...)`, and `Clear()`
  (`dump.cs:L45906-L45926`).
- `LiveResultData`: `LiveType` and `LiveResult`, constructed from
  `SingleModeLiveLiveResult` (`dump.cs:L45930-L45937`).
- `TreeSquareInfo`: `SquareId`, `SquareNum`, plus derived `LiveId` and
  `IsMusic` (`dump.cs:L45941-L45950`).
- `TrainingBonus`: `ParameterType` and `Value`, constructed from
  `SingleModeLiveTrainingBonus` (`dump.cs:L45953-L45960`).

The metadata therefore explicitly names performance points, songs/music,
live results, live bonuses, master bonuses, training bonuses, tree squares,
lessons/commands, evaluation/member state, and an expectation gauge. I did not
find a Grand-Live DTO field or master/work-state symbol named `Fans`, audience,
tokens, or SP-live-currency in the inspected live-specific blocks; that is an
absence from this static name scan, not proof that no economy exists elsewhere.

## Open questions / needs live capture

The dump gives names, types, and routing families but not the server-side
values or guaranteed order. A Frida/wire capture should confirm:

- whether `start` is always followed by `live_start`, or whether normal turns
  and a later `LiveTop` phase mediate the first performance request;
- the numeric meanings of `command_type`, `command_id`, `command_group_id`,
  `select_id`, `continue_type`, `short_cut_state`, `square_id`, `live_id`,
  `live_type`, `result_state`, `performance_type`, and `target_type`;
- exact request defaults and validation for `current_turn`, `current_vital`,
  `current_money`, `use_tp`, `tp_info`, `current_succession_rank_point`, and
  `is_force_delete`;
- whether `race_start`/`race_end` cover only career races, live performances,
  or both, and when `race_analyze`, `race_out`, and `multi_race_reserve` occur;
- whether `live_data_set` is complete after every response or must be merged
  with prior state, especially for `next_square_info_array`, live bonuses,
  music arrays, evaluation state, and `reserve_square_id`;
- the exact factor-selection/lottery order after `finish`, including the
  meaning of `factor_lottery_id` and `lottery_count`;
- the concrete master-data rows and dynamic rewards associated with
  `GRAND_LIVE_TYPE = 10` and `TRUE_GRANDLIVE_MUSIC_ID = 1029`.

Static verification commands for the negative route/name checks were:

```powershell
rg -a -o '(grand_live|live_[a-z_]+|single_mode_live_[a-z_]+)[^\x00 ]*' global-metadata.dat
rg -n 'single_mode_live/|GrandLive|LiveDeck|Fans|Audience|Token|SP' `
  uma_api/client.py career_bot uma_runtime/re_rankpoint/il2cpp_bridge/dump.cs
```

These checks support the inventory above; they do not replace the requested
live capture once Grand Live opens.
