import pathlib

import pytest

from career_bot.skills import SkillBuyer
from tests._helpers import CaptureClient

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_estimate_cost_uses_master_cost_for_circle_skill():
    buyer = SkillBuyer(ROOT)
    cost = buyer._estimate_cost({
        "skill_id": 200352,
        "hint_level": 2,
        "name": "Corner Recovery ○",
    })
    assert cost == 136


@pytest.mark.parametrize(("base", "hint_level", "expected"), [
    (140, 5, 84),
    (200, 5, 120),
    (160, 4, 104),
    (200, 3, 140),
    (200, 0, 200),
    (200, 99, 120),
])
def test_estimate_cost_uses_live_hint_discount_table(base, hint_level, expected):
    """The 2026-07-15 trace proves levels 4/5 are 35%/40%, not 40%/50%."""
    buyer = SkillBuyer(ROOT)
    skill_id = 990001
    buyer.skill_costs[skill_id] = base

    assert buyer._estimate_cost({
        "skill_id": skill_id,
        "hint_level": hint_level,
        "name": "Trace regression skill",
    }) == expected


@pytest.mark.parametrize(("base", "hint_level", "expected"), [
    (200, 0, 180),
    (200, 5, 108),
    (140, 5, 75),
])
def test_estimate_cost_applies_fast_learner_after_hint_discount(base, hint_level, expected):
    buyer = SkillBuyer(ROOT)
    buyer.fast_learner = True
    skill_id = 990001
    buyer.skill_costs[skill_id] = base

    assert buyer._estimate_cost({
        "skill_id": skill_id,
        "hint_level": hint_level,
        "name": "Fast Learner test skill",
    }) == expected


def _register_test_skill(buyer, skill_id=990011, group_id=99001, base=200):
    buyer.skill_names[skill_id] = "Fast Learner test skill"
    buyer.skill_rarities[skill_id] = 1
    buyer.skill_costs[skill_id] = base
    buyer.skill_grade_values[skill_id] = 100
    buyer.skill_id_exists.add(skill_id)
    buyer.skill_to_group_id[skill_id] = group_id
    buyer.group_to_skill_ids[group_id] = [skill_id]
    return skill_id, group_id


@pytest.mark.parametrize(("effects", "expected_bought", "expected_cost"), [
    ([7], 1, 108),
    ([], 0, 120),
])
def test_buy_uses_fast_learner_discount_for_affordability(
    effects, expected_bought, expected_cost
):
    buyer = SkillBuyer(ROOT)
    skill_id, group_id = _register_test_skill(buyer)
    client = CaptureClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 42,
                "skill_point": 108,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": group_id, "rarity": 1, "level": 5},
                ],
                "chara_effect_id_array": effects,
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    assert buyer.last_candidates[0]["cost"] == expected_cost
    assert bought == expected_bought
    assert len(client.payloads) == expected_bought
    if expected_bought:
        assert client.payloads[0][0] == [{"skill_id": skill_id, "level": 1}]


def test_sync_fast_learner_flips_off_when_later_snapshot_lacks_effect():
    buyer = SkillBuyer(ROOT)

    buyer._sync_fast_learner({"chara_effect_id_array": [None, "bad", "7"]})
    assert buyer.fast_learner is True

    buyer._sync_fast_learner({"chara_effect_id_array": [5, 6, "bad"]})
    assert buyer.fast_learner is False


def test_batch_cost_drift_records_estimated_and_actual_cost():
    buyer = SkillBuyer(ROOT)
    skill_id, group_id = _register_test_skill(buyer)

    class DriftClient(CaptureClient):
        def gain_skills(self, gain_skill_info_array, current_turn):
            self.payloads.append((gain_skill_info_array, current_turn))
            return {
                "data": {
                    "chara_info": {
                        "turn": current_turn,
                        "skill_point": 91,
                    }
                }
            }

    client = DriftClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 42,
                "skill_point": 200,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": group_id, "rarity": 1, "level": 5},
                ],
                "chara_effect_id_array": [7],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    assert bought == 1
    assert client.payloads[0][0] == [{"skill_id": skill_id, "level": 1}]
    result = buyer.attempt_events[0]["result"]
    assert result["estimated_cost"] == 108
    assert result["actual_cost"] == 109


