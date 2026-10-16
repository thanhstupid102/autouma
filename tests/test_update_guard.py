import json

import pytest

from integrations.discord import notify
from uma_api import appstore_version
from uma_api import client_version, update_guard
from uma_api.errors import ApiError


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (1, update_guard.Diagnosis.OK),
        (204, update_guard.Diagnosis.VERSION_STALE),
        (214, update_guard.Diagnosis.RESOURCE_STALE),
        (201, update_guard.Diagnosis.SESSION),
        (217, update_guard.Diagnosis.SESSION),
        (102, update_guard.Diagnosis.OTHER),
        (703, update_guard.Diagnosis.ACCOUNT_UDID_CONFLICT),
        (704, update_guard.Diagnosis.PC_ACCOUNT_LIMIT_ERROR),
        (705, update_guard.Diagnosis.NO_PLATFORM_USER_ID_ERROR),
        (708, update_guard.Diagnosis.NO_CHAINED_USER_ID_ERROR),
        (709, update_guard.Diagnosis.STEAM_ACCOUNT_REMOVE_CHAINED),
        (390, update_guard.Diagnosis.OBSERVED_STEAM_IDENTITY_REQUIRED),
        (202, update_guard.Diagnosis.OTHER),
        (203, update_guard.Diagnosis.AUTH_INVALIDATED),
        (101, update_guard.Diagnosis.MAINTENANCE),
        (999, update_guard.Diagnosis.OTHER),
    ],
)
def test_classify_result_code(code, expected):
    diagnosis, remedy = update_guard.classify_result_code(code)
    assert diagnosis == expected
    assert remedy


@pytest.mark.parametrize(
    ("code", "expected", "remedy_fragment"),
    [
        (703, update_guard.Diagnosis.ACCOUNT_UDID_CONFLICT, "fresh UDID"),
        (704, update_guard.Diagnosis.PC_ACCOUNT_LIMIT_ERROR, "PC account link"),
        (705, update_guard.Diagnosis.NO_PLATFORM_USER_ID_ERROR, "Steam"),
        (708, update_guard.Diagnosis.NO_CHAINED_USER_ID_ERROR, "Trainer-ID link"),
        (709, update_guard.Diagnosis.STEAM_ACCOUNT_REMOVE_CHAINED, "remains chained"),
    ],
)
def test_linkage_result_codes_have_specific_operator_remedies(code, expected, remedy_fragment):
    diagnosis, remedy = update_guard.classify_result_code(code)
    assert diagnosis is expected
    assert remedy_fragment in remedy
    if code == 703:
        assert "scripts/recapture_account.py" not in remedy


def test_observed_390_explains_required_steam_common_identity_without_guessing_name():
    diagnosis, remedy = update_guard.classify_result_code(390)

    assert diagnosis is update_guard.Diagnosis.OBSERVED_STEAM_IDENTITY_REQUIRED
    assert "symbolic name unconfirmed" in remedy
    assert "steam_id" in remedy
    assert "steam_session_ticket" in remedy
    assert "do not retry" in remedy


@pytest.mark.parametrize(
    ("expected_viewer_id", "data_headers", "expected"),
    [
        (123, {"viewer_id": 456}, True),
        ("123", {"viewer_id": "456"}, True),
        (123, {"viewer_id": 123}, False),
        (123, {"viewer_id": "123"}, False),
        (123, {"viewer_id": 0}, False),
        (123, {"viewer_id": "0"}, False),
        (123, {}, False),
        (0, {"viewer_id": 456}, True),
        (None, {"viewer_id": 456}, True),
        (123, None, False),
        (123, "not-headers", False),
        (123, {"viewer_id": "not-an-id"}, False),
    ],
)
def test_is_reregistration_signature(expected_viewer_id, data_headers, expected):
    assert (
        update_guard.is_reregistration_signature(expected_viewer_id, data_headers)
        is expected
    )


