"""Pins for the non-transport slices extracted out of ``UmaClient`` (§13.1 A17).

``UmaClient`` is a compatibility facade: scripts and tests import it *and* its
helpers, so the whole point of the extraction is that nothing about its surface
or its behaviour moved with the code. These tests pin the seams the move could
plausibly have broken -- and the retry core it must NOT have touched.
"""
import ctypes
import inspect
import json

import pytest

from uma_api import account_state, api_warehouse, diagnostics, identity, race_telemetry
from uma_api.client import UmaClient
from uma_api.routes import ApiRoutes


# --- facade parity ----------------------------------------------------------

# The full public+private surface UmaClient carried before the slices left it.
EXPECTED_SURFACE = [
    # transport core -- must still be defined by uma_api.client itself
    "call", "_call_locked", "hard_reset", "login", "auth_config_snapshot",
    "api_log", "_init_trace_log", "auth_bytes", "has_game_auth", "regen_sid",
    "common", "update_headers", "reset_circuit", "_note_api_error",
    "_refresh_resource_version", "_apply_race_out_click_payload",
    "bind_api_warehouse", "_store_api_response",
    "api_payload_summary", "safe_payload", "response_summary",
    "_find_item_rows", "_item_count", "refresh_cached_account_state",
    "recovery_tp", "use_recovery_item", "single_mode_use_tp",
    "_ITEM_LIST_KEYS", "_ITEM_COUNT_KEYS", "TP_BOTTLE_ITEM_ID",
    # endpoint families -- now inherited, still reachable on the facade
    "_single_mode_prefix", "_single_mode_ep", "_remember_scenario_from_data",
    "read_info", "set_trained_chara_lock", "remove_trained_chara",
    "factor_select", "factor_lottery", "finish_career", "load_career",
    "minigame_end", "pre_single_mode", "start_career", "exec_command",
    "check_event", "use_items", "exchange_items", "gain_skills",
    "race_entry", "race_start", "race_end", "race_out", "race_continue",
    "team_edit", "opponent_list", "team_race_analyze", "team_race_start",
    "team_race_end", "team_race_out", "team_race_continue", "reserve_race",
]


@pytest.mark.parametrize("name", EXPECTED_SURFACE)
def test_facade_still_exposes_every_member(name):
    assert hasattr(UmaClient, name)


def test_retry_core_did_not_leave_the_client():
    """B3 boundary: the retry ladder stays owned by uma_api.client."""
    for name in ("call", "_call_locked", "hard_reset", "login", "_note_api_error"):
        assert UmaClient.__dict__[name].__module__ == "uma_api.client"


def test_endpoint_families_resolve_through_the_routes_mixin():
    assert ApiRoutes in UmaClient.__mro__
    assert "race_out" not in UmaClient.__dict__
    assert UmaClient.race_out is ApiRoutes.race_out


def test_module_level_exports_survive_for_out_of_tree_importers():
    from uma_api import client as client_module

    # career_bot.engine.runner imports this name straight off uma_api.client.
    assert client_module.redact_for_console is diagnostics.redact_for_console
    assert client_module.format_api_error is diagnostics.format_api_error


def test_auth_config_snapshot_is_pure_and_replaces_the_old_save_global():
    from uma_api import client as client_module

    client = UmaClient.__new__(UmaClient)
    client.viewer_id = 42
    client.udid_str = "udid"
    client.auth_key_hex = "auth"
    client.steam_id = "steam"
    client.steam_ticket = "ticket"
    client.device_id = "device-id"
    client.device_name = "device-name"
    client.graphics_device = "gpu"
    client.ip_address = "10.0.0.1"
    client.platform_os = "Windows 11"

    expected = {
        "viewer_id": 42,
        "udid": "udid",
        "auth_key": "auth",
        "steam_id": "steam",
        "steam_session_ticket": "ticket",
        "device_id": "device-id",
        "device_name": "device-name",
        "graphics_device_name": "gpu",
        "ip_address": "10.0.0.1",
        "platform_os_version": "Windows 11",
    }
    assert client.auth_config_snapshot() == expected
    assert client.auth_config_snapshot() == expected
    assert not hasattr(client_module, "LAST_SAVED_CONFIG")


# --- identity synthesis -----------------------------------------------------

PROFILE = {
    "device_id": "derived-id",
    "device_name": "derived-name",
    "graphics_device_name": "derived-gpu",
    "ip_address": "10.0.0.1",
    "platform_os_version": "derived-os",
    "udid": "derived-udid",
}