def test_turn_58_cost_regression_does_not_send_all_six_skills_with_634_sp():
    buyer = SkillBuyer(ROOT)
    client = CaptureClient()
    specs = [
        (910001, 91000, 200, 3),
        (910011, 91001, 180, 3),
        (910021, 91002, 100, 1),
        (910031, 91003, 130, 3),
        (910041, 91004, 140, 5),
        (910051, 91005, 200, 5),
    ]
    for index, (skill_id, group_id, base, _) in enumerate(specs):
        buyer.skill_names[skill_id] = f"Turn 58 skill {index}"
        buyer.skill_rarities[skill_id] = 1
        buyer.skill_costs[skill_id] = base
        buyer.skill_grade_values[skill_id] = 100
        buyer.skill_id_exists.add(skill_id)
        buyer.skill_to_group_id[skill_id] = group_id
        buyer.group_to_skill_ids[group_id] = [skill_id]

    state = {
        "data": {
            "chara_info": {
                "turn": 58,
                "skill_point": 634,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": group_id, "rarity": 1, "level": hint_level}
                    for _, group_id, _, hint_level in specs
                ],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    assert sum(candidate["cost"] for candidate in buyer.last_candidates) == 651
    assert sum(candidate["cost"] for candidate in buyer.last_selected) <= 634
    assert bought == 5
    assert len(client.payloads) == 1
    payload_ids = {row["skill_id"] for row in client.payloads[0][0]}
    assert len(payload_ids) == 5
    assert payload_ids != {skill_id for skill_id, *_ in specs}


def test_buy_batch_does_not_send_unaffordable_master_cost_payload():
    buyer = SkillBuyer(ROOT)
    client = CaptureClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 49,
                "skill_point": 495,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": 20035, "rarity": 1, "level": 2},
                    {"group_id": 20033, "rarity": 1, "level": 5},
                    {"group_id": 20046, "rarity": 1, "level": 1},
                    {"group_id": 20072, "rarity": 1, "level": 1},
                ],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    assert bought == 3
    assert len(client.payloads) == 1
    payload, turn = client.payloads[0]
    assert turn == 49
    skill_ids = {item["skill_id"] for item in payload}
    assert skill_ids == {200352, 200332, 200462}
    assert 200722 not in skill_ids


def test_higher_tier_owned_blocks_lower_skill_tip():
    """Owning the gold tier of a group (Professor of Curvature 200331, rarity 2,
    group 20033) must NOT re-buy that group's white tier (Corner Adept o 200332,
    rarity 1). The server accepts such a buy (result_code 1) but grants nothing,
    silently draining SP -- regression for the ~1000-SP leak."""
    buyer = SkillBuyer(ROOT)
    client = CaptureClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 50,
                "skill_point": 900,
                "skill_array": [{"skill_id": 200331}],  # owns the GOLD of group 20033
                "skill_tips_array": [
                    {"group_id": 20033, "rarity": 1, "level": 1},  # white -> must skip
                    {"group_id": 20046, "rarity": 1, "level": 1},  # unrelated -> buyable
                ],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    skill_ids = {item["skill_id"] for cap in client.payloads for item in cap[0]}
    assert 200332 not in skill_ids  # white of an already-gold group is never re-bought
    assert 200462 in skill_ids      # an unrelated white is still bought (no over-block)


def test_buy_batch_counts_bundled_white_tiers_as_bought():
    buyer = SkillBuyer(ROOT)
    client = CaptureClient()
    state = {
        "data": {
            "chara_info": {
                "turn": 49,
                "skill_point": 500,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": 20215, "rarity": 2, "level": 1},
                ],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    assert len(client.payloads) == 1
    payload, turn = client.payloads[0]
    assert turn == 49
    skill_ids = {item["skill_id"] for item in payload}
    assert skill_ids == {202151, 202152}
    assert bought == len(payload)
    assert buyer.last_result["count"] == len(payload)


class SplitRejectClient:
    """Rejects any gain_skills batch that contains `bad_skill_id` (server returns
    201/205 for the whole batch), but accepts batches without it."""

    def __init__(self, bad_skill_id, code="201", skill_point=495):
        self.bad = int(bad_skill_id)
        self.code = code
        self.skill_point = int(skill_point)
        self.calls = []

    def load_career(self):
        return {
            "data": {
                "chara_info": {
                    "turn": 49,
                    "skill_point": self.skill_point,
                    "skill_array": [],
                }
            }
        }

    def gain_skills(self, gain_skill_info_array, current_turn):
        ids = [int(item["skill_id"]) for item in gain_skill_info_array]
        self.calls.append(ids)
        if self.bad in ids:
            raise Exception(f"API error {self.code} on single_mode_free/gain_skills")
        # No SP snapshot: the fallback must deduct its corrected estimate locally.
        return {"data": {}}


def _fallback_fixture(buyer, count=5, points=1000):
    candidates = []
    tips = []
    for index in range(count):
        skill_id = 880001 + index * 10
        group_id = 88000 + index
        buyer.skill_names[skill_id] = f"Fallback skill {index}"
        buyer.skill_rarities[skill_id] = 1
        buyer.skill_costs[skill_id] = 20
        buyer.skill_to_group_id[skill_id] = group_id
        buyer.group_to_skill_ids[group_id] = [skill_id]
        candidates.append({
            "skill_id": skill_id,
            "group_id": group_id,
            "hint_level": 0,
            "name": buyer.skill_names[skill_id],
            "cost": 20,
            "bundled_skill_ids": [],
        })
        tips.append({"group_id": group_id, "rarity": 1, "level": 0})
    state = {
        "data": {
            "chara_info": {
                "turn": 58,
                "skill_point": points,
                "skill_array": [],
                "skill_tips_array": tips,
            }
        }
    }
    return state, candidates


class CommitAware205Client:
    def __init__(self, owned_after_batch=(), points=1000, single_error=None):
        self.owned_after_batch = {int(skill_id) for skill_id in owned_after_batch}
        self.points = int(points)
        self.single_error = single_error
        self.gain_calls = []
        self.load_calls = 0

    def gain_skills(self, gain_skill_info_array, current_turn):
        ids = [int(item["skill_id"]) for item in gain_skill_info_array]
        self.gain_calls.append(ids)
        if len(self.gain_calls) == 1 and len(ids) > 1:
            raise Exception("API error 205 on single_mode_free/gain_skills")
        if self.single_error:
            raise Exception(f"API error {self.single_error} on single_mode_free/gain_skills")
        self.owned_after_batch.update(ids)
        self.points -= 20 * len(ids)
        return {
            "data": {
                "chara_info": {
                    "turn": current_turn,
                    "skill_point": self.points,
                    "skill_array": [
                        {"skill_id": skill_id}
                        for skill_id in sorted(self.owned_after_batch)
                    ],
                }
            }
        }

    def load_career(self):
        self.load_calls += 1
        return {
            "data": {
                "chara_info": {
                    "turn": 58,
                    "skill_point": self.points,
                    "skill_array": [
                        {"skill_id": skill_id}
                        for skill_id in sorted(self.owned_after_batch)
                    ],
                }
            }
        }


def test_committed_205_batch_reloads_and_never_rebuys_owned_skills():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer)
    committed_ids = {candidate["skill_id"] for candidate in candidates}
    client = CommitAware205Client(committed_ids)

    _, bought = buyer._buy_batch(client, state, candidates, 58)

    assert bought == 0
    assert client.load_calls == 1
    assert client.gain_calls == [[candidate["skill_id"] for candidate in candidates]]
    assert committed_ids <= buyer.bought
    assert buyer.recover_after_error is True
    assert all(row.get("skipped") == "already_owned" for row in buyer.last_result["results"])


def test_partially_committed_205_batch_only_sends_missing_skills_individually():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer)
    all_ids = [candidate["skill_id"] for candidate in candidates]
    committed_ids = set(all_ids[:2])
    client = CommitAware205Client(committed_ids)

    _, bought = buyer._buy_batch(client, state, candidates, 58)

    assert bought == 3
    assert client.load_calls == 1
    assert client.gain_calls[0] == all_ids
    assert client.gain_calls[1:] == [[skill_id] for skill_id in all_ids[2:]]
    assert set(all_ids) <= buyer.bought


def test_individual_fallback_skips_unaffordable_skill_without_api_call():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer, count=1, points=500)
    candidate = candidates[0]
    buyer.skill_costs[candidate["skill_id"]] = 200
    candidate["hint_level"] = 5
    candidate["cost"] = 120
    client = CommitAware205Client(points=100)
    event = {"result": {}}

    _, bought = buyer._buy_individually(client, state, candidates, 58, event)

    assert bought == 0
    assert client.load_calls == 1
    assert client.gain_calls == []
    assert buyer.last_result["results"] == [{
        "skill_id": candidate["skill_id"],
        "ok": False,
        "skipped": "unaffordable",
    }]
    assert candidate["skill_id"] not in buyer._failed_for_turn(58)


