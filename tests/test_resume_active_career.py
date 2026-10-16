from types import SimpleNamespace

import pytest

from uma_api import game_service
from uma_api.session import Session
from backend.app.domain import career_selection, preset_runtime
from backend.app.routers.careers.schemas.career import RunCareerRequest
from backend.app.routers.careers.services.career_service import CareerService


class FailingThenSuccessfulRunner:
    def __init__(self):
        self.start_calls = []
        self.loop_info = None

    def set_loop_info(self, current, target):
        self.loop_info = (current, target)

    def start(self, *args, **kwargs):
        self.start_calls.append((args, kwargs))

    def snapshot(self):
        if len(self.start_calls) == 1:
            return {"running": False, "status": "error", "last_error": "runner failed"}
        return {"running": False, "status": "ok"}

    def stop(self):
        pass


def make_resume_context(monkeypatch, tmp_path):
    session = Session(name="resume-active-test", base_dir=str(tmp_path))
    session.client = SimpleNamespace(tp_info={}, coin_info={}, item_map={})
    req = RunCareerRequest(scenario_id=1)
    preset = {}
    service = CareerService(session)

    monkeypatch.setattr(game_service, "login", lambda resume_session: {})
    monkeypatch.setattr(game_service, "refresh_cached_account_state", lambda *args: None)
    monkeypatch.setattr(preset_runtime, "apply_runtime_bot_config", lambda *args: None)
    monkeypatch.setattr(career_selection, "apply_deck_type_counts", lambda *args, **kwargs: None)
    return service, session, req, preset


@pytest.mark.parametrize("wrapped", [False, True])
def test_resume_active_career_loads_and_marks_active(monkeypatch, tmp_path, wrapped):
    service, session, req, preset = make_resume_context(monkeypatch, tmp_path)
    chara_info = {"card_id": 100101, "turn": 47, "scenario_id": 4}
    if wrapped:
        load_result = {"data": {"single_mode_start_common": {"chara_info": chara_info}}}
    else:
        load_result = {"data": {"chara_info": chara_info}}
    monkeypatch.setattr(game_service, "load_career", lambda resume_session: load_result)

    resumed = service._resume_active_career(req, preset)

    assert resumed
    assert resumed["data"]["chara_info"] == chara_info
    assert session.account["career"]["active"] is True


def test_resume_active_career_returns_none_when_load_fails(monkeypatch, tmp_path):
    service, _session, req, preset = make_resume_context(monkeypatch, tmp_path)

    def fail_load(resume_session):
        raise RuntimeError("no active career")

    monkeypatch.setattr(game_service, "load_career", fail_load)

    assert service._resume_active_career(req, preset) is None


def test_resume_active_career_returns_none_without_chara(monkeypatch, tmp_path):
    service, _session, req, preset = make_resume_context(monkeypatch, tmp_path)
    monkeypatch.setattr(game_service, "load_career", lambda resume_session: {"data": {}})

    assert service._resume_active_career(req, preset) is None


def test_loop_resumes_loaded_career_before_starting_new_one(monkeypatch, tmp_path):
    session = Session(name="resume-loop-test", base_dir=str(tmp_path))
    session.client = SimpleNamespace(tp_info={}, coin_info={}, item_map={})
    runner = FailingThenSuccessfulRunner()
    session.runner = runner
    service = CareerService(session)
    req = RunCareerRequest(run_count=1)
    preset = {"name": "resume-loop-test"}
    initial_result = {"data": {"chara_info": {"card_id": 100101, "turn": 1}}}
    resumed_result = {"data": {"chara_info": {"card_id": 100101, "turn": 47}}}

    monkeypatch.setattr(service, "_resume_active_career", lambda _req, _preset: resumed_result)
    monkeypatch.setattr(
        "backend.app.routers.careers.services.career_run._CareerLoop._rerun_session",
        lambda _loop: True,
    )
    monkeypatch.setattr(game_service, "reset_circuit", lambda _session: None)

    def unexpected_start(_req):
        raise AssertionError("active career resume must happen before starting a new career")

    monkeypatch.setattr(service, "start_career_from_request", unexpected_start)

    service.manage_career_loop(req, preset, initial_result)

    assert len(runner.start_calls) == 2
    assert runner.start_calls[0][0][2] is initial_result
    assert runner.start_calls[1][0][2] is resumed_result
