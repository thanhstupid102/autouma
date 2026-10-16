import json
import logging

from core.settings import Settings
import backend.app.domain.account_status as account_status
import backend.app.domain.rank_point as rank_point
import uma_data
from backend.app.routers.careers.schemas.career import StartCareerRequest


class DirectionalStartClient:
    def __init__(
        self,
        computed,
        accepted=None,
        *,
        load_error_code=102,
        existing_career=None,
        probe_error_code=None,
        all_low=False,
        missing_boundary=False,
    ):
        self.computed = computed
        self.accepted = accepted
        self.load_error_code = load_error_code
        self.existing_career = existing_career
        self.probe_error_code = probe_error_code
        self.all_low = all_low
        self.missing_boundary = missing_boundary
        self.start_calls = []
        self.load_career_calls = 0
        self.reset_circuit_calls = 0
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}

    def read_info(self):
        return {
            "data": {
                "tp_info": {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0},
                "coin_info": {"coin": 0, "fcoin": 0},
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
        for item in data.get("item_list") or []:
            self.item_map[int(item["item_id"])] = int(item.get("number") or 0)

    def pre_single_mode(self, exclude_viewer_ids=None):
        return {"data": {}}

    def reset_circuit(self):
        self.reset_circuit_calls += 1

    def start_career(self, **kwargs):
        value = int(kwargs["succession_rank_point"])
        self.start_calls.append(kwargs)
        if len(self.start_calls) > 1 and self.probe_error_code is not None:
            raise Exception(
                f"API error {self.probe_error_code} on single_mode_free/start"
            )
        if self.all_low:
            raise Exception("API error 102 on single_mode_free/start")
        if self.missing_boundary:
            code = 102 if value <= self.computed + 4094 else 1052
            raise Exception(f"API error {code} on single_mode_free/start")
        if value < self.accepted:
            raise Exception("API error 102 on single_mode_free/start")
        if value > self.accepted:
            raise Exception("API error 1052 on single_mode_free/start")
        return {
            "data": {
                "chara_info": {
                    "turn": 1,
                    "card_id": kwargs["card_id"],
                    "scenario_id": kwargs["scenario_id"],
                    "accepted_rank_point": value,
                }
            }
        }

    def load_career(self):
        self.load_career_calls += 1
        if self.existing_career is not None:
            return self.existing_career
        raise Exception(
            f"API error {self.load_error_code} on single_mode_free/load"
        )


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
        rental_friend_viewer_id=0,
    )


def setup_start(monkeypatch, client, tmp_path):
    from uma_api.session import Session

    sleeps = []
    monkeypatch.setattr(rank_point, "support_map", {})
    monkeypatch.setattr(rank_point, "chara_map", {})
    monkeypatch.setattr(rank_point, "succession_relation_loaded", False)
    monkeypatch.setattr(rank_point, "rank_point_master_mdb_mtime_ns", 1)
    monkeypatch.setattr(uma_data, "master_mdb_mtime_ns", lambda _base: 1)
    monkeypatch.setattr(rank_point, "dna_sleep", lambda *args: sleeps.append(args))
    monkeypatch.setattr(
        rank_point, "RANKPOINT_PROBE_LOG_PATH", tmp_path / "rankpoint_probes.jsonl"
    )
    session = Session(name="rankpoint-probe", base_dir=str(Settings.BASE_DIR))
    session.client = client
    session.parent_cards = {123: [100201], 456: [100301]}
    session.parent_g1_wins = {123: 12, 456: 18}
    return session, sleeps


def test_rankpoint_probe_converges_persists_and_returns_normal_start_result(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.INFO)
    computed = 30
    accepted = computed + 777
    client = DirectionalStartClient(computed, accepted)
    session, sleeps = setup_start(monkeypatch, client, tmp_path)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started["success"] is True
    assert started["result"]["data"]["chara_info"]["accepted_rank_point"] == accepted
    sent_values = [call["succession_rank_point"] for call in client.start_calls]
    assert sent_values[:4] == [computed, computed + 64, computed + 256, computed + 1024]
    assert sent_values[-1] == accepted
    assert len(sent_values) - 1 <= rank_point.RANKPOINT_PROBE_MAX_ATTEMPTS
    assert client.load_career_calls == 1
    assert client.reset_circuit_calls == len(sent_values) - 1
    assert sleeps.count((3.5, 5.0)) == len(sent_values) - 1

    lines = (tmp_path / "rankpoint_probes.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["card_id"] == 100101
    assert record["parent_1_id"] == 123
    assert record["parent_1_card_id"] == 100201
    assert record["parent_2_id"] == 456
    assert record["parent_2_card_id"] == 100301
    assert record["rental_viewer_id"] == 0
    assert record["computed_value"] == computed
    assert record["accepted_value"] == accepted
    assert record["delta"] == accepted - computed
    assert record["components"]["relation_pairs"] == {
        "t_p1": 0,
        "t_p2": 0,
        "p1_p2": 0,
    }
    assert record["components"]["relation_triples"] == {
        "t_p1_gp10": 0,
        "t_p1_gp20": 0,
        "t_p2_gp10": 0,
        "t_p2_gp20": 0,
    }
    assert record["components"]["g1_bonuses"] == {
        "parent_1": 12,
        "parent_2": 18,
        "parent_1_to_parent_2": 0,
    }

    account, chara_info = account_status.apply_career_result(session, started["result"])
    assert chara_info["accepted_rank_point"] == accepted
    assert account["career"]["active"] is True

    assert (
        f"[RANKPOINT] server accepted {accepted} (computed {computed}, "
        f"delta {accepted - computed})"
    ) in caplog.text


def test_rankpoint_probe_respects_attempt_cap(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    client = DirectionalStartClient(30, all_low=True)
    session, _ = setup_start(monkeypatch, client, tmp_path)
    monkeypatch.setattr(rank_point, "RANKPOINT_PROBE_MAX_ATTEMPTS", 3)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started["success"] is False
    assert len(client.start_calls) == 4  # original request + three probes
    assert client.reset_circuit_calls == 3
    assert not (tmp_path / "rankpoint_probes.jsonl").exists()
    assert "probe exhausted 3-attempt cap" in caplog.text


def test_rankpoint_probe_aborts_on_foreign_probe_error(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    client = DirectionalStartClient(30, accepted=31, probe_error_code=208)
    session, _ = setup_start(monkeypatch, client, tmp_path)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started["success"] is False
    assert len(client.start_calls) == 2
    assert client.reset_circuit_calls == 1
    assert not (tmp_path / "rankpoint_probes.jsonl").exists()
    assert "non-directional error 208" in caplog.text


def test_rankpoint_probe_does_not_run_when_load_error_is_not_102(
    monkeypatch, tmp_path
):
    client = DirectionalStartClient(30, accepted=31, load_error_code=205)
    session, sleeps = setup_start(monkeypatch, client, tmp_path)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started["success"] is False
    assert len(client.start_calls) == 1
    assert client.reset_circuit_calls == 0
    assert (3.5, 5.0) not in sleeps
    assert not (tmp_path / "rankpoint_probes.jsonl").exists()


def test_existing_career_resume_stays_ahead_of_rankpoint_probe(monkeypatch, tmp_path):
    resumed = {
        "data": {
            "chara_info": {"turn": 2, "card_id": 100101, "scenario_id": 4}
        }
    }
    client = DirectionalStartClient(30, accepted=31, existing_career=resumed)
    session, sleeps = setup_start(monkeypatch, client, tmp_path)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started == {"success": True, "result": resumed}
    assert len(client.start_calls) == 1
    assert client.reset_circuit_calls == 0
    assert (3.5, 5.0) not in sleeps
    assert not (tmp_path / "rankpoint_probes.jsonl").exists()


def test_rankpoint_probe_never_exceeds_default_sixteen_attempts(
    monkeypatch, tmp_path
):
    client = DirectionalStartClient(30, missing_boundary=True)
    session, _ = setup_start(monkeypatch, client, tmp_path)

    from backend.app.routers.careers.services.career_service import CareerService

    started = CareerService(session).start_career_from_request(start_request())

    assert started["success"] is False
    assert len(client.start_calls) == 1 + rank_point.RANKPOINT_PROBE_MAX_ATTEMPTS
    assert client.reset_circuit_calls == rank_point.RANKPOINT_PROBE_MAX_ATTEMPTS


def test_master_mtime_reload_runs_once_for_each_change(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    state = {"mtime": 10}
    calls = {"relation": 0, "g1": 0}

    def load_relation():
        calls["relation"] += 1
        return True

    def load_g1():
        calls["g1"] += 1
        return True

    monkeypatch.setattr(rank_point, "rank_point_master_mdb_mtime_ns", 10)
    monkeypatch.setattr(
        uma_data, "master_mdb_mtime_ns", lambda _base: state["mtime"]
    )
    monkeypatch.setattr(rank_point, "load_succession_relation_data", load_relation)
    monkeypatch.setattr(rank_point, "load_g1_win_saddle_data", load_g1)

    assert rank_point.reload_rank_point_master_data_if_changed() is False
    state["mtime"] = 20
    assert rank_point.reload_rank_point_master_data_if_changed() is True
    assert rank_point.reload_rank_point_master_data_if_changed() is False
    state["mtime"] = 30
    assert rank_point.reload_rank_point_master_data_if_changed() is True
    assert rank_point.reload_rank_point_master_data_if_changed() is False

    assert calls == {"relation": 2, "g1": 2}
    assert caplog.text.count(
        "master.mdb changed -> reloaded relation/G1 data"
    ) == 2