def test_individual_cost_drift_records_estimated_and_actual_cost():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer, count=1, points=100)
    event = {"result": {}}
    buyer.attempt_events.append(event)

    class DriftSingleClient:
        def load_career(self):
            return {
                "data": {
                    "chara_info": {
                        "turn": 58,
                        "skill_point": 100,
                        "skill_array": [],
                        "chara_effect_id_array": [7],
                    }
                }
            }

        def gain_skills(self, gain_skill_info_array, current_turn):
            return {
                "data": {
                    "chara_info": {
                        "turn": current_turn,
                        "skill_point": 81,
                    }
                }
            }

    _, bought = buyer._buy_individually(
        DriftSingleClient(), state, candidates, 58, event
    )

    assert bought == 1
    result = buyer.attempt_events[0]["result"]["results"][0]
    assert result["estimated_cost"] == 18
    assert result["actual_cost"] == 19


def test_individual_fallback_stops_when_career_reload_fails():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer, count=2)
    event = {"result": {}}

    class ReloadFailureClient:
        def __init__(self):
            self.gain_calls = []

        def load_career(self):
            raise RuntimeError("reload unavailable")

        def gain_skills(self, gain_skill_info_array, current_turn):
            self.gain_calls.append(list(gain_skill_info_array))

    client = ReloadFailureClient()

    returned_state, bought = buyer._buy_individually(client, state, candidates, 58, event)

    assert returned_state is state
    assert bought == 0
    assert client.gain_calls == []
    assert buyer.recover_after_error is True
    assert buyer.last_result["result"] == "failed"
    assert buyer.last_result["reload_failed"] is True
    assert "reload unavailable" in buyer.last_result["error"]
    assert event["result"] is buyer.last_result


