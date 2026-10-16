import threading

import pytest

from career_bot.engine import CareerRunner
from uma_api.client import UmaClient
from uma_api.routes import derive_exchange_get_list_time


@pytest.mark.parametrize(
    ("servertime", "expected"),
    [
        (1784044193, "2026/07/14 15:49:53"),
        (1784044231, "2026/07/14 15:50:31"),
        (1784044242, "2026/07/14 15:50:42"),
        (1784044360, "2026/07/14 15:52:40"),
    ],
)
def test_exchange_get_list_time_uses_show_exchange_servertime(servertime, expected):
    response = {"data_headers": {"servertime": servertime}}

    assert derive_exchange_get_list_time(response) == expected


def test_exchange_item_sends_exact_wire_payload_in_order():
    client = UmaClient.__new__(UmaClient)
    calls = []
    client.call = lambda endpoint, payload: calls.append((endpoint, payload)) or {"data": {}}

    client.exchange_item(9001, 1, 123, "2026/07/14 15:49:53")

    endpoint, payload = calls[0]
    assert endpoint == "item/exchange"
    assert list(payload) == ["exchange_id", "count", "current_num", "get_list_time"]
    assert payload == {
        "exchange_id": 9001,
        "count": 1,
        "current_num": 123,
        "get_list_time": "2026/07/14 15:49:53",
    }


def test_alarm_clock_price_uses_master_exchange_row(monkeypatch, tmp_path):
    import uma_data

    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    monkeypatch.setattr(
        uma_data,
        "configured_master_mdb_path",
        lambda *_args, **_kwargs: tmp_path / "master.mdb",
    )
    monkeypatch.setattr(
        uma_data,
        "load_item_exchange",
        lambda *_args, **_kwargs: {
            "change_item_id": 95,
            "change_item_num": 1,
            "pay_item_id": 43,
            "pay_item_num": 12,
        },
    )

    assert client.alarm_clock_carat_price() == 12


def test_buy_alarm_clock_uses_refreshed_carat_balance_and_merges_response(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {"fcoin": 90, "coin": 10}
    client.item_map = {95: 0}
    calls = []

    def fake_call(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint == "load/index":
            return {
                "data": {
                    "coin_info": {"fcoin": 4, "coin": 18},
                    "user_item": {"item_id": 95, "num": 0},
                }
            }
        if endpoint == "item/show_exchange":
            return {"data_headers": {"servertime": 1784044193}, "data": {}}
        if endpoint == "item/exchange":
            return {
                "data": {
                    "coin_info": {"fcoin": 4, "coin": 8},
                    "reward_summary_info": {
                        "add_item_list": [{"item_id": 95, "number": 1}],
                    },
                    "use_item_info": {"item_id": 43, "number": 10},
                }
            }
        raise AssertionError(endpoint)

    client.call = fake_call

    client.buy_alarm_clock()

    assert [endpoint for endpoint, _payload in calls] == [
        "load/index",
        "item/show_exchange",
        "item/exchange",
    ]
    exchange_payload = calls[-1][1]
    assert exchange_payload["current_num"] == 22
    assert exchange_payload["get_list_time"] == "2026/07/14 15:49:53"
    assert client.coin_info == {"fcoin": 4, "coin": 8}
    assert client.item_map[95] == 1


@pytest.mark.parametrize(
    ("starting_items", "load_items", "expected_count"),
    [
        ({}, None, None),
        ({95: 4}, {"item_id": 95, "num": 4}, 5),
    ],
)
def test_buy_alarm_clock_delta_preserves_unknown_and_increments_known_count(
    tmp_path,
    starting_items,
    load_items,
    expected_count,
):
    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = dict(starting_items)

    def fake_call(endpoint, _payload):
        if endpoint == "load/index":
            data = {"coin_info": {"fcoin": 20, "coin": 0}}
            if load_items is not None:
                data["user_item"] = load_items
            return {"data": data}
        if endpoint == "item/show_exchange":
            return {"data_headers": {"servertime": 1784044193}, "data": {}}
        if endpoint == "item/exchange":
            return {
                "data": {
                    "coin_info": {"fcoin": 10, "coin": 0},
                    "reward_summary_info": {
                        "add_item_list": [{"item_id": 95, "number": 1}],
                    },
                    "use_item_info": {"item_id": 43, "number": 10},
                }
            }
        raise AssertionError(endpoint)

    client.call = fake_call

    client.buy_alarm_clock()

    if expected_count is None:
        assert 95 not in client.item_map
    else:
        assert client.item_map[95] == expected_count


def test_buy_alarm_clock_explicit_item_count_wins_over_delta(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {95: 4}

    def fake_call(endpoint, _payload):
        if endpoint == "load/index":
            return {
                "data": {
                    "coin_info": {"fcoin": 20, "coin": 0},
                    "user_item": {"item_id": 95, "num": 4},
                }
            }
        if endpoint == "item/show_exchange":
            return {"data_headers": {"servertime": 1784044193}, "data": {}}
        if endpoint == "item/exchange":
            return {
                "data": {
                    "coin_info": {"fcoin": 10, "coin": 0},
                    "user_item": {"item_id": 95, "num": 7},
                }
            }
        raise AssertionError(endpoint)

    client.call = fake_call

    client.buy_alarm_clock()

    assert client.item_map[95] == 7


def test_buy_alarm_clock_holds_reentrant_call_lock_for_transaction(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {95: 0}
    client._call_lock = threading.RLock()
    calls = []

    def fake_call(endpoint, _payload):
        assert client._call_lock._is_owned()
        calls.append(endpoint)
        if endpoint == "load/index":
            return {
                "data": {
                    "coin_info": {"fcoin": 20, "coin": 0},
                    "user_item": {"item_id": 95, "num": 0},
                }
            }
        if endpoint == "item/show_exchange":
            return {"data_headers": {"servertime": 1784044193}, "data": {}}
        if endpoint == "item/exchange":
            return {
                "data": {
                    "coin_info": {"fcoin": 10, "coin": 0},
                    "reward_summary_info": {
                        "add_item_list": [{"item_id": 95, "number": 1}],
                    },
                }
            }
        raise AssertionError(endpoint)

    client.call = fake_call

    client.buy_alarm_clock()

    assert calls == ["load/index", "item/show_exchange", "item/exchange"]


def test_alarm_clock_preflight_and_purchase_load_index_once(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.state_root = tmp_path
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client._call_lock = threading.RLock()
    calls = []

    def fake_call(endpoint, _payload):
        calls.append(endpoint)
        if endpoint == "load/index":
            return {"data": {"coin_info": {"fcoin": 20, "coin": 0}}}
        if endpoint == "item/show_exchange":
            return {"data_headers": {"servertime": 1784044193}, "data": {}}
        if endpoint == "item/exchange":
            return {
                "data": {
                    "coin_info": {"fcoin": 10, "coin": 0},
                    "reward_summary_info": {
                        "add_item_list": [{"item_id": 95, "number": 1}],
                    },
                    "use_item_info": {"item_id": 43, "number": 10},
                }
            }
        raise AssertionError(endpoint)

    client.call = fake_call
    client.alarm_clock_carat_price = lambda: 10
    runner = CareerRunner(tmp_path)

    assert runner._ensure_alarm_clock(client, {}) is True
    assert calls.count("load/index") == 1
    assert calls == ["load/index", "item/show_exchange", "item/exchange"]
