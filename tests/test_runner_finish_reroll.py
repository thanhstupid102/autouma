import pathlib

import pytest

from career_bot.engine import CareerRunner, RunFatalError
from career_bot.skills import SkillBuyer
from tests._helpers import CaptureClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


class FinishClient(CaptureClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        return {
            "data": {
                "chara_info": {
                    "turn": current_turn,
                    "state": 3,
                    "playing_state": 1,
                    "skill_point": 345,
                    "skill_array": [],
                    "skill_tips_array": [
                        {"group_id": 20124, "rarity": 1, "level": 1},
                        {"group_id": 20152, "rarity": 1, "level": 4},
                        {"group_id": 20013, "rarity": 1, "level": 1},
                        {"group_id": 20014, "rarity": 1, "level": 1},
                    ],
                }
            }
        }

    def gain_skills(self, gain_skill_info_array, current_turn):
        self.calls.append(("gain_skills", current_turn))
        return super().gain_skills(gain_skill_info_array, current_turn)

    def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=0):
        self.calls.append(("finish_career", current_turn, factor_lottery_id))
        return {"data": {"single_mode_finish_common": {}}}


def test_finish_flow_clears_active_race_before_buying_skills():
    runner = CareerRunner(ROOT)
    client = FinishClient()
    state = {
        "data": {
            "race_start_info": {"program_id": 2512},
            "chara_info": {
                "turn": 78,
                "state": 3,
                "playing_state": 5,
                "skill_point": 345,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": 20124, "rarity": 1, "level": 1},
                    {"group_id": 20152, "rarity": 1, "level": 4},
                    {"group_id": 20013, "rarity": 1, "level": 1},
                    {"group_id": 20014, "rarity": 1, "level": 1},
                ],
            },
        }
    }

    runner._finish_career_flow(client, None, state, {"learn_skill_threshold": 0}, 78)

    assert [call[0] for call in client.calls] == ["race_out", "gain_skills", "finish_career"]
    assert len(client.payloads) == 1
    assert client.payloads[0][1] == 78


def _finish_state(factor_ids):
    return {"data": {"single_mode_finish_common": {
        "trained_chara_id": 123,
        "trained_chara": [{
            "trained_chara_id": 123,
            "factor_info_array": [{"factor_id": fid} for fid in factor_ids],
            "rank": 9,
            "rank_score": 12345,
        }],
    }}}


class SparkRerollClient:
    def __init__(self, fail_finish=False):
        self.calls = []
        self.events = []
        self.tp_info = {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0}
        self.live_tp_info = dict(self.tp_info)
        self.read_info_calls = 0
        self.factor_lottery_tp_info = None
        self.fail_finish = fail_finish
        self.original = [301, 3302, 10060101]
        self.rerolled = [501, 1102, 2012601, 10060101]

    def factor_select(self, current_turn, skill_id_array=None):
        self.events.append("factor_select")
        self.calls.append(("factor_select", current_turn, skill_id_array))
        return {"data": {"single_mode_factor_select_common": {"factor_select_info_array": [
            {"lottery_id": 1, "factor_info_array": [{"factor_id": fid} for fid in self.original]},
        ]}}}

    def read_info(self):
        self.events.append("read_info")
        self.read_info_calls += 1
        return {"data": {"tp_info": dict(self.live_tp_info)}}

    def refresh_cached_account_state(self, data):
        self.tp_info = dict(data["tp_info"])

    def factor_lottery(self, lottery_count=1, use_tp=30, tp_info=None):
        self.events.append("factor_lottery")
        self.factor_lottery_tp_info = dict(tp_info or {})
        self.calls.append(("factor_lottery", lottery_count, use_tp))
        return {"data": {"single_mode_factor_lottery_common": {"factor_select_info_array": [
            {"lottery_id": 2, "factor_info_array": [{"factor_id": fid} for fid in self.rerolled]},
            {"lottery_id": 1, "factor_info_array": [{"factor_id": fid} for fid in self.original]},
        ]}}}

    def single_mode_use_tp(self, scenario_id=None, base=30):
        # Deliberately discounted: the reroll must ignore the career-START campaign
        # cost, so this returning 15 while factor_lottery still sends 30 is the point.
        return 15

    def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=0):
        self.calls.append(("finish_career", current_turn, factor_lottery_id))
        if self.fail_finish:
            raise Exception("API error 500 on single_mode_free/finish")
        return _finish_state(self.rerolled if factor_lottery_id == 2 else self.original)


