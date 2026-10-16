import pytest

from uma_api.account_state import (
    AccountPlayEvidence,
    AccountPlaySignal,
    AccountPlayVerdict,
    HIGH_RANK_SCORE,
    LARGE_FAN_COUNT,
    MANY_OWNED_CHARACTERS,
    MIN_CORROBORATING_PROGRESS_SIGNALS,
    classify_account_played,
)


def _career_records(count):
    return [{"trained_chara_id": index + 1} for index in range(count)]


def _owned_characters(count):
    return [{"card_id": index + 1} for index in range(count)]


def _result(payload):
    return classify_account_played({"data": payload})


def test_tutorial_completion_alone_proves_account_was_played():
    result = _result({"user_info": {"tutorial_step": 1000}})

    assert result.verdict is AccountPlayVerdict.PLAYED
    assert result.evidence == (
        AccountPlayEvidence(AccountPlaySignal.TUTORIAL_COMPLETE, 1000),
    )


def test_real_career_records_alone_prove_account_was_played():
    result = _result({"trained_chara": _career_records(2)})

    assert result.verdict is AccountPlayVerdict.PLAYED
    assert result.evidence == (
        AccountPlayEvidence(AccountPlaySignal.TRAINED_CAREER_RECORDS, 2),
    )


@pytest.mark.parametrize("payload", [
    {
        "main_story_data_list": [],
        "character_story_data_list": [],
        "home_story_data_array": [],
        "short_episode_data_array": [],
        "released_episode_data_array": [],
    },
    {"single_mode_chara_light": None},
    {
        "support_card_deck_array": [
            {"deck_id": index, "support_card_id_array": [index + 1]}
            for index in range(10)
        ],
    },
    {"user_info": {"name": "r81iix"}},
    {"is_linkage": 1, "is_chained": True},
    {
        "tp_info": {"num": 100},
        "coin_info": {"coin_num": 100000},
        "item_list": [{"item_id": 1, "num": 99}],
    },
])
def test_rejected_signals_do_not_prove_account_was_played(payload):
    result = _result(payload)

    assert result.verdict is AccountPlayVerdict.UNVERIFIED
    assert result.evidence == ()


def test_one_weak_signal_does_not_prove_account_was_played():
    result = _result({"user_info": {"fan": LARGE_FAN_COUNT}})

    assert result.verdict is AccountPlayVerdict.UNVERIFIED
    assert result.evidence == (
        AccountPlayEvidence(AccountPlaySignal.FAN_COUNT, LARGE_FAN_COUNT),
    )


def test_three_independent_progress_signals_prove_account_was_played():
    result = _result({
        "user_info": {
            "fan": LARGE_FAN_COUNT,
            "rank_score": HIGH_RANK_SCORE,
        },
        "card_list": _owned_characters(MANY_OWNED_CHARACTERS),
    })

    assert MIN_CORROBORATING_PROGRESS_SIGNALS == 3
    assert result.verdict is AccountPlayVerdict.PLAYED
    assert result.evidence == (
        AccountPlayEvidence(AccountPlaySignal.FAN_COUNT, LARGE_FAN_COUNT),
        AccountPlayEvidence(AccountPlaySignal.RANK_SCORE, HIGH_RANK_SCORE),
        AccountPlayEvidence(AccountPlaySignal.OWNED_CHARACTERS, MANY_OWNED_CHARACTERS),
    )


@pytest.mark.parametrize("payload", [
    None,
    {},
    [],
    "not a payload",
    {"data": None},
    {"data": []},
    {
        "data": {
            "user_info": "not a mapping",
            "trained_chara": "not a list",
            "card_list": ["not a record"],
            "support_card_list": {"not": "a list"},
            "released_episode_data_array": [None],
        },
    },
])
def test_missing_or_malformed_payloads_are_unverified(payload):
    result = classify_account_played(payload)

    assert result.verdict is AccountPlayVerdict.UNVERIFIED
    assert result.evidence == ()