def test_batch_205_sets_recover_after_error():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer, count=1)

    class Batch205Client:
        def gain_skills(self, gain_skill_info_array, current_turn):
            raise Exception("API error 205 on single_mode_free/gain_skills")

    _, bought = buyer._buy_batch(Batch205Client(), state, candidates, 58)

    assert bought == 0
    assert buyer.recover_after_error is True


def test_single_205_sets_recover_after_error():
    buyer = SkillBuyer(ROOT)
    state, candidates = _fallback_fixture(buyer, count=1)
    client = CommitAware205Client(points=1000, single_error=205)

    _, bought = buyer._buy_individually(client, state, candidates, 58, {"result": {}})

    assert bought == 0
    assert len(client.gain_calls) == 1
    assert buyer.recover_after_error is True
    assert candidates[0]["skill_id"] in buyer._failed_for_turn(58)


def test_buy_batch_splits_on_failure_so_good_skills_still_buy():
    buyer = SkillBuyer(ROOT)
    client = SplitRejectClient(200462)  # the third resolved skill is unbuyable
    state = {
        "data": {
            "chara_info": {
                "turn": 49,
                "skill_point": 495,
                "skill_array": [],
                "skill_tips_array": [
                    {"group_id": 20035, "rarity": 1, "level": 2},
                    {"group_id": 20033, "rarity": 1, "level": 5},
                    {"group_id": 20046, "rarity": 1, "level": 1},
                    {"group_id": 20072, "rarity": 1, "level": 1},
                ],
            }
        }
    }

    _, bought = buyer.buy(client, state, {"learn_skill_threshold": 0}, force=True)

    # The 3-skill batch fails once, then each skill is retried alone: the two good
    # ones buy, the unbuyable one is dropped (not the whole batch wasted).
    assert bought == 2
    assert set(client.calls[0]) == {200352, 200332, 200462}
    assert len(client.calls) == 4  # 1 failed batch + 3 individual retries
    assert [200462] in client.calls
    assert 200462 in buyer._failed_for_turn(49)
    assert 200352 not in buyer._failed_for_turn(49)
    # 201 = "this career can't buy this skill", not a state desync: it is remembered
    # (career-scoped) and never re-attempted, and it does NOT trigger a session reload.
    assert buyer.recover_after_error is False
    assert 200462 in buyer.unobtainable
    assert buyer.last_result["split_retry"] is True
    assert buyer.last_result["count"] == 2
