import base64
import builtins
import inspect
import uuid

import pytest

from uma_api import bootstrap
from uma_api.bootstrap import BootstrapState, bootstrap_steam_account, has_game_auth_config


class RecordingPacingPolicy:
    def __init__(self, events):
        self.events = events

    def jittered_sleep(self, seconds):
        self.events.append(("pace", seconds))


class FakeClient:
    def __init__(self, cfg, signup_response, pre_signup_response, events):
        self.initial_cfg = dict(cfg)
        self.viewer_id = cfg["viewer_id"]
        self.udid_str = cfg["udid"]
        self.auth_key_hex = cfg.get("auth_key", "")
        self.steam_id = cfg["steam_id"]
        self.steam_ticket = cfg["steam_session_ticket"]
        self.signup_response = signup_response
        self.pre_signup_response = pre_signup_response
        self.events = events
        self.calls = []
        self.pacing_policy = RecordingPacingPolicy(events)

    def regen_sid(self):
        self.events.append(("regen_sid", None))

    def common(self):
        return {
            "viewer_id": self.viewer_id,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
        }

    def call(self, endpoint, args=None, **kwargs):
        payload = dict(args or {})
        payload.update(self.common())
        self.calls.append((endpoint, payload, kwargs))
        self.events.append(("call", endpoint))
        if endpoint == "tool/pre_signup":
            return self.pre_signup_response
        if endpoint == "tool/signup":
            return self.signup_response
        raise AssertionError(endpoint)

    def auth_config_snapshot(self):
        return {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
        }


def pre_signup_response(
    *, enable_steam_account=True, attest=False, nonce="", country_list=None,
):
    return {
        "data_headers": {"result_code": 1, "viewer_id": 0},
        "data": {
            "enable_steam_account": enable_steam_account,
            "attest": attest,
            "nonce": nonce,
            "country_list": country_list if country_list is not None else ["CA"],
        },
    }


def make_factory(signup_response, events, made, pre_signup=None):
    def factory(cfg, trace_enabled=True):
        client = FakeClient(
            cfg,
            signup_response,
            pre_signup or pre_signup_response(),
            events,
        )
        made.append((client, trace_enabled))
        return client
    return factory


def successful_response():
    return {
        "data_headers": {"result_code": 1, "viewer_id": 123456789},
        "data": {
            "auth_key": base64.b64encode(b"\xab" * 48).decode("ascii"),
        },
    }


def test_bootstrap_generates_exactly_one_fresh_lowercase_udid_with_zero_viewer(monkeypatch):
    generated = []
    fixed = uuid.UUID("ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF")

    def one_uuid():
        generated.append(fixed)
        return fixed

    monkeypatch.setattr(bootstrap.uuid, "uuid4", one_uuid)
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="76561198000000000",
        steam_session_ticket="ticket",
        trace_enabled=False,
        client_factory=make_factory(successful_response(), events, made),
    )

    client, trace_enabled = made[0]
    assert generated == [fixed]
    assert client.initial_cfg["viewer_id"] == 0
    assert client.initial_cfg["udid"] == str(fixed).lower()
    assert result.config["udid"] == str(fixed).lower()
    assert trace_enabled is False


def test_bootstrap_reuses_explicit_udid_without_generating_another(monkeypatch):
    monkeypatch.setattr(
        bootstrap.uuid,
        "uuid4",
        lambda: pytest.fail("an explicit staged udid must be reused"),
    )
    events = []
    made = []
    staged_udid = "00000000-0000-0000-0000-000000000099"

    result = bootstrap_steam_account(
        steam_id="76561198000000000",
        steam_session_ticket="ticket",
        udid=staged_udid,
        client_factory=make_factory(successful_response(), events, made),
    )

    assert made[0][0].initial_cfg["udid"] == staged_udid
    assert result.config["udid"] == staged_udid


def test_steam_identity_is_in_both_merged_signup_payloads_and_pacing_is_between_calls():
    events = []
    made = []

    bootstrap_steam_account(
        steam_id="76561198000000000",
        steam_session_ticket="short-lived-ticket",
        client_factory=make_factory(successful_response(), events, made),
    )

    client, _trace_enabled = made[0]
    assert [endpoint for endpoint, _payload, _kwargs in client.calls] == [
        "tool/pre_signup",
        "tool/signup",
    ]
    for _endpoint, payload, _kwargs in client.calls:
        assert payload["steam_id"] == "76561198000000000"
        assert payload["steam_session_ticket"] == "short-lived-ticket"
    assert events == [
        ("regen_sid", None),
        ("call", "tool/pre_signup"),
        ("pace", 0.83),
        ("regen_sid", None),
        ("call", "tool/signup"),
    ]


