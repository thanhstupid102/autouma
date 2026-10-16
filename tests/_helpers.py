"""Offline test doubles shared by more than one test module.

Moved verbatim out of ``tests/test_skills.py`` by the §13.1/A13 by-owner carve:
``CaptureClient`` is used by both the skill-purchase suite (``test_skills.py``)
and the runner finish/reroll suite; ``_make_session`` by both the rank-point
formula suite and the career-start service suite.

The follow-up A13 carve of ``tests/test_api_routes.py`` into per-router suites
(``test_routes_*.py``) added ``make_client`` / ``_repo_master_data_tree_state``
/ ``PROJECT_ROOT``, which every one of those suites needs.

``start_career_request`` and the three ``_*_command`` builders were byte-identical
copies living in two sibling suites each; they are shared from here now.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from core.settings import Settings
from backend.app.app import create_app
from backend.app.routers.careers.schemas.career import StartCareerRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CaptureClient:
    def __init__(self):
        self.payloads = []

    def gain_skills(self, gain_skill_info_array, current_turn):
        self.payloads.append((gain_skill_info_array, current_turn))
        return {"data": {"chara_info": {"turn": current_turn, "skill_point": 0}}}


def _make_session(name="test-acc"):
    """Build a per-account Session for exercising migrated helpers directly."""
    from uma_api.session import Session
    return Session(name=name, base_dir=str(Settings.BASE_DIR))


def make_client(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    return app, TestClient(app, client=("127.0.0.1", 40000))


def start_career_request():
    """The canonical MANT career-start request used by the start-recovery suites."""
    return StartCareerRequest(
        card_id=100101,
        support_card_ids=[30101, 30102, 30103, 30104, 30105],
        friend_viewer_id=111222333,
        friend_card_id=30106,
        parent_id_1=123,
        parent_id_2=456,
        scenario_id=4,
        deck_id=1,
        use_tp=30,
    )


def race_command(enabled=1):
    """A home-screen race command row."""
    return {"command_type": 4, "command_id": 401, "is_enable": enabled}


def train_command(command_id=101, enabled=1, gain=20, partners=None):
    """A home-screen training command row worth `gain` raw stat."""
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": enabled,
        "training_partner_array": partners or [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": gain}],
    }


def rest_command(enabled=1):
    """A home-screen rest command row."""
    return {"command_type": 7, "command_id": 701, "is_enable": enabled}


def _repo_master_data_tree_state():
    state = {}
    for directory in (PROJECT_ROOT / "data", PROJECT_ROOT / "assets"):
        for path in (directory, *directory.rglob("*")):
            stat = path.stat()
            state[path.relative_to(PROJECT_ROOT)] = (
                path.is_dir(),
                stat.st_size,
                stat.st_mtime_ns,
            )
    return state
