import backend.app.domain.career_selection as career_selection


def test_detect_event_available():
    data = {"single_mode_difficulty_info_array": [
        {"difficulty_id": 1003, "open_difficulty_index": 5}]}
    d = career_selection.detect_event_difficulty(data)
    assert d == {"available": True, "difficulty_id": 1003, "max_level": 5}


def test_detect_event_empty_array():
    assert career_selection.detect_event_difficulty({"single_mode_difficulty_info_array": []}) == {
        "available": False, "difficulty_id": 0, "max_level": 0}


def test_detect_event_missing_key():
    assert career_selection.detect_event_difficulty({}) == {
        "available": False, "difficulty_id": 0, "max_level": 0}


def test_detect_event_none_safe():
    assert career_selection.detect_event_difficulty(None)["available"] is False


def test_detect_event_keeps_available_with_server_time():
    data = {"single_mode_difficulty_info_array": [
        {"difficulty_id": 1003, "open_difficulty_index": 4}]}

    assert career_selection.detect_event_difficulty(data, server_time=1781185534) == {
        "available": True, "difficulty_id": 1003, "max_level": 4}


DETECT = {"available": True, "difficulty_id": 1003, "max_level": 5}


def test_payload_disabled():
    assert career_selection.event_difficulty_payload(False, 5, True, DETECT) == (0, 0, 0)


def test_payload_not_available():
    nd = {"available": False, "difficulty_id": 0, "max_level": 0}
    assert career_selection.event_difficulty_payload(True, 3, True, nd) == (0, 0, 0)


def test_payload_level1_no_boost():
    assert career_selection.event_difficulty_payload(True, 1, False, DETECT) == (1003, 401, 0)


def test_payload_level2_boost():
    assert career_selection.event_difficulty_payload(True, 2, True, DETECT) == (1003, 402, 1)


def test_payload_level_clamped_to_max():
    assert career_selection.event_difficulty_payload(True, 9, False, DETECT) == (1003, 405, 0)


def test_payload_level_floor_to_one():
    assert career_selection.event_difficulty_payload(True, 0, False, DETECT) == (1003, 401, 0)
