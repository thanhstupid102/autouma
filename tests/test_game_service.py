from types import SimpleNamespace

import pytest

from uma_api import api_warehouse, game_service  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = {
            "read_info": {"read": True},
            "login": {"login": True},
            "load_career": {"career": True},
            "pre_single_mode": {"pre": True},
            "start_career": {"start": True},
            "exec_command": {"exec": True},
            "finish_career": {"finish": True},
            "remove_trained_chara": {"remove": True},
            "recovery_tp": {"recover": True},
            "use_recovery_item": {"item": True},
        }

    def call(self, endpoint, payload=None):
        res = {"endpoint": endpoint, "payload": payload}
        self.calls.append(("call", endpoint, payload, res))
        return res

    def read_info(self):
        self.calls.append(("read_info",))
        return self.responses["read_info"]

    def login(self):
        self.calls.append(("login",))
        return self.responses["login"]

    def load_career(self):
        self.calls.append(("load_career",))
        return self.responses["load_career"]

    def pre_single_mode(self, exclude_viewer_ids=None):
        self.calls.append(("pre_single_mode", exclude_viewer_ids))
        return self.responses["pre_single_mode"]

    def start_career(self, **kwargs):
        self.calls.append(("start_career", kwargs))
        return self.responses["start_career"]

    def exec_command(self, **kwargs):
        self.calls.append(("exec_command", kwargs))
        return self.responses["exec_command"]

    def finish_career(self, **kwargs):
        self.calls.append(("finish_career", kwargs))
        return self.responses["finish_career"]

    def remove_trained_chara(self, trained_chara_ids, unlock_ids=None):
        self.calls.append(("remove_trained_chara", trained_chara_ids, unlock_ids))
        return self.responses["remove_trained_chara"]

    def recovery_tp(self, count):
        self.calls.append(("recovery_tp", count))
        return self.responses["recovery_tp"]

    def use_recovery_item(self, item_id, item_num):
        self.calls.append(("use_recovery_item", item_id, item_num))
        return self.responses["use_recovery_item"]


def sample_response():
    return {
        "response_code": 1,
        "data_headers": {"result_code": 1, "servertime": 123},
        "data": {"single_mode_difficulty_info_array": [{"difficulty_id": 9, "open_difficulty_index": 3}]},
    }


def test_load_index_live_delegates_and_preserves_response():
    client = FakeClient()
    session = SimpleNamespace(client=client)
    result = game_service.load_index_live(session)
    assert result is client.calls[-1][3]
    assert client.calls[-1][:3] == ("call", "load/index", {"adid": ""})


def test_load_index_live_allows_custom_payload():
    client = FakeClient()
    session = SimpleNamespace(client=client)
    payload = {}
    result = game_service.load_index_live(session, payload)
    assert result["payload"] is payload
    assert client.calls[-1][:3] == ("call", "load/index", payload)


def test_cached_load_index_uses_api_warehouse_path(tmp_path):
    path = api_warehouse.write_latest(tmp_path, "alice", "load/index", sample_response())
    record = game_service.load_index_cached(tmp_path, "alice")
    assert path == api_warehouse.response_path(tmp_path, "alice", "load/index")
    assert record == api_warehouse.read_latest(tmp_path, "alice", "load/index")
    assert game_service.load_index_cached_data(tmp_path, "alice") == sample_response()["data"]


def test_live_wrappers_delegate_to_existing_client_methods():
    client = FakeClient()
    session = SimpleNamespace(client=client)

    assert game_service.read_info(session) is client.responses["read_info"]
    assert game_service.login(session) is client.responses["login"]
    assert game_service.login_client(client) is client.responses["login"]
    assert game_service.load_career(session) is client.responses["load_career"]
    assert game_service.pre_single_mode(session, [1, 2]) is client.responses["pre_single_mode"]
    assert game_service.start_career(session, card_id=1) is client.responses["start_career"]
    assert game_service.exec_command(session, command_type=1) is client.responses["exec_command"]
    assert game_service.finish_career(session, 7, is_force_delete=True) is client.responses["finish_career"]
    assert game_service.remove_trained_chara(session, [8], unlock_ids=[9]) is client.responses["remove_trained_chara"]
    assert game_service.recovery_tp(session, 2) is client.responses["recovery_tp"]
    assert game_service.use_recovery_item(session, 32, 2) is client.responses["use_recovery_item"]

    assert ("pre_single_mode", [1, 2]) in client.calls
    assert ("start_career", {"card_id": 1}) in client.calls
    assert ("exec_command", {"command_type": 1}) in client.calls
    assert ("finish_career", {"current_turn": 7, "is_force_delete": True}) in client.calls
    assert ("remove_trained_chara", [8], [9]) in client.calls
    assert ("recovery_tp", 2) in client.calls
    assert ("use_recovery_item", 32, 2) in client.calls


