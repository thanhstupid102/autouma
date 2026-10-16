"""Runner race-recovery characterization: 201s raised on the race endpoints.

Carved verbatim out of ``tests/test_201_resilience.py`` by the §13.1/A13
by-owner split -- this half owns ``career_bot/engine``'s race path (event drain,
race_entry, race_end, and the bounded race_out retry ladder).
"""
from career_bot.engine import CareerRunner
from career_bot.scenarios.base import Decision


def career_state(turn=1, playing_state=1, events=None):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "playing_state": playing_state,
                "skill_point": 0,
                "vital": 100,
                "max_vital": 100,
            },
            "home_info": {},
            "free_data_set": {},
            "unchecked_event_array": list(events or []),
        }
    }


class RaceDrainStrategy:
    def _choice(self, event):
        return 0

    def choose_from_event(self, event, current_turn):
        return 0

    def next_decision(self, state, preset):
        turn = int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
        if turn <= 1:
            return Decision("race", {"program_id": 101, "current_turn": turn, "_strategy": self}, "race")
        return Decision("done", {}, "complete")


class RaceDrain201Client:
    circuit_tripped = False
    api_jitter = 0

    def __init__(self):
        self.check_event_calls = 0
        self.load_career_calls = 0
        self.race_end_calls = 0

    def race_entry(self, program_id, current_turn, **kwargs):
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 2}}}

    def race_start(self, is_short, current_turn):
        return career_state(
            current_turn,
            playing_state=5,
            events=[{"event_id": 9001, "chara_id": 42}],
        )

    def check_event(self, **kwargs):
        self.check_event_calls += 1
        if self.check_event_calls == 1:
            raise Exception("API error 201 on single_mode_free/check_event: session/state invalid")
        return career_state(2)

    def load_career(self):
        self.load_career_calls += 1
        return career_state(2)

    def race_end(self, current_turn):
        self.race_end_calls += 1
        return career_state(2)

    def race_out(self, current_turn):
        return career_state(2)


def quiet_runner(monkeypatch, tmp_path):
    import career_bot.engine.runner as runner_module

    monkeypatch.setattr(runner_module.notify, "start_live_monitor", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.notify, "stop_live_monitor", lambda *a, **k: None)
    monkeypatch.setattr(runner_module.notify, "send_career_summary", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "dna_sleep", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "backoff_sleep", lambda *a, **k: None)

    runner = CareerRunner(tmp_path)
    runner._debug_turn = lambda *a, **k: None
    runner._buy_skills = lambda client, state, preset, force: state
    return runner


def test_runner_recovers_201_during_race_event_drain(monkeypatch, tmp_path):
    runner = quiet_runner(monkeypatch, tmp_path)
    client = RaceDrain201Client()

    runner._run(client, {"scenario_id": 1}, career_state(1), RaceDrainStrategy(), max_steps=5)

    snap = runner.snapshot()
    assert client.check_event_calls == 1
    assert client.load_career_calls == 1
    assert snap.get("status") != "error"
    assert snap.get("last_error") == ""
    assert snap.get("finished") is True


class DoneStrategy(RaceDrainStrategy):
    def next_decision(self, state, preset):
        return Decision("done", {}, "complete")


class RaceEntry201Client:
    def __init__(self):
        self.load_career_calls = 0

    def race_entry(self, program_id, current_turn, **kwargs):
        raise Exception("API error 201 on single_mode_free/race_entry: session/state invalid")

    def load_career(self):
        self.load_career_calls += 1
        return career_state(3)


class RaceEnd201Client:
    api_jitter = 0

    def __init__(self):
        self.load_career_calls = 0
        self.race_out_calls = 0

    def race_entry(self, program_id, current_turn, **kwargs):
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 2}}}

    def race_start(self, is_short, current_turn):
        return career_state(current_turn, playing_state=5)

    def race_end(self, current_turn):
        raise Exception("API error 201 on single_mode_free/race_end: session/state invalid")

    def race_out(self, current_turn):
        self.race_out_calls += 1
        return career_state(4)

    def load_career(self):
        self.load_career_calls += 1
        return career_state(4)


