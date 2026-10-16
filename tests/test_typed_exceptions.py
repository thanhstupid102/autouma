"""§12.6 typed exceptions: attributes on the wire errors + ONE HTTP translation.

Two independent halves, both written as EQUIVALENCE proofs rather than as new
expectations, because the slice's whole contract is "nothing observable moves":

1. ``uma_api``. ``ClientVersionError`` / ``AuthInvalidatedError`` are now
   ``ApiError`` subclasses that carry ``result_code`` + ``endpoint`` as real
   attributes instead of leaving every caller to regex the message. The tests
   below pin, for every result code the ladder can produce, that
   ``api_error_result_code`` returns exactly what it returned when the only
   information available was the message string -- so no recovery ladder can
   branch differently than it did before.

2. ``backend``. ``BotConfigValidationError`` is translated to the HTTP envelope
   once, by an app-level handler, instead of by three copies of the same
   ``except``/``raise HTTPException`` pair in ``bot_config/controllers.py``. The
   tests pin the response BYTES (status + body + content-type), and pin that the
   handler is narrow: a ``RuntimeError`` -- or even a plain ``ValueError``, which
   ``BotConfigValidationError`` subclasses -- must still propagate as a server
   error rather than being laundered into a tidy 400.
"""
import os

os.environ.setdefault("SWEEPY_SKIP_STARTUP_GEN", "1")

import pytest
from fastapi.testclient import TestClient

from career_bot.bot_config import BotConfigValidationError
from career_bot.bot_config.store import BotConfigStore
from uma_api import update_guard as _update_guard
from uma_api.errors import ApiError, api_error_result_code
from backend.app.app import create_app

from test_client_retry_ladder import make_client, res


# Every code the ladder classifies or a recovery site branches on, plus the
# ones only seen in career-start (2509/501/1052) and the generic fallthrough.
LADDER_CODES = (
    1, 101, 102, 201, 202, 203, 204, 205, 208, 209, 213, 214, 217,
    394, 500, 501, 703, 709, 1052, 1503, 2509,
)
ENDPOINTS = ("single_mode_free/start", "tool/start_session", "single_mode_free/race_end")
GUARD_TYPES = (_update_guard.ClientVersionError, _update_guard.AuthInvalidatedError)


def _client_message(rc, ep):
    """The exact string ``_call_locked`` builds before raising a guard error."""
    _diagnosis, remedy = _update_guard.classify_result_code(rc)
    remedy = remedy.format(account="tester") if "{account}" in remedy else remedy
    return f"API error {rc} on {ep}: detail-{rc} {remedy}"


# --------------------------------------------------------------------------- #
# 1. uma_api -- classification is unchanged
# --------------------------------------------------------------------------- #

def test_guard_errors_are_typed_api_errors():
    for guard in GUARD_TYPES:
        assert issubclass(guard, ApiError)
        assert issubclass(guard, Exception)
    assert _update_guard.ClientVersionError is not _update_guard.AuthInvalidatedError


def test_attribute_classification_agrees_with_the_legacy_message_parse():
    """The core equivalence: for every (code, endpoint) the ladder can raise,
    reading ``.result_code`` off the typed error gives the same answer as
    regex-parsing the identical message off an untyped ``Exception``."""
    checked = 0
    for rc in LADDER_CODES:
        for ep in ENDPOINTS:
            message = _client_message(rc, ep)
            legacy = api_error_result_code(Exception(message))
            assert legacy == rc, (rc, ep, legacy)
            for guard in GUARD_TYPES:
                typed = guard(message, result_code=rc, endpoint=ep)
                assert api_error_result_code(typed) == legacy
                assert typed.result_code == rc
                assert typed.endpoint == ep
                assert str(typed) == message
                checked += 1
    assert checked == len(LADDER_CODES) * len(ENDPOINTS) * len(GUARD_TYPES)


def test_message_only_construction_still_falls_back_to_the_regex():
    """Foreign/older call sites build these with just a message. They must keep
    resolving through the string, and must not invent a code."""
    for guard in GUARD_TYPES:
        legacy = guard("API error 202")
        assert legacy.result_code is None and legacy.endpoint is None
        assert api_error_result_code(legacy) == 202
        assert str(legacy) == "API error 202"

        codeless = guard("no result code in here")
        assert api_error_result_code(codeless) is None


def test_attribute_wins_over_a_disagreeing_message():
    """Teeth for 'prefers the attribute': if the two sources disagree, the
    structured value is the one that is used."""
    typed = _update_guard.AuthInvalidatedError(
        "API error 999 on ep: stale text", result_code=203, endpoint="ep",
    )
    assert api_error_result_code(typed) == 203
    assert api_error_result_code(Exception(str(typed))) == 999


# --------------------------------------------------------------------------- #
# 1b. the same, end to end through _call_locked
# --------------------------------------------------------------------------- #

def test_call_locked_client_version_error_carries_code_and_endpoint(monkeypatch):
    c, _rec = make_client(
        monkeypatch,
        [res(204), res(204)],
        app_ver="1.0.0",
        app_ver_fresh=None,
    )
    with pytest.raises(_update_guard.ClientVersionError) as ei:
        c.call("load/index", {})
    assert ei.value.result_code == 204
    assert ei.value.endpoint == "load/index"
    assert api_error_result_code(ei.value) == 204
    # message text untouched: still the historical "API error <rc> on <ep>: ..."
    assert str(ei.value).startswith("API error 204 on load/index: ")


