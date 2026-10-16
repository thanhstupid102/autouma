import base64
import json
import struct
from types import SimpleNamespace

import msgpack
import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

import uma_api.client as client
from uma_api.crypto import make_md5_hex


def test_sm5_golden_value():
    assert client.sm5(b"abc").hex() == "1b911c5d874504d330807d5073f37eb1"


def test_make_md5_hex_live_client_golden_values():
    assert make_md5_hex("NhatP0nCay0K") == "48715bd20f972e70b24157f94b6a4126"
    assert make_md5_hex(
        "229594617236fad20319-81da-4234-8154-8d43a84fd3c5",
    ) == "8464c6b15ce1a3bf9f66d3711b27f104"


def test_make_sid_golden_values():
    assert client.make_sid(
        123456789,
        "00112233445566778899aabbccddeeff",
    ).hex() == "f6077c5e96488d0928cad9bd27854f01"
    assert client.make_sid(
        "viewer-42",
        "00112233-4455-6677-8899-aabbccddeeff",
    ).hex() == "014ec54af20415a24970f79871ca180d"


def test_next_sid_golden_values():
    assert client.next_sid("deadbeef").hex() == "2370a71f862f4d5465f79dca2a2f9beb"
    assert client.next_sid("0123456789abcdef").hex() == "3d66a9ee1ecfed1f57155dd94b3965b9"


def test_udid_derivation_golden_values():
    assert client.get_iv("00112233445566778899aabbccddeeff") == b"0011223344556677"
    assert client.get_iv("AABBCCDDEEFF00112233445566778899") == b"aabbccddeeff0011"
    assert client.get_raw_udid("00112233-4455-6677-8899-aabbccddeeff") == bytes.fromhex(
        "00112233445566778899aabbccddeeff"
    )
    assert client.get_raw_udid("AABBCCDDEEFF00112233445566778899") == bytes.fromhex(
        "aabbccddeeff00112233445566778899"
    )


REQUEST_UDID = "00112233-4455-6677-8899-aabbccddeeff"
REQUEST_SID = bytes.fromhex("10" * 16)
REQUEST_UDID_RAW = client.get_raw_udid(REQUEST_UDID)
REQUEST_AUTH = bytes.fromhex("20" * 16)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nested": {"empty": {}, "values": [1, 2, 3]}},
        ["list", {"unicode": "うま娘"}, [True, False, None]],
        {"unicode": "こんにちは世界", "ints": [0, -1, 2**40]},
    ],
)
def test_unpack_request_round_trip(payload):
    encoded = client.pack(
        REQUEST_SID,
        REQUEST_UDID_RAW,
        REQUEST_AUTH,
        payload,
        REQUEST_UDID,
    )

    assert client.unpack_request(encoded, REQUEST_UDID) == payload


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nested": {"empty": {}, "values": [1, 2, 3]}},
        ["list", {"unicode": "うま娘"}, [True, False, None]],
        {"unicode": "こんにちは世界", "ints": [0, -1, 2**40]},
    ],
)
def test_unpack_response_round_trip(payload):
    udid = "AABBCCDDEEFF00112233445566778899"
    key = b"0123456789abcdef0123456789abcdef"
    packed = msgpack.packb(payload, use_bin_type=True)
    body = AES.new(key, AES.MODE_CBC, client.get_iv(udid)).encrypt(
        pad(struct.pack("<I", len(packed)) + packed, 16)
    ) + key

    assert client.unpack(base64.b64encode(body), udid) == payload


def test_apply_race_out_click_payload_structure():
    fake = SimpleNamespace(viewer_id=123456789, current_scenario_id=4)
    payload = {}

    client.UmaClient._apply_race_out_click_payload(fake, payload)

    button_info = json.loads(payload["button_info"])
    assert set(button_info) == {
        "ViewerId",
        "DeviceId",
        "ScenarioId",
        "ClickPosX",
        "ClickPosY",
        "ClickServerTime",
    }
    assert all(type(button_info[key]) is int for key in button_info)
