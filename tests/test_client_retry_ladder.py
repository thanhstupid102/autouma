"""Characterization of UmaClient.call / _call_locked -- the wire retry ladder.

The result-code handling ladder (network retry, HTTP 5xx, 500/205/208, terminal
709, version/resource-stale, auth-invalidated, circuit-breaker) is the least offline-
tested and highest-consequence code in the engine: a wrong retry count or a
mis-advanced SID corrupts a live career. This suite pins the CURRENT observable
behaviour (post counts, which sleep fires, SID advance, final exception type /
return) so the recursion->loop rewrite can be proven equivalent.

Harness: a bare UmaClient (via __new__, __init__ skipped -- it needs the Windows
registry) with the wire boundary stubbed. `unpack` is monkeypatched to pop a
scripted list of decoded responses (each a {'data_headers': {...}, 'data': {...}}),
so a test drives the exact result_code sequence the "server" returns; session.post
returns a dummy 200 (or scripted HTTP/network failures). Sleeps, SID, circuit
notes, regen_sid are recorded, never real.
"""
import os

os.environ.setdefault("SWEEPY_SKIP_STARTUP_GEN", "1")

import threading
import time
import pytest

import uma_api.client as client_mod
from uma_api.client import UmaClient, ApiError
from uma_api import appstore_version
from uma_api import update_guard as _update_guard
from uma_api.errors import SteamAccountRemoveChainedError
from uma_api.trace import TraceLog, iter_trace_records


class FakeResp:
    def __init__(self, status_code=200, text="payload"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    """post() returns 200 forever by default; pass `posts` to script HTTP status
    codes or raise network exceptions (an item that is a BaseException is raised)."""
    def __init__(self, posts=None):
        self._posts = list(posts) if posts is not None else None
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(url)
        if self._posts is None:
            return FakeResp()
        item = self._posts.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def res(rc, *, sid=None, viewer_id=None, data=None):
    dh = {"result_code": rc}
    if sid is not None:
        dh["sid"] = sid
    if viewer_id is not None:
        dh["viewer_id"] = viewer_id
    return {"data_headers": dh, "data": data if data is not None else {}}


class Rec:
    def __init__(self):
        self.backoff = []
        self.server = []
        self.dna = []
        self.notes = []
        self.regen = 0


def make_client(monkeypatch, unpack_script, *, posts=None, refresh_res_ver=False,
                app_ver_fresh=None, viewer_id=123, app_ver="1.0.0"):
    c = UmaClient.__new__(UmaClient)
    c.sid = b"\x00" * 16
    c.udid_str = "00000000-0000-0000-0000-000000000000"
    c.viewer_id = viewer_id
    c.app_ver = app_ver
    c.res_ver = "1000"
    c.current_scenario_id = None
    c.api_warehouse_account = ""
    c.account_name = "tester"
    c.session = FakeSession(posts)

    c.common = lambda: {}
    c.auth_bytes = lambda: b""
    c.api_log = lambda *a, **k: None
    c._refresh_resource_version = lambda dh: refresh_res_ver
    c._store_api_response = lambda ep, r: None
    c.refresh_cached_account_state = lambda d: None
    c._remember_scenario_from_data = lambda d: None

    rec = Rec()
    c._note_api_error = lambda ep, rc: rec.notes.append((ep, rc))
    c.regen_sid = lambda: setattr(rec, "regen", rec.regen + 1)

    monkeypatch.setattr(client_mod, "pack", lambda *a, **k: b"body")
    monkeypatch.setattr(client_mod, "get_raw_udid", lambda u: b"\x00" * 16)
    monkeypatch.setattr(client_mod, "next_sid", lambda s: b"\x11" * 16)
    monkeypatch.setattr(client_mod, "dna_sleep", lambda *a, **k: rec.dna.append(a))
    monkeypatch.setattr(client_mod, "backoff_sleep", lambda attempt, **k: rec.backoff.append(attempt))
    monkeypatch.setattr(client_mod, "server_sleep", lambda *a, **k: rec.server.append(a))
    monkeypatch.setattr(_update_guard, "alert_once", lambda *a, **k: None)
    monkeypatch.setattr(client_mod._client_version, "get_app_ver",
                        lambda base_dir: app_ver_fresh)
    monkeypatch.setattr(
        appstore_version,
        "ensure_app_ver_headless",
        lambda *_args, **_kwargs: app_ver_fresh,
    )

    script = list(unpack_script)
    monkeypatch.setattr(client_mod, "unpack", lambda text, udid: script.pop(0))
    return c, rec


# --------------------------------------------------------------------------- #
# success + SID
# --------------------------------------------------------------------------- #

def test_success_returns_res_single_post(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1)])
    out = c.call("load/index", {})
    assert out["data_headers"]["result_code"] == 1
    assert len(c.session.calls) == 1
    assert rec.backoff == [] and rec.server == []