def test_identity_prefers_explicit_config_over_everything():
    fields = identity.resolve_device_identity({"device_id": "explicit"}, PROFILE)
    assert fields["device_id"] == "explicit"
    assert fields["device_name"] == "derived-name"


def test_identity_prefers_captured_body_over_derived_hwid(monkeypatch):
    """The registered fingerprint is what keeps repeat friend borrows off 501."""
    monkeypatch.setattr(
        identity, "unpack_request",
        lambda body, udid: {"device_id": "registered-8d36ee", "device_name": "registered-name"},
    )
    fields = identity.resolve_device_identity({"body": "x", "udid": "y"}, PROFILE)
    assert fields["device_id"] == "registered-8d36ee"
    assert fields["device_name"] == "registered-name"
    # Fields the capture did not carry still fall back to the derived profile.
    assert fields["ip_address"] == "10.0.0.1"


def test_identity_falls_back_when_captured_body_cannot_be_decoded(monkeypatch):
    def boom(body, udid):
        raise ValueError("bad ciphertext")

    monkeypatch.setattr(identity, "unpack_request", boom)
    fields = identity.resolve_device_identity({"body": "x", "udid": "y"}, PROFILE)
    assert fields["device_id"] == "derived-id"


def test_common_payload_shape_is_the_wire_shape():
    payload = identity.common_payload(
        1, "did", "dname", "gpu", "1.2.3.4", "os", "JPN", "steam", "ticket",
    )
    assert list(payload) == [
        "viewer_id", "device", "device_id", "device_name", "graphics_device_name",
        "ip_address", "platform_os_version", "carrier", "keychain", "locale",
        "button_info", "dmm_viewer_id", "dmm_onetime_token", "steam_id",
        "steam_session_ticket",
    ]
    assert payload["device"] == 4
    assert payload["button_info"] == ""


def test_client_common_delegates_with_its_own_fields():
    client = UmaClient.__new__(UmaClient)
    client.viewer_id = 42
    client.device_id = "did"
    client.device_name = "dname"
    client.graphics_device = "gpu"
    client.ip_address = "1.2.3.4"
    client.platform_os = "os"
    client.locale = "JPN"
    client.steam_id = "steam"
    client.steam_ticket = "ticket"

    assert client.common() == identity.common_payload(
        42, "did", "dname", "gpu", "1.2.3.4", "os", "JPN", "steam", "ticket",
    )


def test_unity_headers_carry_the_version_twice():
    headers = identity.unity_headers("2022.3.62f2")
    assert headers["X-Unity-Version"] == "2022.3.62f2"
    assert headers["User-Agent"].startswith("UnityPlayer/2022.3.62f2 ")
    assert headers["Content-Type"] == "application/x-msgpack"


# --- account-state cache ----------------------------------------------------

class _Cache:
    def __init__(self):
        self.cached_load_data = {}
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}


def test_missing_item_row_means_unchanged_not_zero():
    """Server item arrays are PARTIAL deltas -- an absent row must not zero it."""
    cache = _Cache()
    cache.item_map[32] = 5
    account_state.refresh_account_state(cache, {"user_item_array": []})
    assert cache.item_map[32] == 5

    account_state.refresh_account_state(
        cache, {"user_item_array": [{"item_id": 32, "num": 2}]},
    )
    assert cache.item_map[32] == 2


def test_refresh_only_replaces_tp_and_coin_when_present():
    cache = _Cache()
    cache.tp_info = {"current_tp": 30}
    cache.coin_info = {"coin": 100}
    account_state.refresh_account_state(cache, {"something_else": 1})
    assert cache.tp_info == {"current_tp": 30}
    assert cache.coin_info == {"coin": 100}


def test_find_item_rows_accepts_every_known_carrier_key():
    for key in account_state.ITEM_LIST_KEYS:
        assert account_state.find_item_rows({key: [{"item_id": 1}]}) == [{"item_id": 1}]
    assert account_state.find_item_rows({"user_item": {"item_id": 1}}) == [{"item_id": 1}]
    assert account_state.find_item_rows({"user_item": "not-a-list"}) is None
    assert account_state.find_item_rows(None) is None


def test_singular_user_item_updates_cached_count():
    cache = _Cache()
    cache.item_map[95] = 1

    account_state.refresh_account_state(
        cache,
        {"user_item": {"item_id": 95, "num": 0}},
    )

    assert cache.item_map[95] == 0


def test_item_count_clamps_and_reports_absence():
    assert account_state.item_count({"num": -3}) == 0
    assert account_state.item_count({"current_num": 7}) == 7
    assert account_state.item_count({"item_id": 1}) is None