def test_require_client_raises_clear_not_logged_in():
    try:
        game_service.require_client(SimpleNamespace(client=None))
    except ValueError as exc:
        assert str(exc) == "Not logged in"
    else:
        raise AssertionError("missing ValueError")


# --- §13.2 B1: the master-refresh asymmetry, pinned offline -------------------
# login_with_master_refresh (application layer) MUST check master-data
# freshness after a session login; the transport-side logins (game_service
# .login / .login_client) must NOT -- moving the check must not have made the
# auth bootstrap path start refreshing, nor the app flows stop.

def test_login_with_master_refresh_checks_master_data(monkeypatch):
    from backend.app.services import game_login

    ensure_calls = []
    monkeypatch.setattr(
        game_login._master_updater, "ensure_current",
        lambda base_dir, server, ver, **kwargs: ensure_calls.append(
            (str(server), str(ver))
        ) or False,
    )
    monkeypatch.setattr(
        game_login._master_data,
        "stale_master_json_files",
        lambda *args, **kwargs: [],
    )
    reload_calls = []
    monkeypatch.setattr(
        game_login,
        "reload_master_json_data",
        lambda base_dir, state_root: reload_calls.append((base_dir, state_root)),
    )
    monkeypatch.setattr(
        game_login._master_data,
        "generate",
        lambda *args, **kwargs: pytest.fail(
            "no master update must not regenerate derived JSON"
        ),
    )
    client = FakeClient()
    client.resource_server = "https://cdn.example/"
    client.res_ver = "10006800"
    session = SimpleNamespace(client=client)

    result = game_login.login_with_master_refresh(session)

    assert result is client.responses["login"]
    assert ("login",) in client.calls
    assert ensure_calls == [("https://cdn.example/", "10006800")]
    assert reload_calls == []


def test_login_with_master_refresh_regenerates_state_json_after_update(
    tmp_path, monkeypatch,
):
    from backend.app.services import game_login

    generate_calls = []

    monkeypatch.setattr(
        game_login._master_updater,
        "ensure_current",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        game_login._master_data,
        "generate",
        lambda base_dir, **kwargs: generate_calls.append(
            (base_dir, kwargs.get("state_root"))
        ) or {"success": True},
    )
    monkeypatch.setattr(
        game_login._master_data,
        "stale_master_json_files",
        lambda *args, **kwargs: [],
    )
    reload_calls = []
    monkeypatch.setattr(
        game_login,
        "reload_master_json_data",
        lambda base_dir, state_root: reload_calls.append((base_dir, state_root)),
    )
    client = FakeClient()
    client.resource_server = "https://cdn.example/"
    client.res_ver = "10006800"
    client.state_root = tmp_path

    game_login.login_with_master_refresh(SimpleNamespace(client=client))

    assert generate_calls == [(game_login.Settings.BASE_DIR, tmp_path)]
    assert reload_calls == [(game_login.Settings.BASE_DIR, tmp_path)]


def test_login_with_master_refresh_never_fails_the_login(monkeypatch):
    from backend.app.services import game_login

    def _boom(*args):
        raise RuntimeError("cdn is down")

    monkeypatch.setattr(game_login._master_updater, "ensure_current", _boom)
    monkeypatch.setattr(
        game_login._master_data,
        "stale_master_json_files",
        lambda *args, **kwargs: [],
    )
    client = FakeClient()  # no resource_server/res_ver attrs either
    session = SimpleNamespace(client=client)

    assert game_login.login_with_master_refresh(session) is client.responses["login"]


def test_transport_logins_do_not_touch_master_data(monkeypatch):
    # A raising fake would prove nothing -- the pre-B1 code swallowed every
    # exception in its try/except. A recording spy has real teeth: on the old
    # game_service.login it WOULD record a call.
    import uma_data.master_updater as master_updater

    ensure_calls = []
    monkeypatch.setattr(
        master_updater, "ensure_current",
        lambda *a, **k: ensure_calls.append(a) or False,
    )
    client = FakeClient()
    client.resource_server = "https://cdn.example/"
    client.res_ver = "10006800"
    session = SimpleNamespace(client=client)

    assert game_service.login(session) is client.responses["login"]
    assert game_service.login_client(client) is client.responses["login"]
    assert ensure_calls == []


