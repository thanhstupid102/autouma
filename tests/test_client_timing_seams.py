"""The two SEPARATE timing seams on ``UmaClient`` (REFACTOR_PLAN.md §13.2, B3).

B3's whole risk is that "inject a timing policy" collapses two unrelated concerns
into one object and thereby silently re-times **live request pacing** (anti-detection)
while someone was only trying to tune a retry. So this suite pins three things:

1. the two seams exist, are independently injectable, and are genuinely separate --
   swapping one must leave the other's waits untouched;
2. the defaults reproduce *exactly* today's ``career_bot.delay`` calls -- same
   primitive, same arguments, same order, on every branch of the ladder;
3. the upward import edge the seams bought us stays cut: importing the transport
   client must not drag the decision engine into the process.

The exhaustive equivalence proof is the differential harness (49,764 cells,
trace-identical); these are the offline pins that keep it that way.
"""
import inspect
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import uma_api.client as client_mod
from uma_api import race_telemetry
from uma_api import timing
from uma_api.client import UmaClient

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# recording doubles
# --------------------------------------------------------------------------- #

class RecordingRetryPolicy:
    """Stands in for seam (a). Records ordered (method, args) and never sleeps."""

    def __init__(self):
        self.calls = []

    def backoff_sleep(self, attempt, base=1.0, cap=15.0):
        self.calls.append(("backoff_sleep", attempt, base, cap))
        return 0.0

    def server_sleep(self, min_val, max_val):
        self.calls.append(("server_sleep", min_val, max_val))
        return 0.0

    def jittered_sleep(self, seconds):
        self.calls.append(("jittered_sleep", seconds))
        return 0.0


class RecordingPacingPolicy:
    """Stands in for seam (b). Records ordered (method, args) and never sleeps."""

    def __init__(self, jitter=0.0):
        self.calls = []
        self._jitter = jitter

    def dna_sleep(self, min_val, max_val):
        self.calls.append(("dna_sleep", round(min_val, 6), round(max_val, 6)))
        return 0.0

    def dna_uniform(self, min_val, max_val):
        self.calls.append(("dna_uniform", min_val, max_val))
        return self._jitter

    def jittered_sleep(self, seconds):
        self.calls.append(("jittered_sleep", seconds))
        return 0.0


class _Resp:
    def __init__(self, status_code=200, text="payload"):
        self.status_code = status_code
        self.text = text


class _Session:
    def __init__(self, posts=None):
        self.headers = {}
        self._posts = list(posts) if posts else None
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        if self._posts is None:
            return _Resp()
        item = self._posts.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        pass


def _dh(rc, sid=None, viewer_id=None):
    d = {"result_code": rc}
    if sid is not None:
        d["sid"] = sid
    if viewer_id is not None:
        d["viewer_id"] = viewer_id
    return {"data_headers": d, "data": {}}


def _wire_client(monkeypatch, unpack_script, posts=None, *, retry=None, pacing=None):
    """A bare client with the wire stubbed and both seams replaced by recorders."""
    c = UmaClient.__new__(UmaClient)
    c.sid = b"\x00" * 16
    c.udid_str = "00000000-0000-0000-0000-000000000000"
    c.viewer_id = 123
    c.app_ver = "1.0.0"
    c.res_ver = "1000"
    c.current_scenario_id = None
    c.api_warehouse_account = ""
    c.account_name = "tester"
    c.session = _Session(posts)
    c._call_lock = threading.RLock()
    c._last_raw_call_ts = 0          # far in the past -> no 0.14s floor on entry

    c.common = lambda: {}
    c.auth_bytes = lambda: b""
    c.api_log = lambda *a, **k: None
    c._refresh_resource_version = lambda d: True
    c._store_api_response = lambda ep, r: None
    c.refresh_cached_account_state = lambda d: None
    c._remember_scenario_from_data = lambda d: None
    c._note_api_error = lambda ep, rc: None
    c.regen_sid = lambda: None

    c.retry_policy = retry if retry is not None else RecordingRetryPolicy()
    c.pacing_policy = pacing if pacing is not None else RecordingPacingPolicy()

    script = list(unpack_script)
    monkeypatch.setattr(client_mod, "pack", lambda *a, **k: b"body")
    monkeypatch.setattr(client_mod, "get_raw_udid", lambda u: b"\x00" * 16)
    monkeypatch.setattr(client_mod, "next_sid", lambda s: b"\x11" * 16)
    monkeypatch.setattr(client_mod, "unpack",
                        lambda text, udid: script[0] if len(script) == 1 else script.pop(0))
    monkeypatch.setattr(client_mod._update_guard, "alert_once", lambda *a, **k: None)
    return c


