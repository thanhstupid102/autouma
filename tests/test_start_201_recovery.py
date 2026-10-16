import career_bot.delay as delay
from core.settings import Settings
import backend.app.domain.rank_point as rank_point

from tests._helpers import start_career_request


class Start201Client:
    """TP starts below required. recovery_tp 201s until login() refreshes the
    session; after relogin it tops TP up. Tracks call counts to prove the start
    flow relogins once instead of hammering recovery_tp."""

    def __init__(self):
        self.login_calls = 0
        self.recovery_calls = 0
        self.start_calls = []
        self.session_ok = False
        self.tp_info = {"current_tp": 20, "max_tp": 100, "max_recovery_time": 0}
        self.coin_info = {"fcoin": 0, "coin": 9999}
        self.item_map = {}

    def read_info(self):
        if not self.session_ok:
            raise Exception("API error 201 on read_info/index")
        return {"data": {"tp_info": self.tp_info}}

    def login(self):
        self.login_calls += 1
        self.session_ok = True
        self.tp_info = {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0}
        return {"data": {"tp_info": self.tp_info}}

    def recovery_tp(self, count=1):
        self.recovery_calls += 1
        if not self.session_ok:
            raise Exception("API error 201 on user/recovery_trainer_point")
        self.tp_info = {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0}
        return self.tp_info

    def refresh_cached_account_state(self, data):
        pass

    def pre_single_mode(self, exclude_viewer_ids=None):
        return {"data": {"summary_user_info_array": [], "support_card_data_array": []}}

    def call(self, endpoint, payload=None):
        return {"data": {"common_define": {"single_mode_trained_chara_rental_max_num": 5},
                         "single_mode_rental_succession_num": 0}}

    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"data": {"chara_info": {"turn": 1, "card_id": kwargs["card_id"],
                                        "scenario_id": kwargs["scenario_id"]}}}


def setup(monkeypatch, client):
    monkeypatch.setattr(rank_point, "support_map", {})
    monkeypatch.setattr(rank_point, "chara_map", {})
    monkeypatch.setattr(delay, "dna_sleep", lambda *a, **k: None)
    monkeypatch.setattr(delay, "backoff_sleep", lambda *a, **k: None)
    from uma_api.session import Session
    session = Session(name="test-acc", base_dir=str(Settings.BASE_DIR))
    session.client = client
    session.start_state = {
        "tp_info": dict(client.tp_info),
        "current_money": 12345,
        "succession_rank_point": 0,
    }
    return session


def test_start_relogins_once_on_201_then_starts(monkeypatch):
    client = Start201Client()
    session = setup(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is True
    assert client.login_calls == 1
    # Without relogin the loop would burn all 5 recovery attempts; with relogin it
    # recovers in at most a couple of calls.
    assert client.recovery_calls <= 2
    assert len(client.start_calls) == 1


def test_start_201_bails_clearly_when_relogin_does_not_help(monkeypatch):
    client = Start201Client()
    # login() refreshes the session but TP recovery still 201s (auth truly dead).
    def dead_login():
        client.login_calls += 1
        return {"data": {}}
    client.login = dead_login

    session = setup(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is False
    assert "201" in result["detail"]
    # Relogin attempted at most once; no hammering.
    assert client.login_calls <= 1
    assert client.recovery_calls <= 2