class ForceDeleteClient:
    def __init__(self, load_response=None, *, load_error=None, race_out_error=None, finish_error=None):
        self.load_response = load_response
        self.load_error = load_error
        self.race_out_error = race_out_error
        self.finish_error = finish_error
        self.calls = []

    def load_career(self):
        self.calls.append(("load_career",))
        if self.load_error is not None:
            raise self.load_error
        return self.load_response

    def race_out(self, current_turn):
        self.calls.append(("race_out", {"current_turn": current_turn}))
        if self.race_out_error is not None:
            raise self.race_out_error
        return {"data": {"chara_info": {"turn": current_turn}}}

    def check_event(self, **kwargs):
        self.calls.append(("check_event", kwargs))
        return {"data": {"chara_info": {"turn": kwargs["current_turn"]}}}

    def finish_career(self, **kwargs):
        self.calls.append(("finish_career", kwargs))
        if self.finish_error is not None:
            raise self.finish_error
        return {"finish": True}


def force_delete_state(turn=42, **data):
    return {"data": {"chara_info": {"turn": turn}, **data}}


def delete_session(client, career=None):
    account = {"career": career}
    return SimpleNamespace(
        client=client,
        runner=SimpleNamespace(snapshot=lambda: {"running": False}),
        loop_active=lambda: False,
        account=account,
        dashboard_data={"account": account},
    )


def test_force_delete_uses_authoritative_loaded_turn_over_requested_turn():
    client = ForceDeleteClient(force_delete_state(42))
    session = SimpleNamespace(client=client)

    result = game_service.force_delete_career(
        session,
        requested_turn=7,
        cached_career={"active": True, "turn": 1},
    )

    assert result == {"finish": True}
    assert client.calls[-1] == (
        "finish_career",
        {"current_turn": 42, "is_force_delete": True},
    )


def test_force_delete_does_not_expect_chara_light_to_have_turn():
    client = ForceDeleteClient(force_delete_state(42))
    session = SimpleNamespace(client=client)
    chara_light = {
        "active": True,
        "card_id": 100101,
        "vital": 50,
        "fans": 1234,
        "reserve_race_turn": 45,
    }

    game_service.force_delete_career(
        session,
        requested_turn=0,
        cached_career=chara_light,
    )

    assert "turn" not in chara_light
    assert client.calls[-1] == (
        "finish_career",
        {"current_turn": 42, "is_force_delete": True},
    )


def test_force_delete_reconciles_active_race_before_finish_and_swallows_102():
    client = ForceDeleteClient(
        force_delete_state(42, race_start_info={"program_id": 9001}),
        race_out_error=Exception("API error 102 on single_mode_team/race_out"),
    )
    session = SimpleNamespace(client=client)

    result = game_service.force_delete_career(session, requested_turn=0)

    assert result == {"finish": True}
    assert client.calls == [
        ("load_career",),
        ("race_out", {"current_turn": 42}),
        ("finish_career", {"current_turn": 42, "is_force_delete": True}),
    ]


def test_force_delete_drains_single_confirm_event_before_finish():
    client = ForceDeleteClient(
        force_delete_state(
            42,
            unchecked_event_array=[{"event_id": 123, "chara_id": 456}],
        )
    )
    session = SimpleNamespace(client=client)

    game_service.force_delete_career(session)

    assert client.calls[1] == (
        "check_event",
        {
            "event_id": 123,
            "chara_id": 456,
            "choice_number": 0,
            "current_turn": 42,
        },
    )
    assert client.calls[2][0] == "finish_career"


@pytest.mark.parametrize(
    ("load_response", "load_error"),
    [
        ({"data": {}}, None),
        (None, Exception("API error 102 on single_mode_team/load")),
    ],
    ids=["no-chara-info", "load-102"],
)
def test_delete_endpoint_is_idempotent_when_career_is_already_gone(load_response, load_error):
    from backend.app.routers.careers.services.career_service import CareerService

    client = ForceDeleteClient(load_response, load_error=load_error)
    session = delete_session(client, career={"active": True})

    result = CareerService(session).delete_career(0)

    assert result["success"] is True
    assert session.account["career"] is None
    assert session.dashboard_data["account"] is session.account
    assert not any(call[0] == "finish_career" for call in client.calls)


@pytest.mark.parametrize("code", [102, 201])
def test_delete_endpoint_clears_career_when_finish_is_reconciled(code):
    from backend.app.routers.careers.services.career_service import CareerService

    client = ForceDeleteClient(
        force_delete_state(42),
        finish_error=Exception(f"API error {code} on single_mode_team/finish"),
    )
    session = delete_session(client, career={"active": True})

    result = CareerService(session).delete_career(0)

    assert result["success"] is True
    assert session.account["career"] is None
    assert client.calls[-1] == (
        "finish_career",
        {"current_turn": 42, "is_force_delete": True},
    )


def test_delete_endpoint_preserves_career_on_unexpected_load_error():
    from backend.app.routers.careers.services.career_service import CareerService

    client = ForceDeleteClient(load_error=Exception("network unavailable"))
    session = delete_session(client, career={"active": True})

    result = CareerService(session).delete_career(0)

    assert result == {"success": False, "detail": "network unavailable"}
    assert session.account["career"] == {"active": True}