def test_typed_guard_exceptions_are_distinguishable():
    assert issubclass(update_guard.ClientVersionError, Exception)
    assert issubclass(update_guard.AuthInvalidatedError, Exception)
    assert update_guard.ClientVersionError is not update_guard.AuthInvalidatedError


def test_alert_once_deduplicates_send_and_merges_status(tmp_path, monkeypatch):
    monkeypatch.setattr(update_guard, "_ALERTED", set())
    sent = []

    def fake_send_alert(base_dir, title, message):
        sent.append((base_dir, title, message))
        return True

    monkeypatch.setattr(notify, "send_alert", fake_send_alert)
    diagnosis, remedy = update_guard.classify_result_code(204)

    assert update_guard.alert_once(tmp_path, "alice", diagnosis, remedy) is True
    assert update_guard.alert_once(tmp_path, "alice", diagnosis, remedy) is False

    assert len(sent) == 1
    records = json.loads(
        (tmp_path / "update_status.json").read_text(encoding="utf-8")
    )
    assert len(records) == 1
    assert records[0]["account"] == "alice"
    assert records[0]["diagnosis"] == "VERSION_STALE"
    assert records[0]["remedy"] == remedy
    assert records[0]["ts"]


def test_alert_once_dispatches_to_an_injected_sink(tmp_path, monkeypatch):
    """An injected sink replaces the integrations.discord.notify fallback entirely, so a
    caller that owns its own notifier never triggers the upward late import."""
    monkeypatch.setattr(update_guard, "_ALERTED", set())
    sent = []

    def boom(*args, **kwargs):  # the default path must NOT be taken
        raise AssertionError("default notify sink should not be used")

    monkeypatch.setattr(update_guard, "_default_alert_sink", boom)
    diagnosis, remedy = update_guard.classify_result_code(204)

    posted = update_guard.alert_once(
        tmp_path, "bob", diagnosis, remedy, extra={"ep": "load/index"},
        alert_sink=lambda base_dir, title, message: sent.append((base_dir, title, message)),
    )

    assert posted is True
    assert len(sent) == 1
    base_dir, title, message = sent[0]
    assert base_dir == tmp_path
    assert "VERSION_STALE" in title
    assert "bob" in message and remedy in message
    assert "load/index" in message  # extra is appended as Details


class _Response:
    status_code = 200
    text = "packed"


class _Session:
    def __init__(self):
        self.request_headers = []

    def post(self, *args, **kwargs):
        self.request_headers.append(dict(kwargs.get("headers") or {}))
        return _Response()


