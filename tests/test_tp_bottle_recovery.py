import career_bot.delay as delay
from uma_data import tp_cost
from core.settings import Settings
import backend.app.domain.account_status as account_status
import backend.app.domain.rank_point as rank_point

from tests._helpers import start_career_request

TP_BOTTLE = 32
# An active half-TP career-start campaign (master.mdb campaign_data, target_id=0
# means every scenario). effect_value_1/use_tp is the absolute discounted cost.
HALF_TP_CAMPAIGN = {"target_id": 0, "use_tp": 15, "start_time": 100, "end_time": 200}
SERVER_TIME = 150  # inside the campaign window above


def make_account_cache_client(bottles=5):
    from uma_api.client import UmaClient

    client = UmaClient.__new__(UmaClient)
    client.cached_load_data = {}
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {TP_BOTTLE: bottles}
    return client


def test_partial_item_list_does_not_wipe_cached_tp_bottles():
    client = make_account_cache_client(5)

    client.refresh_cached_account_state({"user_item_array": []})
    client.refresh_cached_account_state({"item_list": [{"item_id": 59, "number": 12345}]})

    assert client.item_map[TP_BOTTLE] == 5


def test_full_inventory_snapshot_updates_cached_tp_bottle_count():
    client = make_account_cache_client(5)

    client.refresh_cached_account_state({"item_list": [{"item_id": TP_BOTTLE, "number": 3}]})
    assert client.item_map[TP_BOTTLE] == 3

    client.refresh_cached_account_state({"item_list": [{"item_id": TP_BOTTLE, "number": 0}]})
    assert client.item_map[TP_BOTTLE] == 0


def test_partial_start_items_do_not_wipe_shared_tp_bottle_cache():
    from types import SimpleNamespace

    session = SimpleNamespace(
        user_info_cache={"tp_bottle_count": 5, "item_map": {TP_BOTTLE: 5}},
        start_state={"tp_bottle_count": 5},
    )

    account_status.update_start_state(session, {"user_item_array": []})

    assert session.user_info_cache["tp_bottle_count"] == 5
    assert session.user_info_cache["item_map"][TP_BOTTLE] == 5
    assert session.start_state["tp_bottle_count"] == 5


def test_recovery_item_partial_response_decrements_cached_count():
    client = make_account_cache_client(5)
    client.call = lambda endpoint, payload: {
        "data": {
            "user_item_array": [],
            "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
        }
    }

    client.use_recovery_item(TP_BOTTLE, 1)

    assert client.item_map[TP_BOTTLE] == 4


class BottleClient:
    """Has TP bottles in item_map. use_recovery_item restores +30 TP each and
    decrements the bottle count; recovery_tp (carat) is the fallback."""

    def __init__(self, bottles=5, start_tp=20):
        self.item_map = {TP_BOTTLE: bottles}
        self.tp_info = {"current_tp": start_tp, "max_tp": 100, "max_recovery_time": 0}
        self.coin_info = {"fcoin": 0, "coin": 9999}
        # The only client-side inputs the start-cost policy reads now that it
        # lives in uma_data.tp_cost instead of on the client.
        self.last_servertime = SERVER_TIME
        self.current_scenario_id = 4
        self.bottle_calls = 0
        self.carat_calls = 0
        self.start_calls = []

    def read_info(self):
        return {"data": {"tp_info": self.tp_info}}

    def use_recovery_item(self, item_id=TP_BOTTLE, item_num=1):
        assert item_id == TP_BOTTLE, "must only auto-use the plain TP bottle"
        if self.item_map.get(TP_BOTTLE, 0) <= 0:
            raise Exception("API error: no item")
        self.bottle_calls += 1
        self.item_map[TP_BOTTLE] -= 1
        self.tp_info = dict(self.tp_info)
        self.tp_info["current_tp"] = min(100, self.tp_info["current_tp"] + 30)
        return self.tp_info

    def recovery_tp(self, count=1):
        self.carat_calls += 1
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


def setup(monkeypatch, client, campaigns=()):
    # Drive the real career-start TP resolver off injected campaign rows: there is
    # no master.mdb in this checkout, and the memo is process-wide.
    tp_cost._CAMPAIGN_CACHE = None
    monkeypatch.setattr(tp_cost, "load_active_campaigns", lambda base_dir=None: list(campaigns))
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


def test_uses_tp_bottle_before_carat(monkeypatch):
    client = BottleClient(bottles=5, start_tp=20)
    session = setup(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is True
    assert client.bottle_calls == 1   # 20 -> 50 covers the 30 needed
    assert client.carat_calls == 0    # never touched carats
    assert client.item_map[TP_BOTTLE] == 4
    assert len(client.start_calls) == 1


def test_falls_back_to_carat_when_no_bottles(monkeypatch):
    client = BottleClient(bottles=0, start_tp=20)
    session = setup(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is True
    assert client.bottle_calls == 0
    assert client.carat_calls == 1    # no bottles -> carat fallback
    assert len(client.start_calls) == 1


def test_campaign_cost_normal_start_requires_and_sends_15(monkeypatch):
    client = BottleClient(bottles=0, start_tp=14)
    session = setup(monkeypatch, client, campaigns=[HALF_TP_CAMPAIGN])

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is True
    assert client.carat_calls == 1   # 14 TP is short of the discounted 15
    assert client.start_calls[0]["use_tp"] == 15


def test_campaign_cost_boost_start_requires_and_sends_30(monkeypatch):
    client = BottleClient(bottles=0, start_tp=29)
    session = setup(monkeypatch, client, campaigns=[HALF_TP_CAMPAIGN])
    req = start_career_request()
    req.is_boost = 1

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(req)

    assert result["success"] is True
    assert client.carat_calls == 1
    assert client.start_calls[0]["use_tp"] == 30   # boost is 2x the campaign cost


def test_campaign_targeting_another_scenario_keeps_full_cost(monkeypatch):
    # target_id=2 (Unity Cup) while the request starts scenario 4 -> no discount.
    # This is what proves career_start really threads req.scenario_id into the resolver.
    campaign = {"target_id": 2, "use_tp": 15, "start_time": 100, "end_time": 200}
    client = BottleClient(bottles=0, start_tp=40)
    session = setup(monkeypatch, client, campaigns=[campaign])

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_career_request())

    assert result["success"] is True
    assert client.carat_calls == 0   # 40 TP already covers the full 30
    assert client.start_calls[0]["use_tp"] == 30
