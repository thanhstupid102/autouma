from career_bot.engine import CareerRunner


class FakeClient:
    def __init__(self):
        self.removed = []
        self.unlocked = []

    def remove_trained_chara(self, ids, unlock_ids=None):
        self.removed.append(list(ids))
        self.unlocked.append(list(unlock_ids or []))


def finish_state(tcid=777):
    return {
        "data": {
            "single_mode_finish_common": {
                "trained_chara_id": tcid,
                "trained_chara": [
                    {"trained_chara_id": tcid, "factor_id_array": [101, 202]},
                ],
            }
        }
    }


def test_auto_delete_disabled_noop(monkeypatch, tmp_path):
    runner = CareerRunner(tmp_path)
    runner.auto_delete_trained = {"enabled": False, "min_blue": 9, "conditions": []}
    runner._notify_factor_ids = [101]
    client = FakeClient()

    runner._maybe_auto_delete_trained(client, finish_state())

    assert client.removed == []


def test_auto_delete_failing_filter_deletes_just_finished(monkeypatch, tmp_path):
    import career_bot.planning.spark.keep_filter as kf

    monkeypatch.setattr(kf, "self_factors", lambda factor_ids: [{"name": "Speed", "stars": 2, "category": "stat"}])
    runner = CareerRunner(tmp_path)
    runner.auto_delete_trained = {"enabled": True, "min_blue": 3, "conditions": []}
    runner._notify_factor_ids = [101]
    client = FakeClient()

    runner._maybe_auto_delete_trained(client, finish_state(888))

    assert client.removed == [[888]]


def test_auto_delete_matching_filter_keeps(monkeypatch, tmp_path):
    import career_bot.planning.spark.keep_filter as kf

    monkeypatch.setattr(kf, "self_factors", lambda factor_ids: [{"name": "Speed", "stars": 3, "category": "stat"}])
    runner = CareerRunner(tmp_path)
    runner.auto_delete_trained = {"enabled": True, "min_blue": 3, "conditions": []}
    runner._notify_factor_ids = [101]
    client = FakeClient()

    runner._maybe_auto_delete_trained(client, finish_state(888))

    assert client.removed == []


def test_auto_delete_missing_trained_id_noop(monkeypatch, tmp_path):
    import career_bot.planning.spark.keep_filter as kf

    monkeypatch.setattr(kf, "self_factors", lambda factor_ids: [])
    runner = CareerRunner(tmp_path)
    runner.auto_delete_trained = {"enabled": True, "min_blue": 1, "conditions": []}
    runner._notify_factor_ids = [101]
    client = FakeClient()

    runner._maybe_auto_delete_trained(client, {"data": {"single_mode_finish_common": {}}})

    assert client.removed == []