class SparkRerollTpClient:
    TP_BOTTLE_ITEM_ID = 32

    def __init__(self):
        self.tp_info = {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0}
        self.coin_info = {"fcoin": 90, "coin": 0}
        self.live_coin_info = {"fcoin": 100, "coin": 0}
        self.item_map = {}
        self.bottle_calls = []
        self.carat_calls = []
        self.read_info_calls = 0
        self.refresh_calls = 0
        self.recovery_jewel_totals = []

    def read_info(self):
        self.read_info_calls += 1
        return {
            "data": {
                "tp_info": dict(self.tp_info),
                "coin_info": dict(self.live_coin_info),
                "item_list": [
                    {"item_id": item_id, "number": number}
                    for item_id, number in self.item_map.items()
                ],
            }
        }

    def refresh_cached_account_state(self, data):
        self.refresh_calls += 1
        if data.get("tp_info"):
            self.tp_info = data["tp_info"]
        if data.get("coin_info"):
            self.coin_info = data["coin_info"]

    def use_recovery_item(self, item_id, item_num):
        item_id = int(item_id)
        item_num = int(item_num)
        own = int(self.item_map.get(item_id, 0) or 0)
        if own < item_num:
            raise ValueError("No recovery item available")
        self.bottle_calls.append((item_id, item_num))
        self.item_map[item_id] = own - item_num
        self.tp_info = {"current_tp": 30 * item_num, "max_tp": 100, "max_recovery_time": 0}
        return self.tp_info

    def recovery_tp(self, count=1):
        self.carat_calls.append(count)
        self.recovery_jewel_totals.append(self.coin_info["fcoin"] + self.coin_info["coin"])
        self.tp_info = {"current_tp": 30 * int(count), "max_tp": 100, "max_recovery_time": 0}
        return self.tp_info


def test_spark_reroll_tp_uses_start_user_cache_bottle_count():
    runner = CareerRunner(ROOT)
    runner.user_info_cache = {"tp_bottle_count": 2, "item_map": {32: 2}}
    client = SparkRerollTpClient()

    assert runner._ensure_spark_reroll_tp(client, 30) is True

    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == []
    assert client.item_map[32] == 1
    assert runner.user_info_cache["tp_bottle_count"] == 1


def test_spark_reroll_tp_cache_zero_does_not_mask_client_bottle():
    runner = CareerRunner(ROOT)
    runner.user_info_cache = {"tp_bottle_count": 0, "item_map": {32: 0}}
    client = SparkRerollTpClient()
    client.item_map[32] = 1

    assert runner._ensure_spark_reroll_tp(client, 30) is True

    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == []


def test_spark_reroll_tp_bottle_error_falls_back_to_carat():
    runner = CareerRunner(ROOT)
    runner.user_info_cache = {"tp_bottle_count": 1, "item_map": {32: 1}}
    client = SparkRerollTpClient()
    client.item_map[32] = 1

    def fail_bottle(item_id, item_num):
        client.bottle_calls.append((item_id, item_num))
        raise Exception("stale bottle cache")

    client.use_recovery_item = fail_bottle

    assert runner._ensure_spark_reroll_tp(client, 30) is True
    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == [1]


