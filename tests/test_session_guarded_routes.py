"""Backend guard characterization: routes that must not touch a live client.

Carved verbatim out of ``tests/test_201_resilience.py`` by the §13.1/A13
by-owner split -- this half owns the backend/uma_api session guards: while the
runner is active, login/start/action must short-circuit and the friends route
must serve its dashboard cache, all without calling a single client method.
"""
import asyncio

from backend.app.routers.auth.schemas.auth import LoginRequest
from backend.app.routers.careers.schemas.career import StartCareerRequest


class RunningRunner:
    def snapshot(self):
        return {"running": True}


class IdleRunner:
    def snapshot(self):
        return {"running": False}


class TouchClient:
    def __init__(self):
        self.touched = False

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            self.touched = True
            raise AssertionError(f"client method touched: {name}")
        return fail


class RunningSession:
    def __init__(self, dashboard_data=None):
        self.runner = RunningRunner()
        self.client = TouchClient()
        self.dashboard_data = dashboard_data
        self.account = {}
        self.pending_game_auth_config = {}

    def loop_active(self):
        return False


class LiveFriendClient:
    def __init__(self):
        self.pre_single_mode_calls = []
        self.load_index_calls = 0

    def pre_single_mode(self, exclude_viewer_ids=None):
        self.pre_single_mode_calls.append(list(exclude_viewer_ids or []))
        return {
            "data": {
                "summary_user_info_array": [
                    {
                        "viewer_id": 123,
                        "support_card_id": 30107,
                        "name": "idle friend",
                        "user_trained_chara": {
                            "trained_chara_id": 987654321,
                            "card_id": 100601,
                            "factor_id_array": [],
                        },
                    }
                ],
                "support_card_data_array": [],
            }
        }

    def call(self, endpoint, payload=None):
        assert endpoint == "load/index"
        self.load_index_calls += 1
        return {
            "data": {
                "common_define": {"single_mode_trained_chara_rental_max_num": 5},
                "single_mode_rental_succession_num": 0,
            }
        }


class ActiveIdleSession:
    def __init__(self):
        self.runner = IdleRunner()
        self.client = LiveFriendClient()
        self.dashboard_data = None
        self.account = {"career": {"active": True}}
        self.start_state = {}
        self.parent_cards = {}
        self.parent_g1_wins = {}
        self.rental_parent_cards = {}
        self.rental_parent_g1_wins = {}

    def loop_active(self):
        return False


def test_guarded_endpoints_return_running_response_without_touching_client():
    session = RunningSession()
    expected = {"success": False, "detail": "Career is running — stop it first."}

    from backend.app.routers.auth.services.auth_service import AuthService

    login_res = asyncio.run(AuthService(session).login(LoginRequest()))
    from backend.app.routers.careers.services.career_service import CareerService

    start_res = asyncio.run(CareerService(session).start(StartCareerRequest(
        card_id=100101,
        support_card_ids=[30101, 30102, 30103, 30104, 30105],
        friend_viewer_id=111,
        friend_card_id=30106,
        parent_id_1=1,
        parent_id_2=2,
        scenario_id=4,
        deck_id=1,
    )))

    action_res = CareerService(session).action(
        command_type=1,
        command_id=101,
        current_turn=1,
        current_vital=100,
    )

    assert login_res == {**expected, "state": "failed"}
    assert start_res == expected
    assert action_res == expected
    assert session.client.touched is False


def test_friends_endpoint_serves_cache_while_runner_active_without_touching_client():
    cached = {
        "friends": [{"viewer_id": 123}],
        "friend_exclude_ids": [456],
        "rental_quota": {"used": 1, "max": 5, "remaining": 4},
    }
    session = RunningSession(dashboard_data=cached)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).friends([])

    assert result["success"] is True
    assert result["friends"] == cached["friends"]
    assert result["exclude_viewer_ids"] == [456]
    assert result["source"] == "cache"
    assert session.client.touched is False


def test_friends_endpoint_fetches_live_when_career_active_but_runner_idle():
    session = ActiveIdleSession()

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).friends([])

    assert result["success"] is True
    assert result["source"] == "refresh"
    assert result["friends"][0]["viewer_id"] == 123
    assert session.client.pre_single_mode_calls == [[]]
    assert session.client.load_index_calls == 1
    assert session.rental_parent_cards[(123, 987654321)][0] == 100601