# --------------------------------------------------------------------------- #
# 1. the seams exist, are injectable, and are SEPARATE
# --------------------------------------------------------------------------- #

def test_both_seams_are_constructor_injectable_and_default_to_none():
    params = inspect.signature(UmaClient.__init__).parameters
    for name in ("retry_policy", "pacing_policy"):
        assert name in params, name
        assert params[name].default is None


def test_seams_default_lazily_even_on_a_new_built_client():
    # The offline harness builds clients via __new__ (real __init__ needs the
    # Windows registry); the seams must still resolve today's defaults.
    c = UmaClient.__new__(UmaClient)
    assert isinstance(c.retry_policy, timing.TransportRetryPolicy)
    assert isinstance(c.pacing_policy, timing.AccountPacingPolicy)
    # ...and memoize, so one client keeps one policy instance.
    assert c.retry_policy is c.retry_policy
    assert c.pacing_policy is c.pacing_policy


def test_seams_are_assignable_and_do_not_alias_each_other():
    c = UmaClient.__new__(UmaClient)
    retry, pacing = RecordingRetryPolicy(), RecordingPacingPolicy()
    c.retry_policy = retry
    c.pacing_policy = pacing
    assert c.retry_policy is retry and c.pacing_policy is pacing
    assert c.retry_policy is not c.pacing_policy


def test_retry_waits_come_from_the_retry_seam_only(monkeypatch):
    """A 500 -> 205 -> 208 -> 208 -> ok ladder: every wait is a RETRY wait."""
    c = _wire_client(monkeypatch, [_dh(500), _dh(205), _dh(208), _dh(208), _dh(1)])
    assert c.call("single_mode_free/race_end", {})["data_headers"]["result_code"] == 1
    assert c.retry_policy.calls == [
        ("backoff_sleep", 0, 1.0, 15.0),      # rc 500, attempt = 3 - retry_500(3)
        ("server_sleep", 0.3, 0.7),           # rc 205
        # first 208 does not back off (retry_208 == 6), the second does
        ("backoff_sleep", 1, 1.0, 15.0),      # attempt = 6 - retry_208(5)
    ]
    # ...and the pacing seam only ever supplied the inter-call floor.
    assert {name for name, *_ in c.pacing_policy.calls} == {"dna_sleep"}


def test_pacing_floor_comes_from_the_pacing_seam_only(monkeypatch):
    c = _wire_client(monkeypatch, [_dh(1)])
    c._last_raw_call_ts = client_mod.time.monotonic()  # "too fast" -> floor applies
    c.call("load/index", {})
    assert len(c.pacing_policy.calls) == 1
    name, lo, hi = c.pacing_policy.calls[0]
    assert name == "dna_sleep" and lo == hi and 0 < lo <= 0.14
    assert c.retry_policy.calls == []                  # no retry -> no retry wait


