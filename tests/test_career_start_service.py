import career_bot.delay as delay
import backend.app.domain.rank_point as rank_point
from backend.app.routers.careers.schemas.career import RunCareerRequest, StartCareerRequest
from tests._helpers import _make_session


class StartCareer102Client:
    def __init__(self, rental_trained_chara_id=987654321, rental_shared_g1=False):
        self.start_calls = []
        self.load_career_calls = 0
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.rental_trained_chara_id = rental_trained_chara_id
        self.rental_shared_g1 = rental_shared_g1

    def read_info(self):
        return {
            "data": {
                "tp_info": {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0},
                "item_list": [
                    {"item_id": 59, "number": 12345},
                    {"item_id": 75, "number": 0},
                ],
            }
        }

    def refresh_cached_account_state(self, data):
        if data.get("tp_info"):
            self.tp_info = data["tp_info"]
        if data.get("coin_info"):
            self.coin_info = data["coin_info"]
        for key in ("item_list", "user_item_array", "user_item"):
            rows = data.get(key)
            if not isinstance(rows, list):
                continue
            seen_bottle = False
            for item in rows:
                iid = item.get("item_id")
                if iid is None:
                    continue
                for count_key in ("number", "num", "current_num", "item_num"):
                    if count_key in item:
                        self.item_map[int(iid)] = max(int(item.get(count_key) or 0), 0)
                        seen_bottle = seen_bottle or int(iid) == 32
                        break
            if not seen_bottle:
                self.item_map[32] = 0
            break

    def pre_single_mode(self, exclude_viewer_ids=None):
        return {
            "data": {
                "summary_user_info_array": [
                    {
                        "viewer_id": 659806586934,
                        "support_card_id": 30107,
                        "name": "rental friend",
                        "user_trained_chara": {
                            "trained_chara_id": self.rental_trained_chara_id,
                            "card_id": 100601,
                            "rank": 13,
                            "factor_id_array": [],
                        },
                    }
                ],
                "support_card_data_array": [],
                "succession_trained_chara_data": {
                    "succession_trained_chara_array": [{
                        "viewer_id": 659806586934,
                        "trained_chara_id": self.rental_trained_chara_id,
                        "card_id": 100601,
                        "win_saddle_id_array": [101, 102] if self.rental_shared_g1 else [],
                        "succession_chara_array": [
                            {
                                "position_id": 10,
                                "card_id": 100701,
                                "win_saddle_id_array": [101] if self.rental_shared_g1 else [],
                            },
                            {
                                "position_id": 20,
                                "card_id": 100801,
                                "win_saddle_id_array": [102] if self.rental_shared_g1 else [],
                            },
                        ],
                    }],
                },
            }
        }

    def call(self, endpoint, payload=None):
        assert endpoint == "load/index"
        return {
            "data": {
                "common_define": {"single_mode_trained_chara_rental_max_num": 5},
                "single_mode_rental_succession_num": 0,
            }
        }

    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        if kwargs.get("rental_viewer_id"):
            raise Exception("API error 102 on single_mode_free/start")
        return {"data": {"chara_info": {"turn": 1, "card_id": kwargs["card_id"], "scenario_id": kwargs["scenario_id"]}}}

    def load_career(self):
        self.load_career_calls += 1
        raise Exception("API error 102 on single_mode_free/load")


class StartCareer102Then201Client(StartCareer102Client):
    def __init__(self):
        super().__init__()
        self.login_calls = 0
        self.session_recovered = False

    def login(self):
        self.login_calls += 1
        self.session_recovered = True
        return self.read_info()

    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        if kwargs.get("rental_viewer_id"):
            raise Exception("API error 102 on single_mode_free/start")
        if not self.session_recovered:
            raise Exception("API error 201 on single_mode_free/start")
        return {"data": {"chara_info": {"turn": 1, "card_id": kwargs["card_id"], "scenario_id": kwargs["scenario_id"]}}}