def test_spark_reroll_tp_without_bottles_falls_back_to_carat():
    runner = CareerRunner(ROOT)
    runner.user_info_cache = {"tp_bottle_count": 0, "item_map": {32: 0}}
    client = SparkRerollTpClient()

    assert runner._ensure_spark_reroll_tp(client, 30) is True
    assert client.bottle_calls == []
    assert client.carat_calls == [1]
    assert client.read_info_calls == 1
    assert client.refresh_calls == 1
    assert client.recovery_jewel_totals == [100]


def test_spark_reroll_tp_bottle_underfill_falls_back_to_carat():
    runner = CareerRunner(ROOT)
    runner.user_info_cache = {"tp_bottle_count": 1, "item_map": {32: 1}}
    client = SparkRerollTpClient()
    client.item_map[32] = 1

    def underfill_bottle(item_id, item_num):
        client.bottle_calls.append((item_id, item_num))
        client.item_map[item_id] -= item_num
        client.tp_info = {"current_tp": 10, "max_tp": 100, "max_recovery_time": 0}
        return client.tp_info

    client.use_recovery_item = underfill_bottle

    assert runner._ensure_spark_reroll_tp(client, 30) is True
    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == [1]
    assert runner.user_info_cache["tp_bottle_count"] == 0


def test_spark_reroll_tp_carat_213_returns_false_without_retry():
    runner = CareerRunner(ROOT)
    client = SparkRerollTpClient()

    def fail_carat(count=1):
        client.carat_calls.append(count)
        raise Exception("API error 213 on user/recovery_trainer_point")

    client.recovery_tp = fail_carat

    assert runner._ensure_spark_reroll_tp(client, 30) is False
    assert client.carat_calls == [1]
    assert client.read_info_calls == 1
    assert any(
        "carat TP recovery rejected by server (213:" in row["detail"]
        for row in runner.status["log"]
    )


def test_spark_reroll_tp_skips_carat_when_live_jewels_are_insufficient():
    runner = CareerRunner(ROOT)
    client = SparkRerollTpClient()
    client.live_coin_info = {"fcoin": 9, "coin": 0}

    assert runner._ensure_spark_reroll_tp(client, 30) is False

    assert client.read_info_calls == 1
    assert client.carat_calls == []
    assert any(
        "only 9/10 jewels after live refresh" in row["detail"]
        for row in runner.status["log"]
    )


def test_spark_reroll_tp_carat_underfill_returns_false():
    runner = CareerRunner(ROOT)
    client = SparkRerollTpClient()

    def underfill_carat(count=1):
        client.carat_calls.append(count)
        client.tp_info = {"current_tp": 20, "max_tp": 100, "max_recovery_time": 0}
        return client.tp_info

    client.recovery_tp = underfill_carat

    assert runner._ensure_spark_reroll_tp(client, 30) is False
    assert client.carat_calls == [1]


def test_spark_reroll_without_bottle_finishes_original_when_carat_underfills():
    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True
    runner.user_info_cache = {"tp_bottle_count": 0, "item_map": {32: 0}}
    client = SparkRerollClient()
    client.tp_info["current_tp"] = 0
    client.item_map = {}
    client.coin_info = {"fcoin": 100, "coin": 0}
    client.carat_calls = []
    client.read_info = lambda: {"data": {"tp_info": client.tp_info, "coin_info": client.coin_info}}
    client.refresh_cached_account_state = lambda data: None
    client.recovery_tp = lambda count=1: client.carat_calls.append(count)
    state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    runner._finish_career_flow(client, None, state, {}, 78)

    assert client.calls == [("factor_select", 78, None), ("finish_career", 78, 1)]
    assert client.carat_calls == [1]
    assert runner._notify_spark_reroll_choice == 1
    assert runner._notify_factor_ids == client.original