def test_pacing_floor_ignores_a_backwards_wall_clock_jump(monkeypatch):
    c = _wire_client(monkeypatch, [_dh(1)])
    c._last_raw_call_ts = 50.0
    wall_values = iter((10_000.0, 1.0))
    wall_reads = []
    monotonic_values = iter((50.05, 50.06))

    def backwards_wall_clock():
        wall_reads.append(True)
        return next(wall_values)

    monkeypatch.setattr(client_mod.time, "time", backwards_wall_clock)
    monkeypatch.setattr(
        client_mod.time, "monotonic", lambda: next(monotonic_values),
    )

    c.call("load/index", {})

    assert c.pacing_policy.calls == [("dna_sleep", 0.09, 0.09)]
    assert c._last_raw_call_ts == 50.06
    assert wall_reads == []


def test_replacing_the_pacing_seam_cannot_change_a_retry_wait(monkeypatch):
    """The anti-merge pin: this is exactly what a single policy object would break."""
    baselines = []
    for pacing in (RecordingPacingPolicy(), RecordingPacingPolicy(jitter=99.0), None):
        retry = RecordingRetryPolicy()
        c = _wire_client(monkeypatch, [_dh(500), _dh(500), _dh(1)],
                         retry=retry, pacing=pacing)
        c.call("single_mode_free/race_end", {})
        baselines.append(retry.calls)
    assert baselines[0] == baselines[1] == baselines[2]
    assert baselines[0] == [("backoff_sleep", 0, 1.0, 15.0), ("backoff_sleep", 1, 1.0, 15.0)]


class SlowRetryPolicy(RecordingRetryPolicy):
    """A retry seam that asks for very different waits -- pacing must not notice.

    (The durations are only *requested*; nothing here actually sleeps, so the
    comparison below is not racing a wall clock.)
    """

    def backoff_sleep(self, attempt, base=60.0, cap=600.0):
        self.calls.append(("backoff_sleep", attempt, base, cap))
        return 600.0


def test_replacing_the_retry_seam_cannot_change_live_pacing(monkeypatch):
    shapes = []
    for retry in (RecordingRetryPolicy(), SlowRetryPolicy()):
        pacing = RecordingPacingPolicy()
        c = _wire_client(monkeypatch, [_dh(500), _dh(1)], retry=retry, pacing=pacing)
        c._last_raw_call_ts = client_mod.time.monotonic()
        c.call("single_mode_free/race_end", {})
        # The floor's argument is `0.14 - elapsed`, i.e. monotonic-clock derived; the
        # invariant is its SHAPE and bound, which a retry swap must never move.
        for name, lo, hi in pacing.calls:
            assert name == "dna_sleep" and lo == hi and 0 < lo <= 0.14
        shapes.append([name for name, *_ in pacing.calls])
    assert shapes[0] == shapes[1] == ["dna_sleep", "dna_sleep"]


def test_network_and_http_5xx_retries_use_the_retry_seam(monkeypatch):
    c = _wire_client(monkeypatch, [_dh(1)],
                     posts=[ConnectionError("boom"), _Resp(503), _Resp()])
    c.call("load/index", {})
    assert c.retry_policy.calls == [
        ("backoff_sleep", 0, 1.0, 15.0),      # network exception
        ("backoff_sleep", 1, 1.0, 15.0),      # HTTP 503
    ]


def test_login_retry_waits_use_the_retry_seam(monkeypatch):
    c = UmaClient.__new__(UmaClient)
    c.session = _Session()
    c.has_game_auth = lambda: True
    c.regen_sid = lambda: None
    c.refresh_cached_account_state = lambda d: None
    retry = RecordingRetryPolicy()
    c.retry_policy = retry
    c.pacing_policy = RecordingPacingPolicy()

    errs = ["394", "202"]

    def _call(ep, args=None):
        if ep == "tool/start_session" and errs:
            raise Exception(f"API error {errs.pop(0)} on {ep}")
        return {"data_headers": {"result_code": 1}, "data": {}}

    c.call = _call
    monkeypatch.setattr(client_mod.requests, "Session", _Session)
    c.login(max_retries=3)

    assert retry.calls == [
        ("jittered_sleep", 2.5),    # 394
        ("jittered_sleep", 4.15),   # 202
    ]
    assert c.pacing_policy.calls == []