def test_success_advances_sid_from_data_headers(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1, sid="serversid")])
    before = c.sid
    c.call("load/index", {})
    assert c.sid == b"\x11" * 16 and c.sid != before


def test_no_sid_in_headers_leaves_sid_unchanged(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1)])
    before = c.sid
    c.call("load/index", {})
    assert c.sid == before


# --------------------------------------------------------------------------- #
# network / HTTP layer
# --------------------------------------------------------------------------- #

def test_http_5xx_retries_with_backoff_then_succeeds(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1)], posts=[FakeResp(503), FakeResp(200)])
    c.call("load/index", {})
    assert len(c.session.calls) == 2
    assert rec.backoff == [0]  # one 5xx retry, attempt index 0


def test_transport_retries_record_every_wire_attempt_in_sidecar(tmp_path, monkeypatch):
    c, _rec = make_client(
        monkeypatch,
        [res(1)],
        posts=[ConnectionError("network down"), FakeResp(503), FakeResp(200)],
    )
    trace = TraceLog(tmp_path, flush_interval=1)
    path = trace.initialize()
    c.on_api_log = None
    c._trace_log = trace
    c.trace_file = path
    c.api_log = UmaClient.api_log.__get__(c, UmaClient)

    c.call("load/index", {})
    trace.close()

    records = list(iter_trace_records(path))
    assert [record["direction"] for record in records] == [
        "REQ", "ERR", "REQ", "ERR", "REQ", "RES",
    ]
    assert [
        record["data"]["wire_attempt"]
        for record in records
        if record["direction"] == "REQ"
    ] == [1, 2, 3]
    assert [
        record["data"]["wire_attempt"]
        for record in records
        if record["direction"] == "ERR"
    ] == [1, 2]


def test_network_exception_retries_then_raises(monkeypatch):
    # 8 network failures in a row -> exhausts max_retries, raises "Network error"
    c, rec = make_client(monkeypatch, [res(1)], posts=[ConnectionError("boom")] * 8)
    with pytest.raises(Exception, match="Network error"):
        c.call("load/index", {})
    assert len(c.session.calls) == 8
    assert rec.backoff == [0, 1, 2, 3, 4, 5, 6]  # backoff on all but the last


def test_non_200_status_raises_http(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1)], posts=[FakeResp(404, "nope")])
    with pytest.raises(Exception, match="HTTP 404"):
        c.call("load/index", {})


# --------------------------------------------------------------------------- #
# result_code 500 / 205 / 208
# --------------------------------------------------------------------------- #

def test_result_500_retry_then_success(monkeypatch):
    c, rec = make_client(monkeypatch, [res(500), res(1)])
    c.call("single_mode_free/race_end", {})
    assert len(c.session.calls) == 2
    assert rec.backoff == [0]  # attempt = 3 - retry_500(3) = 0