def test_spark_reroll_failed_bottle_and_carat_keeps_original():
    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True
    runner.user_info_cache = {"tp_bottle_count": 1, "item_map": {32: 1}}

    class Client(SparkRerollClient):
        TP_BOTTLE_ITEM_ID = 32

        def __init__(self):
            super().__init__()
            self.tp_info["current_tp"] = 0
            self.coin_info = {"fcoin": 100, "coin": 0}
            self.item_map = {32: 1}
            self.bottle_calls = []
            self.carat_calls = []

        def read_info(self):
            return {"data": {"tp_info": self.tp_info, "coin_info": self.coin_info}}

        def refresh_cached_account_state(self, data):
            self.tp_info = data["tp_info"]
            self.coin_info = data["coin_info"]

        def use_recovery_item(self, item_id, item_num):
            self.bottle_calls.append((item_id, item_num))
            raise Exception("stale bottle cache")

        def recovery_tp(self, count=1):
            self.carat_calls.append(count)

    client = Client()
    state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    runner._finish_career_flow(client, None, state, {}, 78)

    assert client.bottle_calls == [(32, 1)]
    assert client.carat_calls == [1]
    assert client.calls == [("factor_select", 78, None), ("finish_career", 78, 1)]


def test_finish_flow_rerolls_before_capture_and_uses_selected_sparks(monkeypatch):
    # An active half-TP campaign is in force. It discounts the career START only --
    # the spark-reroll factor_lottery cost stays a flat 30, so neither the client
    # shim nor the uma_data resolver may touch this path.
    from uma_data import tp_cost

    monkeypatch.setattr(
        tp_cost, "load_active_campaigns",
        lambda base_dir=None: [{"target_id": 0, "use_tp": 15, "start_time": 100, "end_time": 200}],
    )

    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True
    client = SparkRerollClient()
    state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    runner._finish_career_flow(client, None, state, {}, 78)

    assert [call[0] for call in client.calls] == ["factor_select", "factor_lottery", "finish_career"]
    assert client.calls[1] == ("factor_lottery", 1, 30)
    assert client.calls[-1] == ("finish_career", 78, 2)
    assert runner._notify_factor_ids == client.rerolled


def test_spark_reroll_refreshes_tp_info_before_factor_lottery():
    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True
    client = SparkRerollClient()
    client.tp_info = {"current_tp": 84, "max_tp": 100, "max_recovery_time": 1784812757}
    client.live_tp_info = {"current_tp": 85, "max_tp": 100, "max_recovery_time": 1784812757}

    assert runner._choose_finish_factor_lottery_id(client, 78) == 2

    assert client.events == ["factor_select", "read_info", "factor_lottery"]
    assert client.read_info_calls == 1
    assert client.factor_lottery_tp_info == client.live_tp_info
    assert any(
        'factor_lottery request tp_info={"current_tp": 85, "max_recovery_time": 1784812757, "max_tp": 100} use_tp=30'
        == row["detail"]
        for row in runner.status["log"]
    )


def test_finish_flow_reroll_disabled_keeps_factor_lottery_id_zero():
    runner = CareerRunner(ROOT)
    client = SparkRerollClient()
    state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    runner._finish_career_flow(client, None, state, {}, 78)

    assert [call[0] for call in client.calls] == ["finish_career"]
    assert client.calls[-1] == ("finish_career", 78, 0)


def test_capture_sparks_reads_factor_info_array():
    runner = CareerRunner(ROOT)

    runner._capture_sparks(_finish_state([301, 3302, 10060101]))

    assert runner._notify_factor_ids == [301, 3302, 10060101]
    assert runner._notify_rank == 9
    assert runner._notify_rank_score == 12345


def test_reroll_final_finish_failure_is_fatal():
    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True
    state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

    with pytest.raises(RunFatalError, match="finish_career failed after Spark Reroll choice 2"):
        runner._finish_career_flow(SparkRerollClient(fail_finish=True), None, state, {}, 78)


