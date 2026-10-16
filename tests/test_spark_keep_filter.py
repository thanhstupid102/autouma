from career_bot.planning.spark.keep_filter import colour_of, keep_filter_matches


def F(name, stars, category):
    return {"name": name, "stars": stars, "category": category}


def test_colour_of_mapping():
    assert colour_of("stat") == "blue"
    assert colour_of("aptitude") == "pink"
    assert colour_of("skill") == colour_of("race") == colour_of("scenario") == "white"
    assert colour_of("unique") == "green"
    assert colour_of("other") is None


def test_vacuous_filter_keeps_everything():
    flt = {
        "enabled": True,
        "min_blue": 0,
        "min_pink": 0,
        "min_white": 0,
        "min_green": 0,
        "conditions": [],
    }
    assert keep_filter_matches([], flt) is True


def test_min_blue_threshold():
    factors = [F("Speed", 3, "stat"), F("Stamina", 2, "stat")]
    assert keep_filter_matches(factors, {"min_blue": 5, "conditions": []}) is True
    assert keep_filter_matches(factors, {"min_blue": 6, "conditions": []}) is False


def test_modes_atleast_and_exclude():
    factors = [F("Speed", 3, "stat"), F("Arc Maestro", 2, "unique")]
    # atleast = >= min_stars (legacy "include" behaves the same)
    assert keep_filter_matches(
        factors, {"conditions": [{"colour": "green", "name": "Arc Maestro", "mode": "atleast", "min_stars": 2}]}
    ) is True
    assert keep_filter_matches(
        factors, {"conditions": [{"colour": "green", "name": "Arc Maestro", "mode": "include", "min_stars": 2}]}
    ) is True
    assert keep_filter_matches(
        factors, {"conditions": [{"colour": "green", "name": "Arc Maestro", "mode": "atleast", "min_stars": 3}]}
    ) is False
    # exclude = absent
    assert keep_filter_matches(
        factors, {"conditions": [{"colour": "blue", "name": "Speed", "mode": "exclude", "min_stars": 1}]}
    ) is False


def test_or_within_colour_and_across():
    factors = [F("Speed", 3, "stat"), F("Turf", 2, "aptitude")]
    # OR within blue: Speed has OR Stamina has -> Speed present -> passes
    assert keep_filter_matches(factors, {"conditions": [
        {"colour": "blue", "name": "Speed", "mode": "include", "min_stars": 1},
        {"colour": "blue", "name": "Stamina", "mode": "include", "min_stars": 1},
    ]}) is True
    # OR within blue with neither present -> fails
    assert keep_filter_matches(factors, {"conditions": [
        {"colour": "blue", "name": "Power", "mode": "include", "min_stars": 1},
        {"colour": "blue", "name": "Stamina", "mode": "include", "min_stars": 1},
    ]}) is False
    # AND across colours: blue OK (Speed) AND pink wants Dirt (absent) -> fails
    assert keep_filter_matches(factors, {"conditions": [
        {"colour": "blue", "name": "Speed", "mode": "include", "min_stars": 1},
        {"colour": "pink", "name": "Dirt", "mode": "include", "min_stars": 1},
    ]}) is False


def test_white_counts_skill_race_scenario():
    factors = [F("Corner", 2, "skill"), F("Some Race", 1, "race"), F("Scen", 1, "scenario")]
    assert keep_filter_matches(factors, {"min_white": 4, "conditions": []}) is True
    assert keep_filter_matches(factors, {"min_white": 5, "conditions": []}) is False


def test_self_factors_delegates_to_the_shared_parser(monkeypatch):
    """`self_factors` must PARSE through career_bot.planning.factors, not
    reimplement id decoding locally.

    The previous version of this test monkeypatched `self_factors` to itself
    and asserted `self_factors([]) == []` -- which stays true even if the body
    is gutted to `return []`, so it pinned nothing. This spies on the real
    collaborator instead.
    """
    import career_bot.planning.spark.keep_filter as kf

    calls = []
    sentinel = [{"name": "Speed", "stars": 3, "category": "stat"}]

    def spy(fid_array, factor_map=None, skill_data=None, owner_card_id=None):
        calls.append((list(fid_array), factor_map, skill_data))
        return sentinel

    monkeypatch.setattr(kf, "parse_factor_ids", spy)
    monkeypatch.setattr(kf, "_load_factor_map", lambda: {"fm": 1})
    monkeypatch.setattr(kf, "_load_skill_data", lambda: {"sd": 2})

    out = kf.self_factors([101, 202])

    # the parser's result is returned verbatim, and it was fed BOTH loaders
    assert out is sentinel
    assert calls == [([101, 202], {"fm": 1}, {"sd": 2})]


def test_self_factors_normalizes_a_missing_id_array(monkeypatch):
    """None must reach the parser as an empty list, not as None."""
    import career_bot.planning.spark.keep_filter as kf

    seen = []
    monkeypatch.setattr(
        kf, "parse_factor_ids",
        lambda fid_array, **kw: seen.append(fid_array) or [],
    )
    monkeypatch.setattr(kf, "_load_factor_map", lambda: {})
    monkeypatch.setattr(kf, "_load_skill_data", lambda: {})

    assert kf.self_factors(None) == []
    assert seen == [[]]