class StartCareerEventClient(StartCareer102Client):
    def call(self, endpoint, payload=None):
        assert endpoint == "load/index"
        return {
            "data": {
                "single_mode_difficulty_info_array": [
                    {"difficulty_id": 1003, "open_difficulty_index": 4},
                ],
                "common_define": {"single_mode_trained_chara_rental_max_num": 5},
                "single_mode_rental_succession_num": 0,
            }
        }

    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        if kwargs.get("is_boost") and kwargs.get("use_tp") != 60:
            raise Exception("API error 2509 on single_mode_free/start: Boost TP mismatch")
        return {"data": {"chara_info": {"turn": 1, "card_id": kwargs["card_id"], "scenario_id": kwargs["scenario_id"]}}}


class StartCareer2509BoostClient(StartCareerEventClient):
    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        if kwargs.get("is_boost"):
            raise Exception("API error 2509 on single_mode_free/start: Boost unavailable")
        return {"data": {"chara_info": {"turn": 1, "card_id": kwargs["card_id"], "scenario_id": kwargs["scenario_id"]}}}


class StartCareerTpRecoveryClient(StartCareer102Client):
    def __init__(self, bottle_counts, stale_bottles=0):
        super().__init__()
        self.bottle_counts = list(bottle_counts)
        self.last_bottle_count = self.bottle_counts[0] if self.bottle_counts else 0
        self.item_map = {32: stale_bottles}
        self.bottle_calls = []
        self.carat_calls = []

    def read_info(self):
        bottles = self.bottle_counts.pop(0) if self.bottle_counts else self.last_bottle_count
        self.last_bottle_count = bottles
        rows = [
            {"item_id": 59, "num": 12345},
            {"item_id": 75, "current_num": 0},
        ]
        if bottles is not None:
            rows.append({"item_id": 32, "num": bottles})
        return {
            "data": {
                "tp_info": {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
                "coin_info": {"coin": 150, "fcoin": 0},
                "item_list": rows,
            }
        }

    def use_recovery_item(self, item_id, item_num):
        self.bottle_calls.append((item_id, item_num))
        self.item_map[int(item_id)] = max(int(self.item_map.get(int(item_id), 0)) - int(item_num), 0)
        self.tp_info = {"current_tp": 30 * int(item_num), "max_tp": 100, "max_recovery_time": 0}
        return self.tp_info

    def recovery_tp(self, count=1):
        self.carat_calls.append(count)
        self.tp_info = {"current_tp": 30 * int(count), "max_tp": 100, "max_recovery_time": 0}
        return self.tp_info



def setup_start_career_test(monkeypatch, client):
    monkeypatch.setattr(rank_point, "support_map", {})
    monkeypatch.setattr(rank_point, "chara_map", {})
    monkeypatch.setattr(delay, "dna_sleep", lambda *args, **kwargs: None)
    session = _make_session()
    session.client = client
    return session


def start_request():
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
        rental_friend_viewer_id=659806586934,
    )


def test_run_start_forwards_preset_running_style(monkeypatch):
    client = StartCareer102Client()
    session = setup_start_career_test(monkeypatch, client)
    session.last_preset = {"running_style": 3}
    req = RunCareerRequest(
        card_id=100101,
        support_card_ids=[30101, 30102, 30103, 30104, 30105],
        friend_viewer_id=111222333,
        friend_card_id=30106,
        parent_id_1=123,
        parent_id_2=456,
        scenario_id=4,
        deck_id=1,
        use_tp=30,
        preset_name="style-test",
    )

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(req)

    assert result["success"] is True
    assert client.start_calls[0]["running_style"] == 3


