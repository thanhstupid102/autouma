"""Unity Cup team-race API flow (team_edit -> opponent_list -> analyze ->
start -> end -> out, with clock retries and mid-race resume)."""

from career_bot.scenarios.unity_cup.team_roster import TeamRosterBuilder
from uma_api.errors import api_error_result_code, is_blocked_state_error


def run_team_race(runner, client, state, preset, payload):
    current_turn = int(payload.get("current_turn") or 0)
    strategy = payload.get("_strategy")
    # playing_state from the decision payload steers resume: 7 (or absent)
    # = full flow, 8 = the race already started server-side (a previous run
    # died mid-race) so skip straight to end+out, 9 = ended, just out.
    playing_state = int(payload.get("playing_state") or 0)
    edit_res = None
    start_res = None
    race_set_id = None
    if playing_state in (8, 9):
        runner._log("team_race_resume", current_turn, f"resuming from playing_state {playing_state}")
        race_set_id = _resumed_team_race_set_id(state, playing_state)
        if not race_set_id:
            runner._log(
                "team_race_set_id_missing",
                current_turn,
                f"resume playing_state {playing_state} carried no active team_race_set_id; retries disabled",
            )
        if playing_state == 8:
            client.team_race_end(current_turn)
        out = client.team_race_out(current_turn)
    else:
        builder = getattr(strategy, "team_roster", None) or TeamRosterBuilder(runner.base_dir)
        team = builder.build(state)
        edit_res = client.team_edit(team, current_turn)
        opponent_res = client.opponent_list(current_turn)
        race_set_id = _team_race_set_id(runner, opponent_res, current_turn)
        client.team_race_analyze(race_set_id, current_turn)
        start_res = client.team_race_start(race_set_id, current_turn)
        client.team_race_end(current_turn)
        out = client.team_race_out(current_turn)

    attempts = 0
    continue_source = out if _continue_type(out) is not None else start_res
    max_retries = _continue_limit(continue_source) if race_set_id else 0
    while runner.burn_clocks and attempts < max_retries:
        continue_type = _continue_type(continue_source)
        if continue_type is None:
            break
        if continue_type == 2 and not runner._ensure_alarm_clock(client, preset):
            break
        attempts += 1
        runner._log("team_race_clock", current_turn, f"retry type {continue_type}")
        try:
            continue_res = client.team_race_continue(current_turn=current_turn, continue_type=continue_type)
        except Exception as exc:
            if runner._is_state_recovery_error(exc) or is_blocked_state_error(exc):
                raise
            result_code = api_error_result_code(exc)
            code_text = result_code if result_code is not None else "unknown"
            runner._log(
                "team_race_clock_failed",
                current_turn,
                f"result_code={code_text}: {exc}",
            )
            break
        if continue_type == 2:
            runner._sync_cached_alarm_clock_count(client, continue_res)
        client.team_race_analyze(race_set_id, current_turn)
        start_res = client.team_race_start(race_set_id, current_turn)
        client.team_race_end(current_turn)
        out = client.team_race_out(current_turn)
        continue_source = out
        runner._record_clock_used()

    if strategy and hasattr(strategy, "mark_team_race_done"):
        strategy.mark_team_race_done(current_turn)
    out_data = out.get("data") or {}
    if strategy and out_data.get("unchecked_event_array"):
        out = runner._drain_events(client, strategy, out)

    # After team_race_out + event drain the server can briefly report
    # playing_state 5 on the same turn (post-action state, seen in the
    # 2026-07-08 capture) -- for the strategy that reads as "goal failed"
    # and would wrongly finish the career. Refresh from the server to get
    # the authoritative next-turn state instead.
    final_data = (out or {}).get("data") or {}
    final_chara = final_data.get("chara_info") or {}
    if (
        strategy
        and int(final_chara.get("playing_state") or 0) == 5
        and int(final_chara.get("turn") or 0) == current_turn
        and not final_data.get("unchecked_event_array")
    ):
        runner._log("team_race_refresh", current_turn, "stale playing_state 5 after team race; reloading")
        out = runner._fresh_career_state(client, strategy)
    return out or start_res or edit_res or state


def _team_race_set_id(runner, opponent_response, current_turn):
    data = (opponent_response or {}).get("data") if isinstance(opponent_response, dict) else opponent_response
    team_data_set = (data or {}).get("team_data_set") or {}
    opponents = team_data_set.get("opponent_info_array")
    if isinstance(opponents, list) and opponents:
        best = max(opponents, key=lambda o: int((o or {}).get("team_power") or 0))
        race_set_id = int((best or {}).get("team_race_set_id") or 0)
        if race_set_id:
            return race_set_id
    found = _find_first_int_key(opponent_response, {"race_set_id", "team_race_set_id"})
    if found:
        return found
    # No opponent_info_array and no race_set_id/team_race_set_id anywhere in
    # the response -- guessing here (the old UNITY_TEAM_RACE_SET_IDS turn->id
    # table) risks entering the wrong team race set id, which corrupts the
    # career. Fail loudly instead so the run stops and gets investigated.
    detail = f"no opponent_info_array or race_set_id in opponent_list response (turn {int(current_turn or 0)})"
    runner._log("team_race_set_id_missing", current_turn, detail)
    raise RuntimeError(f"Unity Cup team race: could not determine team_race_set_id -- {detail}")


def _resumed_team_race_set_id(state, playing_state):
    data = (state or {}).get("data") if isinstance(state, dict) else state
    team_data_set = (data or {}).get("team_data_set") or {}
    if playing_state == 8:
        opponents = team_data_set.get("opponent_info_array")
        if isinstance(opponents, list) and opponents:
            race_set_id = int((opponents[0] or {}).get("team_race_set_id") or 0)
            if race_set_id:
                return race_set_id
    if playing_state == 9:
        history = team_data_set.get("team_race_history_array")
    else:
        history = None
    if isinstance(history, list):
        for row in reversed(history):
            race_set_id = int((row or {}).get("team_race_set_id") or 0)
            if race_set_id:
                return race_set_id
    return 0

def _continue_type(response):
    data = (response or {}).get("data") if isinstance(response, dict) else response
    if _find_first_positive_key(data, ("available_free_continue_num",)):
        return 1
    if _find_first_positive_key(data, ("available_continue_num",)):
        return 2
    return None

def _continue_limit(response):
    data = (response or {}).get("data") if isinstance(response, dict) else response
    count = _find_first_positive_key(data, ("available_continue_num",))
    return min(int(count), 5) if count > 0 else 0

def _find_first_int_key(value, keys):
    if isinstance(value, dict):
        for key in keys:
            try:
                n = int(value.get(key) or 0)
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                return n
        for item in value.values():
            found = _find_first_int_key(item, keys)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first_int_key(item, keys)
            if found:
                return found
    return 0

def _find_first_positive_key(value, keys):
    return _find_first_int_key(value, keys)

def _find_first_truthy_key(value, keys):
    if isinstance(value, dict):
        if any(value.get(key) is True for key in keys):
            return True
        return any(_find_first_truthy_key(item, keys) for item in value.values())
    if isinstance(value, list):
        return any(_find_first_truthy_key(item, keys) for item in value)
    return False