def test_rows_report_item_ignores_rows_without_a_count():
    rows = [{"item_id": 32}, {"item_id": 99, "num": 1}]
    assert account_state.rows_report_item(rows, 32) is False
    assert account_state.rows_report_item(rows, 99) is True
    assert account_state.rows_report_item(None, 32) is False


def test_client_delegators_honour_the_class_level_key_overrides():
    client = UmaClient.__new__(UmaClient)
    assert client._find_item_rows({"user_item_array": [{"item_id": 1, "num": 4}]})
    assert client._item_count({"item_num": 4}) == 4


# --- api warehouse binding --------------------------------------------------

def _response(result_code=1):
    return {"data_headers": {"result_code": result_code}, "data": {"ok": True}}


def test_warehouse_skips_unbound_client_and_failed_results(tmp_path):
    assert api_warehouse.store_success_response(None, "acct", "load/index", _response()) is None
    assert api_warehouse.store_success_response(
        tmp_path, "acct", "load/index", _response(result_code=205),
    ) is None
    assert api_warehouse.store_success_response(tmp_path, "acct", "load/index", "not-a-dict") is None


def test_warehouse_writes_a_successful_response(tmp_path):
    path = api_warehouse.store_success_response(tmp_path, "acct", "load/index", _response())
    assert path is not None and path.exists()
    assert api_warehouse.read_latest_data(tmp_path, "acct", "load/index") == {"ok": True}


def test_store_api_response_swallows_an_unbound_partial_client():
    """_call_locked calls this on clients built via __new__; it must never raise."""
    client = UmaClient.__new__(UmaClient)
    assert not hasattr(client, "api_warehouse_base_dir")
    assert client._store_api_response("load/index", _response()) is None


# --- race-out telemetry -----------------------------------------------------

def test_button_info_is_all_ints_and_inside_the_button():
    btn = race_telemetry.build_button_info(123456789, 4)
    assert list(btn) == [
        "ViewerId", "DeviceId", "ScenarioId",
        "ClickPosX", "ClickPosY", "ClickServerTime",
    ]
    assert all(type(v) is int for v in btn.values())
    assert btn["ViewerId"] == 123456789
    assert btn["ScenarioId"] == 4
    assert btn["DeviceId"] == 4


def test_race_out_button_info_is_identical_on_windows_and_linux(monkeypatch):
    monkeypatch.delenv(race_telemetry.SCREEN_HEIGHT_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        race_telemetry, "dna_gauss", lambda mean, _sigma: mean,
    )
    monkeypatch.setattr(race_telemetry, "dna_uniform", lambda *_args: 3.5)
    monkeypatch.setattr(race_telemetry.time, "time", lambda: 1000.0)

    payload_bytes = []
    for os_name, physical_height in (("nt", 1080), ("posix", None)):
        with monkeypatch.context() as platform_patch:
            platform_patch.setattr(race_telemetry.os, "name", os_name)
            if physical_height is None:
                platform_patch.delattr(ctypes, "windll", raising=False)
            else:
                user32 = type(
                    "User32",
                    (),
                    {
                        "SetProcessDPIAware": lambda self: None,
                        "GetSystemMetrics": lambda self, _index: physical_height,
                    },
                )()
                platform_patch.setattr(
                    ctypes,
                    "windll",
                    type("Windll", (), {"user32": user32})(),
                    raising=False,
                )
            payload = {}
            race_telemetry.apply_race_out_button_info(payload, 42, 4)
            payload_bytes.append(payload["button_info"].encode("utf-8"))

    expected = (
        b'{"ViewerId":42,"DeviceId":4,"ScenarioId":4,'
        b'"ClickPosX":9888888,"ClickPosY":1422222,'
        b'"ClickServerTime":996}'
    )
    assert payload_bytes == [expected, expected]
    assert json.loads(expected)["ClickPosX"] == 9_888_888
    assert json.loads(expected)["ClickPosY"] == 1_422_222