def test_start_102_with_rental_retries_without_rental_before_resume_recovery(monkeypatch):
    client = StartCareer102Client()
    session = setup_start_career_test(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert len(client.start_calls) == 2
    assert client.start_calls[0]["rental_viewer_id"] == 659806586934
    assert client.start_calls[0]["rental_trained_chara_id"] == 987654321
    assert client.start_calls[0]["parent_id_2"] == 0
    assert client.start_calls[1]["rental_viewer_id"] == 0
    assert client.start_calls[1]["rental_trained_chara_id"] == 0
    assert client.start_calls[1]["parent_id_2"] == 456
    assert client.load_career_calls == 0


def test_start_rental_rank_point_uses_rental_parent_then_owned_fallback(monkeypatch):
    client = StartCareer102Client()
    session = setup_start_career_test(monkeypatch, client)
    session.parent_cards = {
        123: [100201],
        456: [100301],
    }
    session.parent_g1_wins = {123: 3, 456: 6}
    monkeypatch.setattr(rank_point, "succession_relation_points", {
        1: 10,
        2: 20,
        3: 40,
        4: 30,
        5: 50,
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_members", {
        1001: {1, 2, 4},
        1002: {1, 3, 5},
        1003: {2, 3},
        1006: {4, 5},
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_loaded", True, raising=False)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert client.start_calls[0]["succession_rank_point"] == 93
    assert client.start_calls[1]["succession_rank_point"] == 79
    rental_key = (659806586934, 987654321)
    assert session.rental_parent_cards[rental_key][0] == 100601


def test_start_rental_rank_point_keeps_colliding_owned_parent_for_fallback(monkeypatch):
    client = StartCareer102Client(rental_trained_chara_id=456, rental_shared_g1=True)
    session = setup_start_career_test(monkeypatch, client)
    owned_parent_2_cards = [100301, 100401, 100501]
    session.parent_cards = {
        123: [100201],
        456: owned_parent_2_cards.copy(),
    }
    session.parent_g1_wins = {123: 3, 456: 9}
    monkeypatch.setattr(rank_point, "g1_win_saddle_ids", {101, 102}, raising=False)
    monkeypatch.setattr(
        rank_point, "win_saddle_groups", {101: 10, 102: 20}, raising=False
    )
    monkeypatch.setattr(
        rank_point, "win_saddle_types", {101: 3, 102: 3}, raising=False
    )
    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_points", {
        1: 10,
        2: 20,
        3: 40,
        4: 30,
        5: 50,
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_members", {
        1001: {1, 2, 4},
        1002: {1, 3, 5},
        1003: {2, 3},
        1006: {4, 5},
    }, raising=False)
    monkeypatch.setattr(rank_point, "succession_relation_loaded", True, raising=False)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert client.start_calls[0]["rental_trained_chara_id"] == 456
    assert client.start_calls[0]["succession_rank_point"] == 99
    assert client.start_calls[1]["rental_trained_chara_id"] == 0
    assert client.start_calls[1]["succession_rank_point"] == 82
    assert session.parent_cards[456] == owned_parent_2_cards
    assert session.parent_g1_wins[456] == 9
    rental_key = (659806586934, 456)
    assert session.rental_parent_cards[rental_key][0] == 100601
    assert session.rental_parent_g1_wins[rental_key] == 6


def test_start_102_relogs_before_retry_when_session_becomes_201(monkeypatch):
    client = StartCareer102Then201Client()
    session = setup_start_career_test(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert client.login_calls == 1
    assert len(client.start_calls) == 2
    assert client.start_calls[0]["rental_viewer_id"] == 659806586934
    assert client.start_calls[1]["rental_viewer_id"] == 0


def test_start_event_boost_sends_sixty_tp(monkeypatch):
    client = StartCareerEventClient()
    session = setup_start_career_test(monkeypatch, client)
    session.selection = {
        "event": {"enabled": True, "level": 4, "boost": True},
    }

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert len(client.start_calls) == 1
    assert client.start_calls[0]["difficulty_id"] == 1003
    assert client.start_calls[0]["difficulty"] == 404
    assert client.start_calls[0]["is_boost"] == 1
    assert client.start_calls[0]["use_tp"] == 60
    assert session.selection["event"]["enabled"] is True
    assert session.selection["event"]["boost"] is True


def test_start_event_without_boost_keeps_thirty_tp(monkeypatch):
    client = StartCareerEventClient()
    session = setup_start_career_test(monkeypatch, client)
    session.selection = {
        "event": {"enabled": True, "level": 4, "boost": False},
    }

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert len(client.start_calls) == 1
    assert client.start_calls[0]["difficulty_id"] == 1003
    assert client.start_calls[0]["difficulty"] == 404
    assert client.start_calls[0]["is_boost"] == 0
    assert client.start_calls[0]["use_tp"] == 30
    assert session.selection["event"]["enabled"] is True
    assert session.selection["event"]["boost"] is False


def test_start_prefers_tp_bottle_when_live_count_positive(monkeypatch):
    client = StartCareerTpRecoveryClient([2])
    session = setup_start_career_test(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == []
    assert session.start_state["tp_bottle_count"] == 1
    assert client.start_calls[0]["use_tp"] == 30


def test_start_falls_back_to_carat_when_live_bottle_count_zero(monkeypatch):
    client = StartCareerTpRecoveryClient([0], stale_bottles=3)
    session = setup_start_career_test(monkeypatch, client)

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert client.bottle_calls == []
    assert client.carat_calls == [1]
    assert session.start_state["tp_bottle_count"] == 0
    assert client.item_map[32] == 0


def test_start_2509_boost_retries_same_event_without_boost(monkeypatch):
    client = StartCareer2509BoostClient()
    session = setup_start_career_test(monkeypatch, client)
    session.selection = {
        "event": {"enabled": True, "level": 4, "boost": True},
    }

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(start_request())

    assert result["success"] is True
    assert len(client.start_calls) == 2
    assert client.start_calls[0]["difficulty_id"] == 1003
    assert client.start_calls[0]["difficulty"] == 404
    assert client.start_calls[0]["is_boost"] == 1
    assert client.start_calls[0]["use_tp"] == 60
    assert client.start_calls[1]["difficulty_id"] == 1003
    assert client.start_calls[1]["difficulty"] == 404
    assert client.start_calls[1]["is_boost"] == 0
    assert client.start_calls[1]["use_tp"] == 30
    assert session.selection["event"]["enabled"] is True
    assert session.selection["event"]["boost"] is False


# --- fix: the rental ladder must report the codes that actually happened -----
# A 501-with-rental start whose no-rental fallback keeps failing 201 falls into
# the career-load recovery path. The envelope used to hardcode "error 102" on
# that run; it must carry the real codes instead. The genuine-102 path keeps
# its wording verbatim.

class _SimpleReq:
    def __init__(self):
        self.card_id = 100101
        self.support_card_ids = [1, 2, 3, 4, 5]
        self.friend_viewer_id = 111
        self.friend_card_id = 30106
        self.parent_id_1 = 123
        self.parent_id_2 = 456
        self.scenario_id = 4
        self.deck_id = 1
        self.difficulty_id = 0
        self.difficulty = 0
        self.is_boost = 0
        self.boost_story_event_id = 0


class _Rental501Client:
    """No login attr on purpose: session refreshes are skipped, so the original
    501 survives as start_err while the fallbacks keep 201ing."""

    def __init__(self):
        self.start_errors = [
            Exception("API error 501 on single_mode_free/start"),
            Exception("API error 201 on single_mode_free/start"),
            Exception("API error 201 on single_mode_free/start"),
        ]
        self.start_calls = []

    def start_career(self, **kwargs):
        self.start_calls.append(kwargs)
        raise self.start_errors[min(len(self.start_calls) - 1, len(self.start_errors) - 1)]

    def load_career(self):
        raise Exception("API error 201 on single_mode/load")


def _attempts_for(monkeypatch, client):
    from types import SimpleNamespace
    from backend.app.routers.careers.services import career_start as cs

    monkeypatch.setattr(
        rank_point, "selected_succession_rank_point_components",
        lambda session, req, rental_parent_2=None: {"computed": 0},
    )
    session = SimpleNamespace(client=client)
    return cs._StartAttempts(
        session=session,
        client=client,
        req=_SimpleReq(),
        tp_info={"current_tp": 100},
        current_money=1000,
        configured_running_style=0,
    )


def test_rental_501_then_201_fallback_reports_real_codes(monkeypatch):
    attempts = _attempts_for(monkeypatch, _Rental501Client())

    result = attempts.run(999, 888, initial_components={"computed": 0})

    assert result["success"] is False
    assert "error 501/201" in result["detail"]
    assert "error 102" not in result["detail"]


# --- pin: the 2509 boost downgrade touches is_boost ONLY --------------------
# `boost_story_event_id` is a SIBLING of `selected_difficulty_info` in the
# start_chara payload (uma_api/routes.py:160-190), not a child of its
# `is_boost` flag, and the live-client capture in docs/unity_cup.md sends
# `boost_story_event_id: 1016` together with `"is_boost": 0`. So leaving the
# story id populated on a downgraded retry is the documented wire shape, not a
# leak. It is also unreachable from this app: the field defaults to 0 in both
# request schemas, the only body builder hardcodes 0
# (frontend/src/components/dashboard/runBody.ts), and no production line ever
# assigns it -- these tests therefore build the non-zero state by hand.

def test_disable_event_boost_leaves_the_boost_story_event_id_alone(monkeypatch):
    from types import SimpleNamespace
    from backend.app.routers.careers.services import career_start as cs

    req = _SimpleReq()
    req.is_boost = 1
    req.boost_story_event_id = 4022
    session = SimpleNamespace(client=None, selection={"event": {"enabled": True, "boost": True}})
    attempts = cs._StartAttempts(
        session=session,
        client=None,
        req=req,
        tp_info={},
        current_money=0,
        configured_running_style=0,
    )

    attempts.disable_event_boost()

    assert req.is_boost == 0
    assert session.selection["event"]["boost"] is False
    assert req.boost_story_event_id == 4022


def test_2509_downgrade_retry_still_forwards_the_boost_story_event_id(monkeypatch):
    client = StartCareer2509BoostClient()
    session = setup_start_career_test(monkeypatch, client)
    session.selection = {
        "event": {"enabled": True, "level": 4, "boost": True},
    }
    req = start_request()
    req.boost_story_event_id = 4022

    from backend.app.routers.careers.services.career_service import CareerService

    result = CareerService(session).start_career_from_request(req)

    assert result["success"] is True
    assert len(client.start_calls) == 2
    assert client.start_calls[0]["is_boost"] == 1
    assert client.start_calls[0]["boost_story_event_id"] == 4022
    assert client.start_calls[1]["is_boost"] == 0
    assert client.start_calls[1]["boost_story_event_id"] == 4022
    assert req.boost_story_event_id == 4022


def test_non_rental_102_envelope_keeps_its_wording(monkeypatch):
    class _Plain102Client:
        def __init__(self):
            self.start_calls = []

        def start_career(self, **kwargs):
            self.start_calls.append(kwargs)
            raise Exception("API error 102 on single_mode_free/start")

        def load_career(self):
            raise Exception("API error 102 on single_mode/load")

    monkeypatch.setattr(
        rank_point, "probe_succession_rank_point",
        lambda session, req, components, attempt: None,
    )
    attempts = _attempts_for(monkeypatch, _Plain102Client())

    result = attempts.run(0, 0, initial_components={"computed": 0})

    assert result["success"] is False
    assert "Career start blocked (error 102) and no resumable career was found." in result["detail"]
