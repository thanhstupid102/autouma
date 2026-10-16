"""Discord career summaries expose local identities, never trainer names."""

import json
from types import SimpleNamespace

import pytest

from backend.app.routers.careers.schemas.career import RunCareerRequest
from backend.app.routers.careers.services.career_run import _CareerLoop
from backend.app.routers.careers.services.career_service import CareerService
from career_bot.engine import CareerRunner
from integrations.discord import notify
from uma_api import game_service
from uma_api.session import Session
import backend.app.domain.account_store as account_store
import backend.app.domain.career_selection as career_selection
import backend.app.domain.preset_runtime as preset_runtime


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _configure_webhook(state_root, **extra_config):
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "discord.json").write_text(
        json.dumps({"webhook_url": "https://discord.test/hook", **extra_config}),
        encoding="utf-8",
    )


def _capture_requests(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout=10):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    return requests


def _request_payload(request):
    assert request.get_header("Content-type") == "application/json"
    return json.loads(request.data)


def _started_runner(tmp_path, account="lewpie", user_info_cache=None):
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner._run_career = lambda *args, **kwargs: None
    runner.start(
        None,
        {"name": "privacy-test", "scenario_id": 4},
        {},
        account=account,
        user_info_cache=user_info_cache,
    )
    runner.thread.join(timeout=10)
    return runner


@pytest.mark.parametrize("status", ["finished", "error"])
def test_local_account_reaches_outgoing_summary(
    tmp_path, monkeypatch, status,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = _started_runner(tmp_path / "runner", account="lewpie")
    runner.report = {
        "status": status,
        "turns": [],
        "final_turn": 12,
        "error": {"type": "RuntimeError", "stack_trace": ""}
        if status == "error" else None,
    }

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        runner._build_notify_summary(),
    ) is True

    payload = _request_payload(requests[0])
    assert payload["embeds"][0]["description"].startswith(
        "👤 Account **lewpie** · ",
    )


class RecordingRunner:
    def __init__(self):
        self.start_calls = []

    def set_loop_info(self, current, target):
        pass

    def start(self, *args, **kwargs):
        self.start_calls.append(kwargs)

    def snapshot(self):
        return {"running": False, "status": "ok"}

    def stop(self):
        pass


START_RESULT = {
    "data": {
        "single_mode_start_common": {
            "chara_info": {"turn": 1, "card_id": 100101, "scenario_id": 2},
            "home_info": {"available_command_array": []},
        }
    }
}


def _make_launch(monkeypatch, tmp_path, trainer_name="Kaichō"):
    session = Session(name="local-slot", base_dir=str(tmp_path))
    session.user_info_cache = {"user_info": {"name": trainer_name}}
    session.client = SimpleNamespace(
        tp_info={},
        coin_info={},
        item_map={},
        reset_circuit=lambda: None,
    )
    session.runner = RecordingRunner()
    req = RunCareerRequest(
        card_id=100101,
        support_card_ids=[],
        friend_viewer_id=1,
        friend_card_id=2,
        parent_id_1=3,
        parent_id_2=4,
        scenario_id=2,
        run_count=1,
    )
    preset = {"name": "privacy-launch", "scenario_id": 2}
    service = CareerService(session)
    monkeypatch.setattr(
        service,
        "start_career_from_request",
        lambda _req: {"success": True, "result": START_RESULT},
    )
    monkeypatch.setattr(
        account_store, "apply_auto_delete_config", lambda _session: {},
    )
    monkeypatch.setattr(
        career_selection, "apply_deck_type_counts", lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        preset_runtime, "apply_runtime_bot_config", lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(game_service, "reset_circuit", lambda _session: None)
    return service, session, req, preset


@pytest.mark.parametrize("launch", ["single", "loop"])
def test_career_launch_only_passes_the_local_account(
    tmp_path, monkeypatch, launch,
):
    service, session, req, preset = _make_launch(monkeypatch, tmp_path)

    if launch == "single":
        service._launch_career_run(req, preset)
    else:
        req.run_count = 2
        _CareerLoop(service, req, preset, START_RESULT)._launch_runner()

    kwargs = session.runner.start_calls[0]
    assert kwargs["account"] == "local-slot"
    outward_kwargs = {
        key: value for key, value in kwargs.items()
        if key != "user_info_cache"
    }
    assert "Kaichō" not in repr(outward_kwargs)


def test_cached_trainer_name_cannot_reach_outgoing_payload(tmp_path, monkeypatch):
    service, session, req, preset = _make_launch(monkeypatch, tmp_path)
    service._launch_career_run(req, preset)
    start_kwargs = session.runner.start_calls[0]
    account = start_kwargs["account"]
    trainer_name = start_kwargs["user_info_cache"]["user_info"]["name"]

    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    runner = _started_runner(
        tmp_path / "runner",
        account=account,
        user_info_cache=start_kwargs["user_info_cache"],
    )
    runner.report = {"status": "finished", "turns": [], "final_turn": 1}

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        runner._build_notify_summary(),
    ) is True

    assert "local-slot" in requests[0].data.decode("utf-8")
    assert trainer_name not in requests[0].data.decode("utf-8")


def test_configured_account_name_overrides_local_account(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root, account_name="Operator Display")
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {"status": "finished", "account": "local-slot"},
    ) is True

    description = _request_payload(requests[0])["embeds"][0]["description"]
    assert description.startswith("👤 Account **Operator Display** · ")
    assert "local-slot" not in description


def test_empty_account_name_does_not_override_local_account(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root, account_name="   ")
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {"status": "finished", "account": "local-slot"},
    ) is True

    description = _request_payload(requests[0])["embeds"][0]["description"]
    assert description.startswith("👤 Account **local-slot** · ")


def test_summary_request_has_no_removed_branding(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {"status": "finished", "account": "local-slot"},
    ) is True

    request = requests[0]
    outgoing = b"\n".join([
        request.data,
        str(request.header_items()).encode("utf-8"),
    ])
    assert "footer" not in _request_payload(request)["embeds"][0]
    assert "Sweepy改二".encode("utf-8") not in outgoing
    assert b"Uma Musume Auto" not in outgoing
    assert b"umamusume-sweepy" not in outgoing


def test_live_monitor_keeps_functional_polling_footer():
    embed = notify._build_live_embed({"running": True})

    assert embed["footer"] == {"text": "Polling every 10s"}
