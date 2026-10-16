import backend.app.domain.rank_point as rank_point


def test_rank_point_submodules_read_rebound_owner_state(monkeypatch, tmp_path):
    monkeypatch.setattr(rank_point, "base_dir", tmp_path)
    monkeypatch.setattr(rank_point, "state_root", tmp_path / "state")
    monkeypatch.setattr(rank_point, "RANKPOINT_PROBE_LOG_PATH", None)
    monkeypatch.setattr(rank_point, "chara_map", {"1001": "X"})
    monkeypatch.setattr(rank_point, "race_map", {"7": {"grade": "G1"}})
    monkeypatch.setattr(
        rank_point,
        "factor_map",
        {"101": {"name": "Rebound Factor", "stars": 1, "category": "stat"}},
    )
    monkeypatch.setattr(rank_point, "skill_data", {})
    monkeypatch.setattr(rank_point, "succession_relation_points", {9: 42})
    monkeypatch.setattr(
        rank_point,
        "succession_relation_members",
        {10: {9}, 20: {9}},
    )
    monkeypatch.setattr(rank_point, "succession_relation_loaded", True)

    assert rank_point._rankpoint_probe_log_path() == (
        tmp_path / "state" / "rankpoint_probes.jsonl"
    )

    tree = rank_point.build_chara_tree(
        {"factor_id_array": [101], "win_saddle_id_array": [7]},
        "1001",
    )
    assert tree["self"]["name"] == "X"
    assert tree["self"]["wins"] == {"g1": 1, "g2": 0, "g3": 0, "total": 1}
    assert tree["self"]["factors"][0]["name"] == "Rebound Factor"
    assert rank_point.relation_pair_point(1001, 2001) == 42
