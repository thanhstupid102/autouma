import base64

import pytest

from uma_api import client as client_module
from uma_api.client import UmaClient


class _Session:
    def __init__(self):
        self.headers = {}

    def close(self):
        pass


def _bare_client(auth_key_hex="aa" * 48):
    client = UmaClient.__new__(UmaClient)
    client.auth_key_hex = auth_key_hex
    return client


def test_start_session_adopts_attestation_fields_as_observable_state():
    client = _bare_client()

    rotated = client._adopt_start_session_response({
        "data": {"attest": True, "nonce": "server-nonce"},
    })

    assert rotated is False
    assert client.auth_key_rotated is False
    assert client.last_attest is True
    assert client.last_attest_nonce == "server-nonce"


def test_start_session_without_auth_key_keeps_existing_key():
    client = _bare_client("cd" * 48)

    rotated = client._adopt_start_session_response({
        "data": {"attest": False, "nonce": ""},
    })

    assert rotated is False
    assert client.auth_key_rotated is False
    assert client.auth_key_hex == "cd" * 48


def test_start_session_adopts_present_auth_key_as_lowercase_hex():
    client = _bare_client("cd" * 48)
    raw_auth_key = bytes(range(48))

    rotated = client._adopt_start_session_response({
        "data": {
            "attest": False,
            "nonce": "",
            "auth_key": base64.b64encode(raw_auth_key).decode("ascii"),
        },
    })

    assert rotated is True
    assert client.auth_key_rotated is True
    assert client.auth_key_hex == raw_auth_key.hex()


def test_start_session_reports_no_rotation_for_an_unchanged_auth_key():
    raw_auth_key = bytes(range(48))
    client = _bare_client(raw_auth_key.hex())

    rotated = client._adopt_start_session_response({
        "data": {"auth_key": base64.b64encode(raw_auth_key).decode("ascii")},
    })

    assert rotated is False
    assert client.auth_key_rotated is False
    assert client.auth_key_hex == raw_auth_key.hex()


@pytest.mark.parametrize("encoded_auth_key", ["", "not valid base64!"])
def test_start_session_invalid_or_empty_auth_key_keeps_existing_key(encoded_auth_key):
    client = _bare_client("cd" * 48)

    rotated = client._adopt_start_session_response({
        "data": {"auth_key": encoded_auth_key},
    })

    assert rotated is False
    assert client.auth_key_rotated is False
    assert client.auth_key_hex == "cd" * 48


@pytest.mark.parametrize("method_name", ["login", "hard_reset"])
def test_session_boot_methods_adopt_start_session_identity(
    monkeypatch, method_name,
):
    client = _bare_client("cd" * 48)
    client.session = _Session()
    client.viewer_id = 123456789
    client.has_game_auth = lambda: True
    client.regen_sid = lambda: None
    client.update_headers = lambda: None
    client.refresh_cached_account_state = lambda _data: None
    client._single_mode_ep = lambda endpoint: f"single_mode_free/{endpoint}"
    raw_auth_key = bytes(range(48))
    start_session_response = {
        "data_headers": {"result_code": 1},
        "data": {
            "attest": True,
            "nonce": "next-attestation-nonce",
            "auth_key": base64.b64encode(raw_auth_key).decode("ascii"),
        },
    }
    calls = []

    def call(endpoint, _args=None):
        calls.append(endpoint)
        if endpoint == "tool/start_session":
            return start_session_response
        if endpoint == "load/index":
            return {"data_headers": {"result_code": 1}, "data": {}}
        return {
            "data_headers": {"result_code": 1},
            "data": {"chara_info": {"scenario_id": 1}},
        }

    client.call = call
    monkeypatch.setattr(client_module.requests, "Session", _Session)

    if method_name == "login":
        client.login(max_retries=0)
    else:
        client.hard_reset()

    assert calls[0] == "tool/start_session"
    assert client.auth_key_hex == raw_auth_key.hex()
    assert client.auth_key_rotated is True
    assert client.last_attest is True
    assert client.last_attest_nonce == "next-attestation-nonce"