def test_signup_step_pause_is_pacing_not_retry():
    events = []
    made = []

    bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(successful_response(), events, made),
    )

    assert ("pace", 0.83) in events


def test_response_with_data_headers_viewer_and_48_byte_key_is_authenticated():
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(successful_response(), events, made),
    )

    assert result.state is BootstrapState.AUTHENTICATED
    assert result.client.viewer_id == 123456789
    assert result.client.auth_key_hex == "ab" * 48
    assert result.config["auth_key"] == "ab" * 48
    assert result.signup_response == successful_response()


def test_response_with_data_only_viewer_and_48_byte_key_is_authenticated():
    response = successful_response()
    response["data_headers"].pop("viewer_id")
    response["data"]["viewer_id"] = 123456789
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(response, events, made),
    )

    assert result.state is BootstrapState.AUTHENTICATED
    assert result.client.viewer_id == 123456789


@pytest.mark.parametrize("viewer_id", [None, True, 0, -1, "123456789"])
def test_invalid_or_absent_signup_viewer_id_needs_transition_link(viewer_id):
    response = successful_response()
    if viewer_id is None:
        response["data_headers"].pop("viewer_id")
    else:
        response["data_headers"]["viewer_id"] = viewer_id
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(response, events, made),
    )

    assert result.state is BootstrapState.NEEDS_TRANSITION_LINK
    assert result.client.viewer_id == 0


def test_signup_auth_key_that_is_not_48_bytes_needs_transition_link():
    response = successful_response()
    response["data"]["auth_key"] = base64.b64encode(b"short").decode("ascii")
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(response, events, made),
    )

    assert result.state is BootstrapState.NEEDS_TRANSITION_LINK


def test_pre_signup_fields_are_captured_on_result():
    response = successful_response()
    pre_signup = pre_signup_response(
        attest=True,
        nonce="nonce-value",
        country_list=["CA", "US"],
    )
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(response, events, made, pre_signup),
    )

    assert result.pre_signup_response == pre_signup
    assert result.enable_steam_account is True
    assert result.attest is True
    assert result.nonce == "nonce-value"


def test_disabled_steam_signup_skips_tool_signup():
    response = successful_response()
    pre_signup = pre_signup_response(enable_steam_account=False)
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(response, events, made, pre_signup),
    )

    assert result.state is BootstrapState.STEAM_SIGNUP_DISABLED
    assert result.signup_response is None
    assert [endpoint for endpoint, _payload, _kwargs in made[0][0].calls] == [
        "tool/pre_signup",
    ]


def test_pre_signup_only_mode_skips_tool_signup():
    events = []
    made = []

    result = bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        perform_signup=False,
        client_factory=make_factory(successful_response(), events, made),
    )

    assert result.state is BootstrapState.PRE_SIGNUP_COMPLETE
    assert result.signup_response is None
    assert [endpoint for endpoint, _payload, _kwargs in made[0][0].calls] == [
        "tool/pre_signup",
    ]


@pytest.mark.parametrize("cfg, expected", [
    ({"viewer_id": 1, "udid": "u", "auth_key": "ab" * 48}, True),
    ({"viewer_id": 0, "udid": "u", "auth_key": "ab" * 48}, False),
    ({"viewer_id": 1, "udid": "", "auth_key": "ab" * 48}, False),
    ({"viewer_id": 1, "udid": "u", "auth_key": "ab" * 47}, False),
    ({"viewer_id": 1, "udid": "u", "auth_key": "not-hex"}, False),
])
def test_has_game_auth_config_validates_only_game_auth_fields(cfg, expected):
    cfg = dict(cfg, steam_id="", steam_session_ticket="")
    assert has_game_auth_config(cfg) is expected


def test_bootstrap_never_starts_session_writes_files_or_imports_backend(monkeypatch):
    source = inspect.getsource(bootstrap)
    assert "backend" not in source
    events = []
    made = []
    real_open = builtins.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError("bootstrap must not write files")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", read_only_open)

    bootstrap_steam_account(
        steam_id="steam",
        steam_session_ticket="ticket",
        client_factory=make_factory(successful_response(), events, made),
    )

    endpoints = [endpoint for endpoint, _payload, _kwargs in made[0][0].calls]
    assert "tool/start_session" not in endpoints
    assert "load/index" not in endpoints
