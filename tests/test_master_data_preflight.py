import logging
from types import SimpleNamespace

import uma_data
from backend.app.domain import master_data_preflight
from backend.app.routers.careers.schemas.career import RunCareerRequest
from backend.app.routers.careers.services import career_run, career_start
from backend.app.routers.careers.services.career_service import CareerService
from tests._helpers import start_career_request
from uma_api import game_service
from uma_api.session import Session


def test_mant_does_not_require_unity_tables(monkeypatch, tmp_path):
    def unexpected_loader(_base_dir):
        raise AssertionError("MANT must not inspect Unity Cup tables")

    monkeypatch.setattr(uma_data, "load_route_race_objectives", unexpected_loader)
    monkeypatch.setattr(uma_data, "load_scout_aptitudes", unexpected_loader)
    monkeypatch.setattr(uma_data, "stale_master_json_files", lambda *_args: [])

    assert master_data_preflight.career_master_data_error(
        tmp_path, tmp_path / "state", 4,
    ) is None


def test_consumer_loader_stubs_satisfy_unity_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(
        uma_data,
        "load_route_race_objectives",
        lambda _base_dir: {"objectives": {1: {}}, "race_groups": {1: [1]}},
    )
    monkeypatch.setattr(
        uma_data,
        "load_scout_aptitudes",
        lambda _base_dir: {"aptitudes": {1001: {}}},
    )
    monkeypatch.setattr(uma_data, "stale_master_json_files", lambda *_args: [])

    assert master_data_preflight.career_master_data_error(
        tmp_path, tmp_path / "state", 2,
    ) is None


def test_missing_database_message_names_automatic_fetch_remedy(monkeypatch, tmp_path):
    db_path = tmp_path / "master" / "master.mdb"
    unavailable = {
        "success": False,
        "reason": "missing_db",
        "master_mdb_path": db_path,
    }
    monkeypatch.setattr(
        uma_data, "load_route_race_objectives", lambda _base_dir: unavailable,
    )
    monkeypatch.setattr(
        uma_data, "load_scout_aptitudes", lambda _base_dir: unavailable,
    )

    assert master_data_preflight.career_master_data_error(
        tmp_path, tmp_path / "state", 2,
    ) == (
        f"Career start blocked for Unity Cup: master.mdb is unavailable at {db_path}. "
        "master.mdb is fetched automatically; check outbound network access and "
        "the pre-download resource version, then restart or log in to retry the CDN fetch."
    )


def test_missing_table_message_names_tables_and_refetch_remedy(monkeypatch, tmp_path):
    db_path = tmp_path / "master.mdb"
    monkeypatch.setattr(
        uma_data,
        "load_route_race_objectives",
        lambda _base_dir: {
            "success": False,
            "reason": "missing_tables",
            "master_mdb_path": db_path,
            "missing_tables": ["single_mode_race_group"],
        },
    )
    monkeypatch.setattr(
        uma_data,
        "load_scout_aptitudes",
        lambda _base_dir: {
            "success": False,
            "reason": "missing_tables",
            "master_mdb_path": db_path,
            "missing_tables": ["single_mode_scout_chara"],
        },
    )

    assert master_data_preflight.career_master_data_error(
        tmp_path, tmp_path / "state", 2,
    ) == (
        f"Career start blocked for Unity Cup: master.mdb at {db_path} is missing "
        "required table(s): single_mode_race_group, single_mode_scout_chara. "
        "Move the incomplete database aside, then restart or log in so the automatic "
        "CDN fetch replaces it; if the fetch fails, check network access and the "
        "resolved resource version."
    )


def test_stale_generated_json_message_names_file_and_generator(monkeypatch, tmp_path):
    state_root = tmp_path / "state"
    output_dir = state_root / "master_json"
    output_dir.mkdir(parents=True)
    stale_path = output_dir / "race_map.json"
    stale_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        uma_data,
        "stale_master_json_files",
        lambda *_args: ["race_map.json", "skill_data.json"],
    )

    assert master_data_preflight.career_master_data_error(
        tmp_path, state_root, 4,
    ) == (
        f"Career start blocked: generated master JSON does not match master.mdb: "
        f"{stale_path}. Run `python scripts/generate_master_data.py` from "
        f"{tmp_path.resolve()} to regenerate the files, then retry."
    )


def test_preflight_logs_the_same_detail_at_warning(monkeypatch, tmp_path, caplog):
    session = Session(
        name="master-warning",
        base_dir=str(tmp_path),
        state_root=str(tmp_path / "state"),
    )
    detail = "Career start blocked: exact operator detail"
    monkeypatch.setattr(
        career_start.master_data_preflight,
        "career_master_data_error",
        lambda *_args: detail,
    )
    caplog.set_level(logging.WARNING)

    assert career_start._master_data_preflight_failure(session, 4) == {
        "success": False,
        "detail": detail,
    }
    assert detail in caplog.messages


def test_fresh_start_blocks_before_live_state_or_tp_spend(monkeypatch, tmp_path):
    session = Session(
        name="master-fresh-start",
        base_dir=str(tmp_path),
        state_root=str(tmp_path / "state"),
    )
    session.client = SimpleNamespace()
    service = CareerService(session)
    monkeypatch.setattr(career_start, "_validate_start_preconditions", lambda *_args: None)
    monkeypatch.setattr(
        career_start.career_selection,
        "validate_start_selection",
        lambda *_args: None,
    )
    blocked = {"success": False, "detail": "missing master"}
    monkeypatch.setattr(
        career_start,
        "_master_data_preflight_failure",
        lambda *_args: blocked,
    )

    def unexpected_read_info(_session):
        raise AssertionError("preflight must run before live state or TP recovery")

    monkeypatch.setattr(game_service, "read_info", unexpected_read_info)

    assert service.start_career_from_request(start_career_request()) == blocked


def test_active_resume_uses_preflight_before_runner_launch(monkeypatch, tmp_path):
    session = Session(
        name="master-active-resume",
        base_dir=str(tmp_path),
        state_root=str(tmp_path / "state"),
    )
    session.client = SimpleNamespace()
    session.account = {"career": {"active": True, "scenario_id": 2}}
    service = CareerService(session)
    req = RunCareerRequest(scenario_id=2)
    monkeypatch.setattr(game_service, "load_index_live", lambda *_args: {"data": {}})
    monkeypatch.setattr(
        career_run.account_status,
        "get_account_status",
        lambda *_args: session.account,
    )
    monkeypatch.setattr(
        game_service,
        "load_career",
        lambda _session: {
            "data": {"chara_info": {"card_id": 100101, "turn": 4, "scenario_id": 2}},
        },
    )
    blocked = {"success": False, "detail": "missing Unity master"}
    monkeypatch.setattr(
        career_run,
        "_master_data_preflight_failure",
        lambda *_args: blocked,
    )

    def unexpected_runner_start(*_args, **_kwargs):
        raise AssertionError("resume must not launch the runner after preflight failure")

    monkeypatch.setattr(session.runner, "start", unexpected_runner_start)

    assert service._launch_career_run(req, {"scenario_id": 2}) == blocked
