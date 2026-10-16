import pytest

from uma_api import client as client_module
from uma_api.client import UmaClient
from uma_api.errors import GameAuthRequiredError


class Session:
    def __init__(self):
        self.headers = {}

    def close(self):
        pass


def bare_client(*, authenticated):
    client = UmaClient.__new__(UmaClient)
    client.viewer_id = 123456789 if authenticated else 0
    client.udid_str = "00000000-0000-4000-8000-000000000000"
    client.auth_key_hex = "ab" * 48 if authenticated else ""
    client.steam_id = ""
    client.steam_ticket = ""
    client.session = Session()
    client.regen_sid = lambda: None
    client.refresh_cached_account_state = lambda data: None
    return client


def test_login_without_game_auth_raises_typed_error_and_makes_no_wire_call():
    client = bare_client(authenticated=False)
    calls = []
    client.call = lambda *args, **kwargs: calls.append((args, kwargs))

    with pytest.raises(GameAuthRequiredError):
        client.login()

    assert calls == []


def test_login_with_game_auth_calls_start_session_then_load_index(monkeypatch):
    client = bare_client(authenticated=True)
    calls = []

    def call(endpoint, args=None):
        calls.append((endpoint, args))
        return {"data_headers": {"result_code": 1}, "data": {}}

    client.call = call
    monkeypatch.setattr(client_module.requests, "Session", Session)

    client.login(max_retries=0)

    assert calls == [
        ("tool/start_session", {"attestation_type": 0, "device_token": None}),
        ("load/index", {"adid": ""}),
    ]


def test_login_has_no_signup_path():
    assert not hasattr(UmaClient, "signup")
    assert "tool/signup" not in UmaClient.login.__code__.co_consts