def test_api_jitter_is_drawn_through_the_injected_pacing_seam(monkeypatch):
    """Constructor injection end-to-end: api_jitter must come from seam (b)."""
    monkeypatch.setattr(client_mod, "get_hwid", lambda seed: {"udid": "u-0000"})
    monkeypatch.setattr(client_mod.identity, "resolve_device_identity",
                        lambda cfg, profile: {
                            "device_id": "d", "device_name": "n",
                            "graphics_device_name": "g", "ip_address": "1.2.3.4",
                            "platform_os_version": "os",
                        })
    monkeypatch.setattr(client_mod._client_version, "load_client_version", lambda base: {})
    monkeypatch.setattr(client_mod._client_version, "resolve_versions",
                        lambda cv, cfg, a, b: (a, b))
    monkeypatch.setattr(client_mod._client_version, "get_resource_server", lambda base: "")
    monkeypatch.setattr(client_mod.requests, "Session", _Session)

    pacing = RecordingPacingPolicy(jitter=0.0123)
    retry = RecordingRetryPolicy()
    c = UmaClient({"viewer_id": 7}, trace_enabled=False,
                  retry_policy=retry, pacing_policy=pacing)

    assert c.retry_policy is retry and c.pacing_policy is pacing
    assert c.api_jitter == 0.0123
    assert pacing.calls == [("dna_uniform", -0.02, 0.02)]
    assert retry.calls == []


# --------------------------------------------------------------------------- #
# 2. the defaults reproduce today's career_bot.delay calls exactly
# --------------------------------------------------------------------------- #

@pytest.fixture
def hooks(monkeypatch):
    """Record what the DEFAULT policies ask of uma_api.client's timing hooks."""
    seen = []
    monkeypatch.setattr(client_mod, "backoff_sleep",
                        lambda attempt, **k: seen.append(("backoff_sleep", attempt, k)))
    monkeypatch.setattr(client_mod, "server_sleep",
                        lambda a, b: seen.append(("server_sleep", a, b)))
    monkeypatch.setattr(client_mod, "jittered_sleep",
                        lambda s: seen.append(("jittered_sleep", s)))
    monkeypatch.setattr(client_mod, "dna_sleep",
                        lambda a, b: seen.append(("dna_sleep", a, b)))
    monkeypatch.setattr(client_mod, "dna_uniform",
                        lambda a, b: seen.append(("dna_uniform", a, b)) or 0.0)
    return seen


def test_default_retry_policy_forwards_verbatim(hooks):
    policy = client_mod.default_retry_policy()
    policy.backoff_sleep(2, base=1.0, cap=15.0)
    policy.server_sleep(0.3, 0.7)
    policy.jittered_sleep(4.15)
    assert hooks == [
        ("backoff_sleep", 2, {"base": 1.0, "cap": 15.0}),
        ("server_sleep", 0.3, 0.7),
        ("jittered_sleep", 4.15),
    ]


def test_default_pacing_policy_forwards_verbatim(hooks):
    policy = client_mod.default_pacing_policy()
    policy.dna_sleep(0.14, 0.14)
    policy.dna_uniform(-0.02, 0.02)
    policy.jittered_sleep(0.83)
    assert hooks == [
        ("dna_sleep", 0.14, 0.14),
        ("dna_uniform", -0.02, 0.02),
        ("jittered_sleep", 0.83),
    ]


def test_module_hooks_stay_the_monkeypatch_seam_the_ladder_uses(hooks, monkeypatch):
    """Patching uma_api.client.<name> must still divert the DEFAULT policies --
    8 test modules depend on exactly this."""
    c = _wire_client(monkeypatch, [_dh(500), _dh(205), _dh(1)],
                     retry=client_mod.default_retry_policy(),
                     pacing=client_mod.default_pacing_policy())
    c._last_raw_call_ts = client_mod.time.monotonic()
    c.call("single_mode_free/race_end", {})
    assert ("backoff_sleep", 0, {"base": 1.0, "cap": 15.0}) in hooks
    assert ("server_sleep", 0.3, 0.7) in hooks
    assert any(name == "dna_sleep" for name, *_ in hooks)