def test_reroll_resume_with_both_options_does_not_spend_tp_again():
    runner = CareerRunner(ROOT)
    runner.spark_reroll_enabled = True

    class Client(SparkRerollClient):
        def factor_select(self, current_turn, skill_id_array=None):
            raise Exception("API error 102 on single_mode_free/factor_select")

        def load_career(self):
            self.calls.append(("load_career",))
            return self.factor_lottery()

        def factor_lottery(self, *args, **kwargs):
            if self.calls and self.calls[-1][0] == "load_career":
                return super().factor_lottery(*args, **kwargs)
            raise AssertionError("should not reroll again after resume exposes both options")

    assert runner._choose_finish_factor_lottery_id(Client(), 78) == 2


class Runner208Client:
    def __init__(self):
        self.calls = []

    def gain_skills(self, gain_skill_info_array, current_turn):
        self.calls.append((list(gain_skill_info_array), current_turn))
        raise Exception("API error 208 (server busy, sid resync needed) on single_mode_free/gain_skills")


class Runner208SkillBuyer:
    def __init__(self, payload):
        self.payload = list(payload)
        self.recover_after_error = False
        self.attempt_events = []

    def buy(self, client, state, preset, force):
        current_turn = int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
        try:
            client.gain_skills(self.payload, current_turn)
        except Exception as e:
            self.recover_after_error = True
            self.attempt_events.append({
                "selected": [],
                "attempt": [],
                "payload": self.payload,
                "result": {"result": "error", "error": str(e)},
            })
            return state, 0
        return state, len(self.payload)


def _runner_skill_state(skill_ids):
    return {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 500,
                "skill_array": [{"skill_id": skill_id} for skill_id in skill_ids],
                "skill_tips_array": [],
            }
        }
    }


def _run_208_skill_reconciliation(post_skill_ids):
    payload = [
        {"skill_id": 200352, "level": 1},
        {"skill_id": 200332, "level": 1},
    ]
    runner = CareerRunner(ROOT)
    runner._debug_turn = lambda *args, **kwargs: None
    runner._fresh_career_state = lambda client, *a, **k: _runner_skill_state(post_skill_ids)
    runner.skill_buyer = Runner208SkillBuyer(payload)
    client = Runner208Client()

    state = runner._buy_skills(client, _runner_skill_state([]), {"learn_skill_threshold": 0}, True)

    assert client.calls == [(payload, 78)]
    return runner, state


def test_runner_reconciles_skills_bought_from_reloaded_owned_skills_after_208():
    runner, state = _run_208_skill_reconciliation([200352, 200332, 999999])

    assert {row["skill_id"] for row in state["data"]["chara_info"]["skill_array"]} == {200352, 200332, 999999}
    assert runner.status["skills_bought"] == 2
    assert runner.status["last_action"] == "skills 2"

    failed_runner, _ = _run_208_skill_reconciliation([999999])

    assert failed_runner.status["skills_bought"] == 0
    assert failed_runner.status["last_action"] == ""


def test_finish_flow_retries_sp_drain_after_transient_recover():
    """A transient 208 on the FIRST finish buy used to set recover_after_error and
    abort the whole SP drain (skill_buy_closed_at_finish), stranding all leftover SP.
    The drain must instead RETRY on the reloaded state and spend the SP."""
    runner = CareerRunner(ROOT)
    runner._debug_turn = lambda *args, **kwargs: None
    state = {
        "data": {
            "chara_info": {
                "turn": 78,
                "skill_point": 500,
                "skill_array": [],
                "skill_tips_array": [{"group_id": 20035, "rarity": 1, "level": 2}],
            }
        }
    }

    class TransientClient:
        def __init__(self):
            self.calls = []

        def load_career(self):
            self.calls.append("load_career")
            return state  # same object -> SP persists across the recover reload

        def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=0):
            self.calls.append("finish_career")
            return {"data": {"single_mode_finish_common": {}}}

    class TransientBuyer:
        def __init__(self):
            self.recover_after_error = False
            self.attempt_events = []
            self.buy_calls = 0

        def buy(self, client, st, preset, force):
            self.buy_calls += 1
            self.recover_after_error = False
            chara = (st.get("data") or {}).get("chara_info") or {}
            sp = int(chara.get("skill_point") or 0)
            if self.buy_calls == 1:
                # Transient 208: the session reloaded but nothing was bought.
                self.recover_after_error = True
                return st, 0
            # Later passes succeed, draining 200 SP each.
            if sp > 0:
                chara["skill_point"] = max(0, sp - 200)
            return st, 1

        def reset_scoped_failures(self):
            pass

    runner.skill_buyer = TransientBuyer()
    client = TransientClient()

    runner._finish_career_flow(client, None, state, {"learn_skill_threshold": 0}, 78)

    # The transient recover on pass 1 must NOT end the drain: it retries and the
    # remaining SP is fully spent (500 -> 0), not stranded.
    assert runner.skill_buyer.buy_calls >= 3
    assert int(state["data"]["chara_info"]["skill_point"]) == 0
    assert "finish_career" in client.calls