def _client_for_responses(monkeypatch, tmp_path, responses):
    import uma_api.client as client_module

    client = client_module.UmaClient.__new__(client_module.UmaClient)
    client.sid = bytes(16)
    client.udid_str = "00000000-0000-0000-0000-000000000000"
    client.viewer_id = 1
    client.app_ver = "1.0.0"
    client.res_ver = "100"
    client.session = _Session()
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    client.current_scenario_id = None
    client.api_jitter = 0
    client.api_warehouse_base_dir = None
    client.state_root = tmp_path
    client.api_warehouse_account = "alice"
    client.account_name = "alice"
    client.api_log = lambda *args, **kwargs: None
    client.common = lambda: {"viewer_id": 1}
    client.auth_bytes = lambda: b""
    client.noted_api_errors = []
    client._note_api_error = lambda ep, rc: client.noted_api_errors.append((ep, rc))

    response_iter = iter(responses)
    monkeypatch.setattr(
        appstore_version,
        "fetch_app_ver_from_store",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(client_module.Settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(client_module, "pack", lambda *args, **kwargs: b"request")
    monkeypatch.setattr(client_module, "get_raw_udid", lambda _udid: b"0" * 16)
    monkeypatch.setattr(client_module, "unpack", lambda *_args: next(response_iter))
    monkeypatch.setattr(client_module, "dna_sleep", lambda *args, **kwargs: None)
    return client, client_module


def test_703_alerts_once_with_the_udid_conflict_remedy(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 703}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(
        client_module._update_guard,
        "alert_once",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    with pytest.raises(ApiError) as exc_info:
        client.call("load/index", {})

    assert exc_info.value.result_code == 703
    assert len(alerts) == 1
    alert_args, _alert_kwargs = alerts[0]
    assert alert_args[2] is update_guard.Diagnosis.ACCOUNT_UDID_CONFLICT
    assert "fresh UDID" in alert_args[3]
    assert "scripts/recapture_account.py" not in alert_args[3]


@pytest.mark.parametrize("result_code", [704, 705, 708, 709])
def test_new_linkage_diagnoses_do_not_add_discord_alerts(
    result_code, tmp_path, monkeypatch,
):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": result_code}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(
        client_module._update_guard,
        "alert_once",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    with pytest.raises(ApiError):
        client.call("load/index", {})

    assert alerts == []


def test_observed_390_is_not_retried(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 390}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(
        client_module._update_guard,
        "alert_once",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    with pytest.raises(ApiError) as exc_info:
        client.call("load/index", {})

    assert exc_info.value.result_code == 390
    assert len(client.session.request_headers) == 1
    assert client.noted_api_errors == [("load/index", 390)]
    assert alerts == []


@pytest.mark.parametrize(
    ("source", "current_app_ver", "expected_headers"),
    [
        ("auto-startup", "1.0.0", ["1.0.0", "9.9.9"]),
        ("appstore", "9.9.9", ["9.9.9", "9.9.9"]),
    ],
)
def test_204_refresh_retry_order_is_source_independent(
    source, current_app_ver, expected_headers, tmp_path, monkeypatch,
):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 204}, "data": {}},
        {"data_headers": {"result_code": 1}, "data": {}},
    ])
    client.app_ver = current_app_ver
    assert client_version.set_app_ver(
        tmp_path, current_app_ver, source=source,
    )
    monkeypatch.setattr(
        appstore_version,
        "fetch_app_ver_from_store",
        lambda *_args, **_kwargs: "9.9.9",
    )
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    result = client.call("load/index", {})

    assert result["data_headers"]["result_code"] == 1
    assert client.app_ver == "9.9.9"
    assert [
        headers["APP-VER"] for headers in client.session.request_headers
    ] == expected_headers
    assert len(client.session.request_headers) == 2
    assert alerts == []


def test_204_second_rejection_alerts_and_raises_typed_error(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 204}, "data": {}},
        {"data_headers": {"result_code": 204}, "data": {}},
    ])
    assert client_version.set_app_ver(tmp_path, "9.9.9", source="publisher")
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    with pytest.raises(update_guard.ClientVersionError, match="app_ver rejected"):
        client.call("load/index", {})

    assert len(client.session.request_headers) == 2
    assert len(alerts) == 1


def test_214_adopts_data_header_resource_version_and_retries_once(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 214, "resource_version": "200"}, "data": {}},
        {"data_headers": {"result_code": 1}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    result = client.call("tool/start_session", {})

    assert result["data_headers"]["result_code"] == 1
    assert client.res_ver == "200"
    assert client_version.get_res_ver(tmp_path) == "200"
    assert [headers["RES-VER"] for headers in client.session.request_headers] == ["100", "200"]
    assert alerts == []


def test_214_without_resource_version_alerts_as_recoverable(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 214}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    with pytest.raises(Exception, match="API error 214") as exc_info:
        client.call("tool/start_session", {})

    assert not isinstance(exc_info.value, update_guard.ClientVersionError)
    assert len(client.session.request_headers) == 1
    assert len(alerts) == 1


@pytest.mark.parametrize("result_code", [102, 202])
def test_plain_auth_overload_uses_existing_generic_error_path(
    result_code, tmp_path, monkeypatch
):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {
            "data_headers": {"result_code": result_code, "viewer_id": 1},
            "data": {},
        },
    ])
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    with pytest.raises(Exception, match=f"API error {result_code}") as exc_info:
        client.call("single_mode_free/start", {})

    assert not isinstance(exc_info.value, update_guard.AuthInvalidatedError)
    assert len(client.session.request_headers) == 1
    assert client.noted_api_errors == [("single_mode_free/start", result_code)]
    assert alerts == []


