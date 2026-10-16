import sqlite3

from uma_data import (
    load_single_use_tp_campaigns,
    resolve_single_mode_use_tp,
)
from uma_data import tp_cost

# The process-wide campaign memo is cleared per test by the autouse
# _offline_single_use_tp_campaigns fixture in tests/conftest.py.
ACTIVE_GLOBAL_CAMPAIGN = {"target_id": 0, "use_tp": 15, "start_time": 100, "end_time": 200}


def test_resolve_single_mode_use_tp_uses_active_global_campaign():
    campaigns = [{"target_id": 0, "use_tp": 15, "start_time": 100, "end_time": 200}]

    assert resolve_single_mode_use_tp(campaigns, 150) == 15
    assert resolve_single_mode_use_tp(campaigns, 99) == 30
    assert resolve_single_mode_use_tp(campaigns, 201) == 30


def test_resolve_single_mode_use_tp_matches_scenario_target():
    campaigns = [{"target_id": 2, "use_tp": 15, "start_time": 100, "end_time": 200}]

    assert resolve_single_mode_use_tp(campaigns, 150, scenario_id=2) == 15
    assert resolve_single_mode_use_tp(campaigns, 150, scenario_id=4) == 30


def test_resolve_single_mode_use_tp_defaults_without_campaign_or_server_time():
    assert resolve_single_mode_use_tp([], 150) == 30
    assert resolve_single_mode_use_tp([], 0) == 30


def test_load_single_use_tp_campaigns_filters_campaign_data(tmp_path):
    db_path = tmp_path / "master.mdb"
    columns = [
        "campaign_id",
        "target_type",
        "target_id",
        "effect_type_1",
        "effect_value_1",
        "open_flag_id",
        "user_show",
        "disp_order",
        "image_icon_id",
        "transition_type",
        "image_change",
        "logo_type",
        "start_time",
        "end_time",
    ]
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE campaign_data ("
            + ", ".join(f"{column} INTEGER" for column in columns)
            + ")"
        )
        connection.executemany(
            "INSERT INTO campaign_data VALUES (" + ", ".join("?" for _ in columns) + ")",
            [
                (225, 1, 0, 4, 15, 0, 1, 1, 0, 0, 0, 0, 100, 200),
                (226, 2, 0, 2, 10, 0, 1, 1, 0, 0, 0, 0, 100, 200),
                (227, 1, 0, 1, 99, 0, 1, 1, 0, 0, 0, 0, 100, 200),
            ],
        )

    assert load_single_use_tp_campaigns(tmp_path, master_mdb_path=db_path) == [
        {"campaign_id": 225, "target_id": 0, "use_tp": 15, "start_time": 100, "end_time": 200}
    ]


# --- career-start TP cost policy (moved off UmaClient in §13.1/A7) -----------


def test_career_start_tp_uses_active_campaign(monkeypatch):
    monkeypatch.setattr(tp_cost, "load_active_campaigns", lambda base_dir=None: [ACTIVE_GLOBAL_CAMPAIGN])

    assert tp_cost.single_mode_career_start_tp(server_time=150) == 15
    # Outside the campaign window the full cost is restored.
    assert tp_cost.single_mode_career_start_tp(server_time=99) == 30
    assert tp_cost.single_mode_career_start_tp(server_time=300) == 30


def test_career_start_tp_without_campaign_is_full_cost(monkeypatch):
    monkeypatch.setattr(tp_cost, "load_active_campaigns", lambda base_dir=None: [])

    assert tp_cost.single_mode_career_start_tp(server_time=150) == 30


def test_career_start_tp_honours_scenario_target(monkeypatch):
    campaign = {"target_id": 2, "use_tp": 15, "start_time": 100, "end_time": 200}
    monkeypatch.setattr(tp_cost, "load_active_campaigns", lambda base_dir=None: [campaign])

    assert tp_cost.single_mode_career_start_tp(server_time=150, scenario_id=2) == 15
    assert tp_cost.single_mode_career_start_tp(server_time=150, scenario_id=4) == 30


def test_career_start_tp_falls_back_when_master_data_fails(monkeypatch):
    def _boom(base_dir=None):
        raise RuntimeError("master.mdb exploded")

    monkeypatch.setattr(tp_cost, "load_active_campaigns", _boom)

    assert tp_cost.single_mode_career_start_tp(server_time=150) == 30


def test_active_campaigns_reload_only_when_master_mdb_changes(monkeypatch):
    state = {"mtime": 1, "loads": 0}

    def _load(base_dir, master_mdb_path=None):
        state["loads"] += 1
        return [ACTIVE_GLOBAL_CAMPAIGN]

    monkeypatch.setattr(tp_cost, "master_mdb_mtime_ns", lambda base_dir: state["mtime"])
    monkeypatch.setattr(tp_cost, "load_single_use_tp_campaigns", _load)

    assert tp_cost.load_active_campaigns("base") == [ACTIVE_GLOBAL_CAMPAIGN]
    assert tp_cost.load_active_campaigns("base") == [ACTIVE_GLOBAL_CAMPAIGN]
    assert state["loads"] == 1

    state["mtime"] = 2
    assert tp_cost.load_active_campaigns("base") == [ACTIVE_GLOBAL_CAMPAIGN]
    assert state["loads"] == 2


def test_deprecated_client_shim_delegates_to_master_data(monkeypatch):
    from uma_api.client import UmaClient

    campaign = {"target_id": 4, "use_tp": 15, "start_time": 100, "end_time": 200}
    monkeypatch.setattr(tp_cost, "load_active_campaigns", lambda base_dir=None: [campaign])

    client = UmaClient.__new__(UmaClient)
    client.last_servertime = 150
    client.current_scenario_id = 4

    # Scenario falls back to the client's active one, server clock comes from the client.
    assert client.single_mode_use_tp() == 15
    # An explicit non-matching scenario wins over the client's, so no discount.
    assert client.single_mode_use_tp(scenario_id=2) == 30
    # The old instance-level campaign cache is gone; the shim holds no state.
    assert not hasattr(client, "_single_use_tp_cache")