def test_result_500_exhausts_then_raises_apierror(monkeypatch):
    # retry_500 default 3 -> original + 3 retries = 4 posts, then rc=500 falls
    # through the ladder (OTHER) and raises ApiError(500).
    c, rec = make_client(monkeypatch, [res(500)] * 4)
    with pytest.raises(ApiError) as ei:
        c.call("single_mode_free/race_end", {})
    assert ei.value.result_code == 500
    assert len(c.session.calls) == 4
    assert rec.backoff == [0, 1, 2]


def test_result_205_retry_uses_server_sleep(monkeypatch):
    c, rec = make_client(monkeypatch, [res(205), res(1)])
    c.call("single_mode_free/load", {})
    assert len(c.session.calls) == 2
    assert len(rec.server) == 1 and rec.backoff == []


def test_result_208_batch_endpoint_raises_immediately(monkeypatch):
    c, rec = make_client(monkeypatch, [res(208)])
    with pytest.raises(ApiError) as ei:
        c.call("single_mode_free/multi_item_use", {})
    assert ei.value.result_code == 208
    assert "server busy" in str(ei.value)
    assert len(c.session.calls) == 1  # no retry -- immediate recoverable raise


def test_result_208_nonbatch_retries_first_without_backoff(monkeypatch):
    # first 208 (retry_208=6): 6<6 False -> no backoff, still recurses; then success
    c, rec = make_client(monkeypatch, [res(208), res(1)])
    c.call("single_mode_free/load", {})
    assert len(c.session.calls) == 2
    assert rec.backoff == []  # first retry does not back off


def test_result_208_nonbatch_second_retry_backs_off(monkeypatch):
    c, rec = make_client(monkeypatch, [res(208), res(208), res(1)])
    c.call("single_mode_free/load", {})
    assert len(c.session.calls) == 3
    assert rec.backoff == [1]  # attempt = 6 - retry_208(5) = 1 on the 2nd 208


# --------------------------------------------------------------------------- #
# 709: terminal Steam-account linkage state
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("response_viewer_id", [999, 123])
def test_709_raises_terminal_linkage_error_without_identity_mutation(
    monkeypatch, response_viewer_id,
):
    c, rec = make_client(monkeypatch, [res(709, viewer_id=response_viewer_id)], viewer_id=123)
    with pytest.raises(SteamAccountRemoveChainedError) as exc_info:
        c.call("load/index", {})

    assert exc_info.value.endpoint == "load/index"
    assert c.viewer_id == 123
    assert rec.regen == 0
    assert len(c.session.calls) == 1


def test_login_does_not_retry_terminal_709(monkeypatch):
    class LoginSession:
        def __init__(self):
            self.headers = {}

        def close(self):
            pass

    client = UmaClient.__new__(UmaClient)
    client.session = LoginSession()
    client.has_game_auth = lambda: True
    client.regen_sid = lambda: None
    calls = []

    def reject(*args, **kwargs):
        calls.append((args, kwargs))
        raise SteamAccountRemoveChainedError(709, "tool/start_session", "still chained")

    client.call = reject
    monkeypatch.setattr(client_mod.requests, "Session", LoginSession)

    with pytest.raises(SteamAccountRemoveChainedError):
        client.login(max_retries=3)

    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# version-stale (204) / resource-stale (214)
# --------------------------------------------------------------------------- #

def test_version_stale_refreshes_app_ver_and_retries(monkeypatch):
    c, rec = make_client(monkeypatch, [res(204), res(1)], app_ver="1.0.0", app_ver_fresh="2.0.0")
    c.call("load/index", {})
    assert c.app_ver == "2.0.0"
    assert len(c.session.calls) == 2


def test_version_stale_retries_once_without_a_new_version_then_raises(monkeypatch):
    c, rec = make_client(
        monkeypatch,
        [res(204), res(204)],
        app_ver="1.0.0",
        app_ver_fresh=None,
    )
    with pytest.raises(_update_guard.ClientVersionError):
        c.call("load/index", {})
    assert len(c.session.calls) == 2