def test_race_out_height_override_is_the_only_coordinate_override(monkeypatch):
    monkeypatch.setattr(
        race_telemetry, "dna_gauss", lambda mean, _sigma: mean,
    )
    monkeypatch.setattr(race_telemetry, "dna_uniform", lambda *_args: 3.5)
    monkeypatch.setattr(race_telemetry.time, "time", lambda: 1000.0)
    monkeypatch.setattr(race_telemetry.os, "name", "nt")

    user32 = type(
        "User32",
        (),
        {
            "SetProcessDPIAware": lambda self: None,
            "GetSystemMetrics": lambda self, _index: 1080,
        },
    )()
    monkeypatch.setattr(
        ctypes,
        "windll",
        type("Windll", (), {"user32": user32})(),
        raising=False,
    )

    monkeypatch.delenv(race_telemetry.SCREEN_HEIGHT_OVERRIDE_ENV, raising=False)
    canonical = race_telemetry.build_button_info(42, 4)
    monkeypatch.setenv(race_telemetry.SCREEN_HEIGHT_OVERRIDE_ENV, "1080")
    overridden = race_telemetry.build_button_info(42, 4)

    assert (canonical["ClickPosX"], canonical["ClickPosY"]) == (
        9_888_888,
        1_422_222,
    )
    assert (overridden["ClickPosX"], overridden["ClickPosY"]) == (
        9_892_586,
        1_423_393,
    )


def test_apply_race_out_button_info_only_touches_button_info():
    payload = {"current_turn": 40}
    race_telemetry.apply_race_out_button_info(payload, 1, 2)
    assert payload["current_turn"] == 40
    assert isinstance(payload["button_info"], str)
    # Compact JSON: the real client sends no spaces.
    assert ", " not in payload["button_info"]


# --- diagnostics ------------------------------------------------------------

def test_redaction_covers_every_sensitive_key_at_any_depth():
    sensitive = {key: key for key in diagnostics.SENSITIVE_ERROR_KEYS}
    redacted = diagnostics.redact_for_console(
        {"data": {**sensitive, "turn": 3}},
    )
    inner = redacted["data"]
    assert set(k for k, v in inner.items() if v == "<redacted>") == diagnostics.SENSITIVE_ERROR_KEYS
    assert inner["turn"] == 3


def test_long_strings_and_long_lists_are_capped():
    assert diagnostics.redact_for_console("x" * 500).endswith("...<truncated>")
    assert len(diagnostics.redact_for_console(list(range(50)))) == 20


def test_format_api_error_keeps_only_the_interesting_data_keys():
    detail = diagnostics.format_api_error(
        "single_mode_free/start", 102,
        {"response_code": 200, "data_headers": {"sid": "secret"},
         "data": {"error_message": "nope", "noise": [1, 2, 3]}},
    )
    assert '"error_message": "nope"' in detail
    assert "noise" not in detail
    assert "secret" not in detail


def test_payload_and_response_summaries_stay_endpoint_aware():
    assert diagnostics.api_payload_summary(
        "single_mode_free/gain_skills", {"current_turn": 5, "gain_skill_info_array": [1]},
    ) == {"current_turn": 5, "gain_skill_info_array": [1]}
    assert diagnostics.api_payload_summary("single_mode_free/race_end", None) == {"current_turn": None}

    summary = diagnostics.response_summary(
        {"data_headers": {"result_code": 1},
         "data": {"chara_info": {"turn": 12, "vital": 60},
                  "race_start_info": {"program_id": 7, "is_short": 0}}},
    )
    assert summary["result_code"] == 1
    assert summary["chara"]["turn"] == 12
    assert summary["race_start_info"]["program_id"] == 7


def test_safe_payload_copies_rather_than_aliases():
    original = {
        "a": 1,
        "password": "raw-secret",
        "nested": {"link_password": "hashed-secret"},
    }
    copy = diagnostics.safe_payload(original)
    copy["a"] = 2
    assert original["a"] == 1
    assert copy["password"] == "<redacted>"
    assert copy["nested"]["link_password"] == "<redacted>"
    assert "raw-secret" not in str(copy)
    assert "hashed-secret" not in str(copy)
    assert diagnostics.safe_payload(None) == {}


def test_client_summary_methods_delegate_unchanged():
    client = UmaClient.__new__(UmaClient)
    res = {"data_headers": {"result_code": 1}, "data": {}}
    assert client.response_summary(res) == diagnostics.response_summary(res)
    assert client.safe_payload({"a": 1}) == {"a": 1}
    assert client.api_payload_summary("x/gain_skills", {}) == {
        "current_turn": None, "gain_skill_info_array": [],
    }


# --- the wire itself did not move -------------------------------------------

def test_call_locked_still_owns_the_ladder_it_always_owned():
    """Cheap structural guard for the B3 exclusion: these live in _call_locked."""
    src = inspect.getsource(UmaClient._call_locked)
    for token in (
        "retry_500", "retry_205", "retry_208", "next_sid(", "backoff_sleep(",
        "_note_api_error", "AuthInvalidatedError", "ClientVersionError",
        "self.common()", "self._apply_race_out_click_payload(payload)",
    ):
        assert token in src, token
