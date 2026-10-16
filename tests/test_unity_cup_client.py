import pytest

from uma_api.client import UmaClient


def make_client():
    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = None
    client.tp_info = {}
    client.calls = []

    def fake_call(ep, args=None, retry_208=6, retry_205=3):
        client.calls.append((ep, args or {}, retry_208, retry_205))
        return {"data": {}}

    client.call = fake_call
    return client


def call_start(client, **overrides):
    kwargs = {
        "card_id": 100101,
        "support_card_ids": [1, 2, 3, 4, 5, 6],
        "friend_viewer_id": 11,
        "friend_card_id": 22,
        "parent_id_1": 33,
        "parent_id_2": 44,
        "scenario_id": 2,
        "deck_id": 7,
        "use_tp": 30,
        "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
    }
    kwargs.update(overrides)
    client.start_career(**kwargs)
    return client.calls[-1]


def test_unity_start_uses_team_endpoint_and_30_tp():
    client = make_client()

    ep, payload, _, _ = call_start(client)
    assert ep == "single_mode_team/start"
    assert payload["start_chara"]["scenario_id"] == 2
    assert "running_style" in payload["start_chara"]
    assert payload["start_chara"]["running_style"] == 2
    assert next(reversed(payload["start_chara"])) == "running_style"
    assert payload["use_tp"] == 30
    assert client.current_scenario_id == 2


@pytest.mark.parametrize("running_style", [0, -1, 5, None, "invalid"])
def test_start_career_invalid_running_style_defaults_to_senko(running_style):
    client = make_client()

    _, payload, _, _ = call_start(client, running_style=running_style)

    assert payload["start_chara"]["running_style"] == 2


def test_start_career_passes_through_valid_running_style():
    client = make_client()

    ep, payload, _, _ = call_start(client, scenario_id=4, running_style=3)

    assert ep == "single_mode_free/start"
    assert payload["start_chara"]["running_style"] == 3


def test_unity_routes_single_mode_methods_to_team_prefix():
    client = make_client()
    client.current_scenario_id = 2

    client.exec_command(1, 101, 25, 80)
    client.check_event(9, 25, chara_id=1, choice_number=0)
    client.gain_skills([{"skill_id": 200352, "level": 1}], 25)
    client.race_entry(1234, 25)
    client.race_entry(1234, 25, running_style=3)
    client.race_start(1, 25)
    client.race_end(25)
    client.race_out(25)
    client.race_continue(25, 1)
    client.factor_select(78)
    client.factor_lottery(1, 30, tp_info={})
    client.finish_career(78)
    client.minigame_end(10)

    assert [row[0] for row in client.calls] == [
        "single_mode_team/exec_command",
        "single_mode_team/check_event",
        "single_mode_team/gain_skills",
        "single_mode_team/race_entry",
        "single_mode_team/change_running_style",
        "single_mode_team/race_start",
        "single_mode_team/race_end",
        "single_mode_team/race_out",
        "single_mode_team/continue",
        "single_mode_team/factor_select",
        "single_mode_team/factor_lottery",
        "single_mode_team/finish",
        "single_mode_team/minigame_end",
    ]


def test_mant_routes_stay_free_prefix():
    client = make_client()
    client.current_scenario_id = 4

    client.exec_command(1, 101, 1, 80)
    client.gain_skills([], 1)
    client.race_entry(1234, 1)
    client.finish_career(78)

    assert [row[0] for row in client.calls] == [
        "single_mode_free/exec_command",
        "single_mode_free/gain_skills",
        "single_mode_free/race_entry",
        "single_mode_free/finish",
    ]


def test_gain_skills_disables_205_retry():
    client = make_client()

    client.gain_skills([{"skill_id": 200352, "level": 1}], 25)

    endpoint, payload, retry_208, retry_205 = client.calls[0]
    assert endpoint == "single_mode_free/gain_skills"
    assert payload["gain_skill_info_array"] == [{"skill_id": 200352, "level": 1}]
    assert retry_208 == 6
    assert retry_205 == 0


def test_team_race_methods_use_team_prefix():
    client = make_client()

    client.team_edit([], 24)
    client.opponent_list(24)
    client.team_race_analyze(301, 24)
    client.team_race_start(301, 24)
    client.team_race_end(24)
    client.team_race_out(24)
    client.team_race_continue(24, 1)

    assert [row[0] for row in client.calls] == [
        "single_mode_team/team_edit",
        "single_mode_team/opponent_list",
        "single_mode_team/team_race_analyze",
        "single_mode_team/team_race_start",
        "single_mode_team/team_race_end",
        "single_mode_team/team_race_out",
        "single_mode_team/team_race_continue",
    ]
