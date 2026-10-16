# career_bot/scenarios

Per-scenario career strategies behind one registry.

    __init__.py   STRATEGIES registry + get_strategy_class + resolve_scenario_id
    base.py       Decision, ScenarioStrategy: shared career flow (events, finish/race
                  resume building blocks, command/bond helpers), the capability
                  attributes the runner consults, and neutral scenario hooks
                  (e.g. _ignored_group_bond_slots -> set(); no Sirius/Throne
                  knowledge lives here)
    scoring.py    TrainingScoreMixin: preset-driven training scorer (opt-in per scenario)
    objectives.py RouteObjectives + RouteObjectivesMixin: mandatory trainee route
                  races. Fan objectives are ignored; users schedule optional races
                  through presets. MANT's point objectives are also ignored here
    mant/         scenario_id 4 (MANT / Trackblazer): coin-shop items, the Sirius/Throne
                  two-pal-deck tactics (card ids, outing schedule, bond exclusions --
                  this strat only works well in MANT), charm/energy rescue, medic tank
    unity_cup/    scenario_id 2 (Unity Cup): team race (roster builder + API flow),
                  speed/wit command picker; objectives come from the shared layer
    grand_live/   scenario_id 3 (Grand Live): Live Tree squares bought with the five
                  performance tokens (live_state.py models live_data_set,
                  squares.py ranks offers against master.mdb), plus the scheduled
                  live on turns 24/36/48/60/72. Training uses the shared scorer

## Adding a scenario

1. Create `career_bot/scenarios/<name>/` with `strategy.py`:
   `class <Name>Strategy(ScenarioStrategy)` (add `TrainingScoreMixin` if you want the
   preset-driven scorer), set a unique `scenario_id`, implement `next_decision` by
   composing the base building blocks (`_finish_common_decision`, `_event_decision`,
   `_race_state_decision`, `_command_decision`) around your scenario logic.
2. If the scenario's trainees carry route objectives (`single_mode_route_race` —
   most scenarios do; MANT doesn't): add `RouteObjectivesMixin` to the bases, set
   `self.objectives = RouteObjectives(base_dir)` in `__init__` (and call
   `self.objectives.reset()` in `reset_run_state`), steer forced races with
   `self.objectives.race_program_for_turn(chara, turn)` via
   `race_planner.forced_program(state, preferred=...)`. Fan-objective rows are
   intentionally ignored; optional races only come from user presets through
   `race_planner.choose(state, preset)`.
3. Declare capabilities as class attributes instead of editing the runner:
   - `handles_shop_items = True` if the scenario uses the MANT-style coin shop
   - `verbose_response_log = True` to console-print every API response
   - `extra_playing_states = frozenset({...})` for scenario-specific playing_states
   - `extra_action_handlers()` returning `{action: handler(runner, client, state,
     preset, payload)}` for scenario-specific Decision actions (see
     unity_cup/team_race.py)
   - `free_clock_retry = True` (MANT only) to keep the runner's legacy "force
     clocks until 1st place" behavior on `_should_force_clocks`-matched /
     `_mandatory` races. False (default) makes the runner instead honor
     `Decision.payload["_required_rank"]` -- clock retries only for a route
     objective the trainee just failed to meet, never on a race without one
     (see career_bot/runner.py `_race` and unity_cup/strategy.py)
4. Re-export the strategy from `<name>/__init__.py` and add the class to
   `STRATEGY_CLASSES` in `scenarios/__init__.py`.
5. Add tests beside the existing ones (`tests/test_<name>_*.py`); keep scenario state
   on the strategy (reset it in `reset_run_state`), never on the runner.