def test_call_locked_auth_invalidated_error_carries_code_and_endpoint(monkeypatch):
    c, _rec = make_client(monkeypatch, [res(203)])
    with pytest.raises(_update_guard.AuthInvalidatedError) as ei:
        c.call("single_mode_free/exec_command", {})
    assert ei.value.result_code == 203
    assert ei.value.endpoint == "single_mode_free/exec_command"
    assert str(ei.value).startswith("API error 203 on single_mode_free/exec_command: ")


def test_call_locked_reregistration_102_reports_the_real_102(monkeypatch):
    """A 102 + mismatched viewer is re-classified as AUTH_INVALIDATED for the
    remedy text, but the carried result_code stays the code the SERVER sent --
    which is what the 102-sensitive ladders (`api_error_result_code(e) == 102`)
    have always seen via the message."""
    c, _rec = make_client(monkeypatch, [res(102, viewer_id=999)], viewer_id=123)
    with pytest.raises(_update_guard.AuthInvalidatedError) as ei:
        c.call("single_mode_free/exec_command", {})
    assert ei.value.result_code == 102
    assert api_error_result_code(Exception(str(ei.value))) == 102


# --------------------------------------------------------------------------- #
# 2. backend -- one translation, byte-identical envelope
# --------------------------------------------------------------------------- #

FORCED_DETAIL = "scenarios.2: Unknown field(s) at scenarios.2: bad"
FORCED_BODY = b'{"detail":"scenarios.2: Unknown field(s) at scenarios.2: bad"}'
REAL_BODY = b'{"detail":"Unknown field(s) at scenarios.2: bad"}'


@pytest.fixture
def bot_config_client(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        yield app, client


def _boom(self, *args, **kwargs):
    raise BotConfigValidationError(FORCED_DETAIL)


@pytest.mark.parametrize(
    "store_method, request_call",
    [
        ("response", lambda c: c.get("/api/bot-config")),
        ("write_active", lambda c: c.post("/api/bot-config", json={"config": {}})),
        ("reset_active", lambda c: c.post("/api/bot-config/reset")),
    ],
)
def test_every_bot_config_route_renders_the_same_400_bytes(
    bot_config_client, monkeypatch, store_method, request_call,
):
    _app, client = bot_config_client
    monkeypatch.setattr(BotConfigStore, store_method, _boom)
    resp = request_call(client)
    assert resp.status_code == 400
    assert resp.content == FORCED_BODY
    assert resp.headers["content-type"] == "application/json"


def test_posting_an_invalid_config_returns_the_validator_message(bot_config_client):
    """The unforced path: a real rejected payload, not a patched store."""
    _app, client = bot_config_client
    resp = client.post(
        "/api/bot-config", json={"config": {"scenarios": {"2": {"bad": 1}}}},
    )
    assert resp.status_code == 400
    assert resp.content == REAL_BODY


def test_a_corrupt_stored_config_returns_400_on_get(bot_config_client):
    """`read_active()` raising is the only way the GET route can 400, and it is
    the reason its (now removed) local `except` existed."""
    app, client = bot_config_client
    store = app.state.ctx.bot_config_store
    store.ensure()
    store.active_path.write_text('{"scenarios": {"2": {"bad": 1}}}', encoding="utf-8")
    resp = client.get("/api/bot-config")
    assert resp.status_code == 400
    assert resp.content == REAL_BODY


def test_success_paths_are_untouched(bot_config_client):
    _app, client = bot_config_client
    ok = client.get("/api/bot-config")
    assert ok.status_code == 200
    assert sorted(ok.json()) == [
        "config", "default_config", "fields", "scenarios", "success",
    ]
    assert client.post("/api/bot-config/reset").status_code == 200


@pytest.mark.parametrize("boom_type", [RuntimeError, ValueError, KeyError])
def test_the_handler_does_not_launder_other_exceptions(
    bot_config_client, monkeypatch, boom_type,
):
    """Narrowness guard. `BotConfigValidationError` subclasses `ValueError`, so a
    handler registered one level too high would swallow every ValueError in the
    app into a 400. These must still surface as server errors."""
    _app, client = bot_config_client

    def raiser(self, *args, **kwargs):
        raise boom_type("not a bot-config validation failure")

    monkeypatch.setattr(BotConfigStore, "response", raiser)
    with pytest.raises(boom_type):
        client.get("/api/bot-config")


def test_translation_is_registered_once_at_the_app_level(tmp_path):
    from backend.app.exception_handlers import bot_config_validation_error_handler

    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    assert app.exception_handlers[BotConfigValidationError] is (
        bot_config_validation_error_handler
    )


def test_controllers_no_longer_translate_the_domain_error():
    """The point of the slice: the duplicated translation is gone, not moved."""
    from backend.app.routers.bot_config import controllers

    source = open(controllers.__file__, encoding="utf-8").read()
    assert "except BotConfigValidationError" not in source
    assert "HTTPException" not in source.split("# A `BotConfigValidationError`")[0]
