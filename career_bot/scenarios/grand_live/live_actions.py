"""Grand Live action handlers: tree-square purchase and the scheduled live.

Both are registered through GrandLiveStrategy.extra_action_handlers, so the
runner dispatches them without knowing anything Grand-Live-specific. Each
returns the state the runner should continue from.
"""


def _drain(runner, client, strategy, response, state):
    data = (response or {}).get("data") or {}
    if strategy and data.get("unchecked_event_array"):
        return runner._drain_events(client, strategy, response)
    return response or state


def _race_is_stranded(state):
    """Is this state a forced race the race planner cannot resolve?

    single_mode_live/master_square answers with only chara_info, home_info,
    live_data_set, not_up_parameter_info and unchecked_event_array -- verified
    across all 52 master_square responses in the 2026-07-27 run logs, none of
    which carried race_condition_array or race_start_info.

    On a mandatory-race turn that combination is fatal: home_info still says
    every command except (4, 401) is disabled, so RacePlanner.forced_program
    finds race_enabled/other_enabled but no program id anywhere and returns 0,
    and the strategy then has no command to pick either. The run stops on
    `idle`. That is exactly how the 2026-07-27 session died on turns 12, 68 and
    78 -- three separate manual restarts.
    """
    data = (state or {}).get("data") or {}
    commands = (data.get("home_info") or {}).get("command_info_array") or []
    if not commands:
        return False
    race_enabled = any(
        cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0)
        for cmd in commands
    )
    other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
    if not race_enabled or other_enabled:
        return False
    return not (data.get("race_condition_array") or data.get("race_start_info"))


def run_live_square(runner, client, state, preset, payload):
    """Buy one tree square (single_mode_live/master_square).

    One square per decision on purpose: the response carries a fresh
    live_data_set with the tokens spent and the next offers, so the strategy
    re-decides against real state instead of us guessing a batch up front.
    The per-turn cap lives in the strategy (MAX_SQUARE_BUYS_PER_TURN).
    """
    current_turn = int(payload.get("current_turn") or 0)
    square_id = int(payload.get("square_id") or 0)
    strategy = payload.get("_strategy")
    if not square_id:
        return state

    before = strategy.live.tokens if strategy is not None else {}
    result = client.master_square(square_id, current_turn)
    detail = f"bought square {square_id}"
    if strategy is not None:
        strategy.note_square_bought(current_turn, square_id)
        strategy.live.update_from(result)
        spent = strategy.live.token_delta(before)
        detail = f"bought square {square_id}" + (f" ({spent})" if spent else " (no token change)")
        strategy.log_tokens(current_turn, note=detail, preset=preset)
    runner._log("live_square", current_turn, detail)

    result = _drain(runner, client, strategy, result, state)
    if _race_is_stranded(result):
        runner._log(
            "live_square_reload",
            current_turn,
            "master_square response has no race_condition_array on a forced-race turn; reloading",
        )
        return runner._fresh_career_state(client, strategy)
    return result


def run_live_start(runner, client, state, preset, payload):
    """Run the scheduled Grand Live performance (single_mode_live/live_start).

    The turn is marked done before the call so a failure cannot put the runner
    in a retry loop on the same turn -- a live that errors should surface, not
    spin. SingleModeLiveLiveStartResponse carries chara_info and live_data_set
    but no home_info, so the next turn's commands have to come from a fresh
    load rather than this response.
    """
    current_turn = int(payload.get("current_turn") or 0)
    strategy = payload.get("_strategy")
    if strategy is not None:
        strategy.mark_live_done(current_turn)

    result = client.live_start(current_turn)
    if strategy is not None:
        strategy.live.update_from(result)
    runner._log("live_start", current_turn, f"Grand Live performance (turn {current_turn})")

    result = _drain(runner, client, strategy, result, state)
    data = (result or {}).get("data") or {}
    if not data.get("home_info"):
        runner._log("live_start_reload", current_turn, "live_start response has no home_info; reloading career")
        return runner._fresh_career_state(client, strategy)
    return result