def test_record_final_stats_reflects_post_drain_sp():
    """The webhook (_latest_stats -> action_history) and the career summary
    (_build_notify_summary -> report turn stats) read stats recorded BEFORE the finish
    drain, so they show the pre-drain skill_point. _record_final_stats must refresh
    both from the post-drain state so the REAL leftover SP is reported."""
    from career_bot.engine.report import new_report
    runner = CareerRunner(ROOT)
    runner.report = new_report({"name": "t"}, 4)
    runner.report["turns"] = [{
        "turn": 78, "stats": {"skill_point": 377, "speed": 1124}, "skill_point": 377,
        "api_calls": [], "skill_buy_attempts": [], "item_buy_attempts": [], "item_usage_attempts": [],
    }]
    runner.status["action_history"] = [{
        "turn": 78, "action": "finish", "facility": "",
        "stats": {"skill_point": 377}, "detail": "old", "time": "x",
    }]
    # Post-drain state: 342 SP was spent, 35 remains.
    state = {"data": {"chara_info": {
        "turn": 78, "skill_point": 35, "vital": 77, "max_vital": 120,
        "speed": 1124, "stamina": 668, "power": 963, "guts": 492, "wiz": 676,
    }}}

    runner._record_final_stats(state)

    assert runner.report["turns"][0]["stats"]["skill_point"] == 35
    assert runner.report["turns"][0]["skill_point"] == 35
    assert runner.status["action_history"][-1]["stats"]["skill_point"] == 35


class AcceptAllNoStateClient:
    """Server accepts every gain_skills (result_code 1) but its response does NOT
    refresh chara.skill_array -- the real behaviour that lets a re-buy of an
    already-owned skill slip through (the server takes the SP and grants nothing)."""

    def __init__(self):
        self.payloads = []

    def gain_skills(self, gain_skill_info_array, current_turn):
        self.payloads.append([int(i["skill_id"]) for i in gain_skill_info_array])
        return {"data": {}}  # no chara_info -> skill_array + skill_point stay stale


def test_buy_never_resends_already_bought_skill_when_state_stale():
    """Even when the buy response never updates skill_array (so chara still looks like
    nothing is owned), a second drain pass on the SAME state must NOT re-send a skill
    already bought this career -- otherwise the finish drain burns SP re-buying it."""
    buyer = SkillBuyer(ROOT)
    client = AcceptAllNoStateClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 49,
                "skill_point": 5000,  # plenty, so a re-buy is NOT blocked by affordability
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": 20035, "rarity": 1, "level": 2},
                    {"group_id": 20033, "rarity": 1, "level": 5},
                ],
            }
        }
    }

    buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)
    assert buyer.bought, "pass 1 should have bought at least one skill"
    first_pass_count = len(client.payloads)
    bought_ids = set(buyer.bought)

    # Second drain pass on the SAME stale state (skill_array still empty, SP still high).
    buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    resent = [pid for payload in client.payloads[first_pass_count:] for pid in payload if pid in bought_ids]
    assert resent == [], f"re-sent already-bought skills: {resent}"