def test_resource_stale_retries_once_then_raises_apierror(monkeypatch):
    c, rec = make_client(monkeypatch, [res(214), res(214)], refresh_res_ver=True)
    with pytest.raises(ApiError) as ei:
        c.call("load/index", {})
    assert ei.value.result_code == 214
    assert len(c.session.calls) == 2  # retried once (_ver_retry), then raised


# --------------------------------------------------------------------------- #
# auth-invalidated + circuit breaker note
# --------------------------------------------------------------------------- #

def test_auth_invalidated_203_raises(monkeypatch):
    c, rec = make_client(monkeypatch, [res(203)])
    with pytest.raises(_update_guard.AuthInvalidatedError):
        c.call("single_mode_free/exec_command", {})


def test_102_reregistration_signature_raises_auth_invalidated(monkeypatch):
    # 102 + a mismatched non-zero viewer_id in the headers => re-registered auth
    c, rec = make_client(monkeypatch, [res(102, viewer_id=999)], viewer_id=123)
    with pytest.raises(_update_guard.AuthInvalidatedError):
        c.call("single_mode_free/exec_command", {})


def test_unhandled_code_raises_apierror_and_notes_circuit(monkeypatch):
    c, rec = make_client(monkeypatch, [res(209)])
    with pytest.raises(ApiError) as ei:
        c.call("single_mode_free/exec_command", {})
    assert ei.value.result_code == 209
    assert rec.notes == [("single_mode_free/exec_command", 209)]


def test_recovered_by_design_load_skips_circuit_note(monkeypatch):
    # 102 on a /load endpoint is recovered-by-design: it must NOT trip the breaker
    c, rec = make_client(monkeypatch, [res(102)])
    with pytest.raises(ApiError) as ei:
        c.call("single_mode_free/load", {})
    assert ei.value.result_code == 102
    assert rec.notes == []  # circuit breaker not notified


# --------------------------------------------------------------------------- #
# rate limit
# --------------------------------------------------------------------------- #

def test_rate_limit_sleeps_when_called_within_140ms(monkeypatch):
    c, rec = make_client(monkeypatch, [res(1)])
    c._last_raw_call_ts = time.monotonic()  # just now -> next call is "too fast"
    c.call("load/index", {})
    assert len(rec.dna) == 1  # dna_sleep fired to honour the 0.14s floor


class DummyResponse:
    status_code = 200
    text = "packed"


class DummySession:
    def post(self, *args, **kwargs):
        return DummyResponse()


def test_api_error_response_still_advances_sid(monkeypatch):
    import pytest
    import uma_api.client as client_module
    from uma_api.client import UmaClient, next_sid

    client = UmaClient.__new__(UmaClient)
    client.sid = bytes(16)
    client.udid_str = "00000000-0000-0000-0000-000000000000"
    client.viewer_id = 1
    client.app_ver = "1.0.0"
    client.res_ver = "1"
    client.session = DummySession()
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client.current_scenario_id = None
    client.api_jitter = 0
    client.api_log = lambda *args, **kwargs: None
    client.common = lambda: {"viewer_id": 1}
    client.auth_bytes = lambda: b""
    client._note_api_error = lambda *args, **kwargs: None

    monkeypatch.setattr(client_module, "pack", lambda *args, **kwargs: b"request-body")
    monkeypatch.setattr(client_module, "get_raw_udid", lambda udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack", lambda text, udid: {
        "response_code": 102,
        "data_headers": {
            "result_code": 102,
            "sid": "server-sid-after-error",
        },
    })

    with pytest.raises(Exception, match="API error 102"):
        client.call("single_mode_free/start", {})

    assert client.sid == next_sid("server-sid-after-error")