@pytest.mark.parametrize("result_code", [102, 202])
def test_guest_viewer_signature_raises_auth_invalidation(
    result_code, tmp_path, monkeypatch
):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {
            "data_headers": {"result_code": result_code, "viewer_id": 999},
            "data": {},
        },
    ])
    alerts = []
    monkeypatch.setattr(
        client_module._update_guard,
        "alert_once",
        lambda *args, **kwargs: alerts.append(args),
    )

    with pytest.raises(update_guard.AuthInvalidatedError, match="Sign in again"):
        client.call("load/index", {})

    assert len(client.session.request_headers) == 1
    assert client.noted_api_errors == []
    assert len(alerts) == 1
    assert alerts[0][2] == update_guard.Diagnosis.AUTH_INVALIDATED


def test_recovered_by_design_102_remains_exempt(tmp_path, monkeypatch):
    client, client_module = _client_for_responses(monkeypatch, tmp_path, [
        {"data_headers": {"result_code": 102}, "data": {}},
    ])
    alerts = []
    monkeypatch.setattr(client_module._update_guard, "alert_once", lambda *args, **kwargs: alerts.append(args))

    with pytest.raises(Exception, match="API error 102") as exc_info:
        client.call("single_mode_free/factor_select", {})

    assert not isinstance(exc_info.value, update_guard.AuthInvalidatedError)
    assert len(client.session.request_headers) == 1
    assert alerts == []


def test_login_does_not_retry_typed_auth_invalidation(monkeypatch):
    import uma_api.client as client_module

    class LoginSession:
        def __init__(self):
            self.headers = {}

        def close(self):
            pass

    client = client_module.UmaClient.__new__(client_module.UmaClient)
    client.session = LoginSession()
    client.has_game_auth = lambda: True
    client.regen_sid = lambda: None
    calls = []

    def reject(*args, **kwargs):
        calls.append((args, kwargs))
        raise update_guard.AuthInvalidatedError("API error 202")

    client.call = reject
    monkeypatch.setattr(client_module.requests, "Session", LoginSession)

    with pytest.raises(update_guard.AuthInvalidatedError):
        client.login(max_retries=3)
    assert len(calls) == 1


def test_login_retries_plain_202_before_succeeding(monkeypatch):
    import uma_api.client as client_module

    class LoginSession:
        def __init__(self):
            self.headers = {}

        def close(self):
            pass

    client = client_module.UmaClient.__new__(client_module.UmaClient)
    client.session = LoginSession()
    client.has_game_auth = lambda: True
    client.regen_sid = lambda: None
    client.refresh_cached_account_state = lambda data: None
    calls = []
    start_session_attempts = 0

    def call(ep, args):
        nonlocal start_session_attempts
        calls.append(ep)
        if ep == "tool/start_session":
            start_session_attempts += 1
            if start_session_attempts < 3:
                raise Exception(f"API error 202 on {ep}")
        return {"data_headers": {"result_code": 1}, "data": {}}

    client.call = call
    sleeps = []
    monkeypatch.setattr(client_module.requests, "Session", LoginSession)
    monkeypatch.setattr(
        client_module, "jittered_sleep", lambda seconds: sleeps.append(seconds)
    )

    result = client.login(max_retries=3)

    assert result["data_headers"]["result_code"] == 1
    assert calls == [
        "tool/start_session",
        "tool/start_session",
        "tool/start_session",
        "load/index",
    ]
    assert sleeps == [4.15, 4.15]