def test_finish_flow_records_post_drain_sp_not_finish_response():
    """_record_final_stats must run on the POST-DRAIN state (before finish_career
    replaces it). The career-complete response can carry a stale pre-drain
    skill_point; recording from it would report the wrong leftover SP on the webhook
    + summary. Here the drain takes 500 -> 100 and finish_career returns a stale 999;
    the recorded stat must be 100."""
    from career_bot.engine.report import new_report
    runner = CareerRunner(ROOT)
    runner._debug_turn = lambda *args, **kwargs: None
    runner.report = new_report({"name": "t"}, 4)
    runner.report["turns"] = [{
        "turn": 78, "stats": {"skill_point": 500}, "skill_point": 500,
        "api_calls": [], "skill_buy_attempts": [], "item_buy_attempts": [], "item_usage_attempts": [],
    }]
    runner.status["action_history"] = [{
        "turn": 78, "action": "finish", "facility": "",
        "stats": {"skill_point": 500}, "detail": "old", "time": "x",
    }]
    state = {"data": {"chara_info": {
        "turn": 78, "skill_point": 500, "skill_array": [],
        "skill_tips_array": [{"group_id": 20035, "rarity": 1, "level": 2}],
    }}}

    class DrainBuyer:
        def __init__(self):
            self.recover_after_error = False
            self.attempt_events = []

        def buy(self, client, st, preset, force):
            self.recover_after_error = False
            chara = (st.get("data") or {}).get("chara_info") or {}
            sp = int(chara.get("skill_point") or 0)
            if sp > 100:
                chara["skill_point"] = sp - 200
            return st, 1

        def reset_scoped_failures(self):
            pass

    class StaleFinishClient:
        def load_career(self):
            return state

        def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=0):
            # career-complete response carries a STALE pre-drain skill_point
            return {"data": {"chara_info": {"turn": 78, "skill_point": 999}, "single_mode_finish_common": {}}}

    runner.skill_buyer = DrainBuyer()
    runner._finish_career_flow(StaleFinishClient(), None, state, {"learn_skill_threshold": 0}, 78)

    assert runner.report["turns"][0]["skill_point"] == 100
    assert runner.status["action_history"][-1]["stats"]["skill_point"] == 100


def test_recover_race_out_relogins_and_resumes_on_dead_session():
    """A daily reset / forced relogin kills the session: race_out 201s AND the Tier-2
    re-entry's race_entry 201s. That is an expired session, not a corrupted race --
    _recover_race_out must relogin + resume the career, not raise RunFatalError."""
    runner = CareerRunner(ROOT)
    runner._RACE_OUT_INPLACE_RETRIES = 0  # skip the in-place wait loop in the test
    resumed = {"data": {"chara_info": {
        "turn": 16, "playing_state": 1, "skill_point": 0, "skill_array": [], "skill_tips_array": [],
    }}}

    class DeadSessionClient:
        def __init__(self):
            self.login_calls = 0
            self.load_calls = 0

        def race_out(self, current_turn):
            raise Exception("API error 201 on single_mode_free/race_out")

        def race_entry(self, program_id, current_turn, **kw):
            raise Exception("API error 201 on single_mode_free/race_entry")

        def login(self):
            self.login_calls += 1
            return {"data": {}}

        def load_career(self):
            self.load_calls += 1
            return resumed

    client = DeadSessionClient()
    out = runner._recover_race_out(
        client, None, 16, "race_out_recovered",
        Exception("API error 201 on single_mode_free/race_out"), program_id=2512,
    )

    assert out is resumed              # resumed via relogin, not RunFatalError
    assert client.login_calls == 1     # relogin happened
    assert client.load_calls == 1