def test_api_500_response_retries_after_sid_resync(monkeypatch):
    import uma_api.client as client_module
    from uma_api.client import UmaClient, next_sid

    class OkSession:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return DummyResponse()

    client = UmaClient.__new__(UmaClient)
    client.sid = bytes(16)
    client.udid_str = "00000000-0000-0000-0000-000000000000"
    client.viewer_id = 1
    client.app_ver = "1.0.0"
    client.res_ver = "1"
    client.session = OkSession()
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client.current_scenario_id = None
    client.api_jitter = 0
    client.api_log = lambda *args, **kwargs: None
    client.common = lambda: {"viewer_id": 1}
    client.auth_bytes = lambda: b""
    client._note_api_error = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("500 retry should not trip circuit"))

    responses = iter([
        {"data_headers": {"result_code": 500, "sid": "server-sid-after-500"}, "data": {}},
        {"data_headers": {"result_code": 1, "sid": "server-sid-after-ok"}, "data": {}},
    ])
    monkeypatch.setattr(client_module, "pack", lambda *args, **kwargs: b"request-body")
    monkeypatch.setattr(client_module, "get_raw_udid", lambda udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack", lambda text, udid: next(responses))
    monkeypatch.setattr(client_module, "backoff_sleep", lambda *args, **kwargs: None)

    assert client.call("single_mode_team/start", {})["data_headers"]["result_code"] == 1
    assert client.session.calls == 2
    assert client.sid == next_sid("server-sid-after-ok")


# --------------------------------------------------------------------------- #
# SID-chain serialization + circuit-breaker accounting
#
# Moved verbatim out of tests/test_201_resilience.py by the §13.1/A13 by-owner
# carve: these exercise uma_api.client.call, the same owner as the ladder above.
# (The module-level DummyResponse defined earlier is reused -- the carved block
# brought a byte-identical copy that was dropped as a duplicate.)
# --------------------------------------------------------------------------- #

class SerialPostSession:
    def __init__(self):
        self.headers = {}
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def post(self, *args, **kwargs):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return DummyResponse()


def test_uma_client_call_serializes_sid_chain(monkeypatch):
    import uma_api.client as client_module
    from uma_api.client import UmaClient, next_sid

    client = UmaClient.__new__(UmaClient)
    client.sid = bytes(16)
    client.udid_str = "00000000-0000-0000-0000-000000000000"
    client.viewer_id = 1
    client.app_ver = "1.0.0"
    client.res_ver = "1"
    client.session = SerialPostSession()
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client.current_scenario_id = None
    client.api_jitter = 0
    client.api_log = lambda *args, **kwargs: None
    client.common = lambda: {"viewer_id": 1}
    client.auth_bytes = lambda: b""
    client._note_api_error = lambda *args, **kwargs: None

    packed_sids = []
    unpack_count = 0
    unpack_lock = threading.Lock()

    def fake_pack(sid, *args, **kwargs):
        packed_sids.append(sid)
        return b"request-body"

    def fake_unpack(text, udid):
        nonlocal unpack_count
        with unpack_lock:
            unpack_count += 1
            sid = f"server-sid-{unpack_count}"
        return {"data_headers": {"result_code": 1, "sid": sid}, "data": {}}

    monkeypatch.setattr(client_module, "pack", fake_pack)
    monkeypatch.setattr(client_module, "get_raw_udid", lambda udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack", fake_unpack)
    monkeypatch.setattr(client_module, "dna_sleep", lambda *a, **k: None)

    barrier = threading.Barrier(3)
    errors = []

    def worker():
        try:
            barrier.wait()
            client.call("single_mode_free/load", {})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert hasattr(client, "_call_lock")
    assert client.session.max_active == 1
    assert packed_sids[0] == bytes(16)
    assert packed_sids[1] == next_sid("server-sid-1")


def test_circuit_breaker_ignores_recovery_and_skill_errors(monkeypatch):
    # A transient session-desync burst produces a mix of: gameplay 201s, the
    # recovery reload's load-201 (same desync, re-probed), and optional gain_skills
    # 201s. Counting load + gain_skills double-counts one desync and kills careers
    # the bot would otherwise recover. They must NOT trip the breaker; real gameplay
    # endpoints still must.
    import collections
    import uma_api.client as client_module
    from uma_api.client import UmaClient, CIRCUIT_ERROR_THRESHOLD

    def make_client():
        c = UmaClient.__new__(UmaClient)
        c.sid = bytes(16)
        c.udid_str = "00000000-0000-0000-0000-000000000000"
        c.viewer_id = 1
        c.app_ver = "1.0.0"
        c.res_ver = "1"
        c.session = type("S", (), {"post": lambda self, *a, **k: DummyResponse()})()
        c.tp_info = {}
        c.coin_info = {}
        c.item_map = {}
        c.current_scenario_id = None
        c.api_jitter = 0
        c.api_log = lambda *a, **k: None
        c.common = lambda: {"viewer_id": 1}
        c.auth_bytes = lambda: b""
        c.circuit_tripped = False
        c._err_window = collections.deque()
        c._call_lock = threading.RLock()
        return c

    monkeypatch.setattr(client_module, "pack", lambda *a, **k: b"body")
    monkeypatch.setattr(client_module, "get_raw_udid", lambda udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack",
                        lambda text, udid: {"data_headers": {"result_code": 201}, "data": {}})
    monkeypatch.setattr(client_module, "dna_sleep", lambda *a, **k: None)

    n = CIRCUIT_ERROR_THRESHOLD + 2

    # Recovery reload + optional skill buy 201s: never trip the breaker.
    c1 = make_client()
    for _ in range(n):
        for ep in ("single_mode_free/load", "single_mode_free/gain_skills"):
            try:
                c1.call(ep, {})
            except Exception:
                pass
    assert c1.circuit_tripped is False

    # A real gameplay endpoint 201ing still trips it (safety net preserved).
    c2 = make_client()
    for _ in range(n):
        try:
            c2.call("single_mode_free/exec_command", {})
        except Exception:
            pass
    assert c2.circuit_tripped is True


def test_gain_skills_208_raises_for_resync_not_silent(monkeypatch):
    # A 208 ("server busy") on gain_skills/multi_item carries no sid, so silently
    # continuing ("return res") desyncs the SID chain -> 201 burst on the next call.
    # It must RAISE a recoverable "208" (caller relogins/re-syncs) and must NOT count
    # toward the circuit breaker.
    import collections
    import pytest
    import uma_api.client as client_module
    from uma_api.client import UmaClient

    c = UmaClient.__new__(UmaClient)
    c.sid = bytes(16)
    c.udid_str = "00000000-0000-0000-0000-000000000000"
    c.viewer_id = 1
    c.app_ver = "1.0.0"
    c.res_ver = "1"
    c.session = type("S", (), {"post": lambda self, *a, **k: DummyResponse()})()
    c.tp_info = {}
    c.coin_info = {}
    c.item_map = {}
    c.current_scenario_id = None
    c.api_jitter = 0
    c.api_log = lambda *a, **k: None
    c.common = lambda: {"viewer_id": 1}
    c.auth_bytes = lambda: b""
    c.circuit_tripped = False
    c._err_window = collections.deque()
    c._call_lock = threading.RLock()

    monkeypatch.setattr(client_module, "pack", lambda *a, **k: b"body")
    monkeypatch.setattr(client_module, "get_raw_udid", lambda udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack",
                        lambda text, udid: {"data_headers": {"result_code": 208}, "data": {}})
    monkeypatch.setattr(client_module, "dna_sleep", lambda *a, **k: None)

    for ep in ("single_mode_free/gain_skills",
               "single_mode_free/multi_item_exchange",
               "single_mode_free/multi_item_use"):
        with pytest.raises(Exception) as ei:
            c.call(ep, {})
        assert "208" in str(ei.value)
    assert c.circuit_tripped is False