def test_timing_primitives_are_thin_forwarders_onto_career_bot_delay(monkeypatch):
    import career_bot.delay as delay

    seen = []
    monkeypatch.setattr(delay, "dna_sleep", lambda *a: seen.append(("dna_sleep",) + a) or 1.0)
    monkeypatch.setattr(delay, "dna_uniform", lambda *a: seen.append(("dna_uniform",) + a) or 2.0)
    monkeypatch.setattr(delay, "dna_gauss", lambda *a: seen.append(("dna_gauss",) + a) or 3.0)
    monkeypatch.setattr(delay, "jittered_sleep", lambda *a: seen.append(("jittered_sleep",) + a) or 4.0)
    monkeypatch.setattr(delay, "backoff_sleep",
                        lambda attempt, **k: seen.append(("backoff_sleep", attempt, k)) or 5.0)
    monkeypatch.setattr(delay, "server_sleep", lambda *a: seen.append(("server_sleep",) + a) or 6.0)

    assert timing.dna_sleep(0.1, 0.2) == 1.0
    assert timing.dna_uniform(-1, 1) == 2.0
    assert timing.dna_gauss(991, 62) == 3.0
    assert timing.jittered_sleep(0.83) == 4.0
    assert timing.backoff_sleep(3, base=1.0, cap=15.0) == 5.0
    assert timing.server_sleep(0.3, 0.7) == 6.0
    assert seen == [
        ("dna_sleep", 0.1, 0.2, None, None),
        ("dna_uniform", -1, 1),
        ("dna_gauss", 991, 62),
        ("jittered_sleep", 0.83, 0.3),
        ("backoff_sleep", 3, {"base": 1.0, "cap": 15.0, "factor": 2.0}),
        ("server_sleep", 0.3, 0.7),
    ]


def test_race_telemetry_still_draws_from_the_account_dna(monkeypatch):
    import career_bot.delay as delay

    monkeypatch.setattr(delay, "dna_gauss", lambda mean, sd: float(mean))
    monkeypatch.setattr(delay, "dna_uniform", lambda a, b: 3.0)
    monkeypatch.setattr(race_telemetry, "screen_height", lambda default=864: 1080)
    info = race_telemetry.build_button_info(42, 4)
    assert info["ViewerId"] == 42 and info["ScenarioId"] == 4
    assert info["ClickPosX"] > 0 and info["ClickPosY"] > 0


# --------------------------------------------------------------------------- #
# 3. the import edge the seams bought us stays cut
# --------------------------------------------------------------------------- #

def _fresh_import(statement):
    return subprocess.run([sys.executable, "-B", "-c", statement],
                          cwd=str(ROOT), capture_output=True, text=True)


def test_uma_api_client_does_not_import_career_bot():
    # §13.2 B3: the five delay primitives are call-time forwarders now, so merely
    # importing the transport client must not drag the decision engine in.
    result = _fresh_import(
        "import sys, uma_api.client; "
        "print(any(m == 'career_bot' or m.startswith('career_bot.') for m in sys.modules))"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_uma_api_race_telemetry_does_not_import_career_bot():
    result = _fresh_import(
        "import sys, uma_api.race_telemetry; "
        "print(any(m == 'career_bot' or m.startswith('career_bot.') for m in sys.modules))"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_no_module_level_career_bot_import_remains_in_uma_api():
    offenders = []
    for path in sorted((ROOT / "uma_api").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith(("import career_bot", "from career_bot")):
                offenders.append(f"{path.name}:{lineno}")
    assert offenders == []