def test_race_entry_201_reloads_career_state(tmp_path):
    runner = CareerRunner(tmp_path)
    client = RaceEntry201Client()

    result = runner._race(
        client,
        career_state(1),
        {"scenario_id": 1},
        {"program_id": 101, "current_turn": 1, "_strategy": DoneStrategy()},
    )

    assert client.load_career_calls == 1
    assert result["data"]["chara_info"]["turn"] == 3


def test_race_end_201_reloads_career_state(tmp_path):
    runner = CareerRunner(tmp_path)
    client = RaceEnd201Client()

    result = runner._race(
        client,
        career_state(1),
        {"scenario_id": 1},
        {"program_id": 101, "current_turn": 1, "_strategy": DoneStrategy()},
    )

    assert client.load_career_calls == 1
    assert client.race_out_calls == 0
    assert result["data"]["chara_info"]["turn"] == 4


class RaceOut201StuckStrategy:
    """Mimics mant.next_decision: race on turn 1, then race_progress whenever the
    career is parked on the race screen (playing_state 3)."""

    def _choice(self, event):
        return 0

    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        playing_state = int(chara.get("playing_state") or 0)
        if playing_state == 3:
            return Decision("race_progress", {
                "current_turn": turn,
                "phase": "start",
                "race_start_info": {"program_id": 101},
                "chara_info": chara,
                "_strategy": self,
            }, "resume race start")
        if turn <= 1 and playing_state == 1:
            return Decision("race", {"program_id": 101, "current_turn": turn, "_strategy": self}, "race")
        return Decision("done", {}, "complete")


class RaceOut201StuckClient:
    """race_out always 201s and load always returns the same race-screen state
    (playing_state 3) -- the exact shape that used to loop until the circuit
    breaker tripped."""

    circuit_tripped = False
    api_jitter = 0

    def __init__(self):
        self.race_out_calls = 0
        self.race_start_calls = 0
        self.race_end_calls = 0
        self.race_entry_calls = 0
        self.load_career_calls = 0
        self.login_calls = 0

    def login(self):
        self.login_calls += 1

    def race_entry(self, program_id, current_turn, **kwargs):
        self.race_entry_calls += 1
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 2}}}

    def race_start(self, is_short, current_turn):
        self.race_start_calls += 1
        return career_state(current_turn, playing_state=3)

    def race_end(self, current_turn):
        self.race_end_calls += 1
        return career_state(current_turn, playing_state=3)

    def race_out(self, current_turn):
        self.race_out_calls += 1
        raise Exception("API error 201 on single_mode_free/race_out: session/state invalid")

    def load_career(self):
        self.load_career_calls += 1
        return career_state(1, playing_state=3)


def test_race_out_201_is_bounded_and_stops_cleanly(monkeypatch, tmp_path):
    runner = quiet_runner(monkeypatch, tmp_path)
    runner._parse_race_rank = lambda res: 1  # avoid the clock-burn / rank-parse path
    client = RaceOut201StuckClient()

    runner._run(client, {"scenario_id": 1}, career_state(1, playing_state=1),
                RaceOut201StuckStrategy(), max_steps=20)

    snap = runner.snapshot()
    # race_out: initial + in-place retries + one re-entry-reset attempt, then stop --
    # bounded well under the 6-errors/90s circuit breaker.
    assert client.race_out_calls == 1 + runner._RACE_OUT_INPLACE_RETRIES + 1
    assert client.race_out_calls < 6
    # THE KEY FIX: no reload on a race_out 201. Reloading mid-race-exit is what
    # corrupted the server state into the permanent playing_state-3 lock.
    assert client.load_career_calls == 0
    # Tier 2: re-entered the race fresh to try to clear the stuck exit (initial race +
    # one reset = 2 entries), replaying the full proven-good sequence.
    assert client.race_entry_calls == 2
    # Stopped cleanly with actionable guidance, not the misleading throttling one.
    assert snap.get("status") == "error"
    assert "race_out rejected by the server" in (snap.get("last_error") or "")
    assert snap.get("finished") is not True
