"""
Tests for career_bot/event_catalog.py (catalog mining + prefs helpers)
and the prefs override in career_bot/events.py EventManager.choose().
"""
import json
import pathlib

from career_bot.events import catalog as catalog_module
from career_bot.events.catalog import (
    build_catalog_from_logs,
    load_catalog,
    load_prefs,
    save_prefs,
)
from career_bot.events import EventManager
from career_bot.engine import CareerRunner


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_log(tmp_path: pathlib.Path, payload: dict, filename="career_log_test.json"):
    """Write a fake career log JSON into tmp_path/uma_runtime/bot_logs/."""
    log_dir = tmp_path / "uma_runtime" / "bot_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_walk_reads_event_summaries_from_capped_api_markers():
    seen = []
    catalog_module._walk({
        "_omitted": "api_body_exceeds_limit",
        "event_catalog_shape": [{
            "story_id": 123,
            "chara_id": 456,
            "event_contents_info": {
                "support_card_id": 789,
                "choice_array": [{"select_index": 1}],
            },
        }],
    }, seen.append)

    assert [event["story_id"] for event in seen] == [123]


def _make_base(tmp_path: pathlib.Path):
    """Ensure data/json/ subdir exists and return base_dir.

    Since commit e6c1293 the product reads every event data file from
    data/json/ (not data/), so fixtures must be written there."""
    (tmp_path / "data" / "json").mkdir(parents=True, exist_ok=True)
    return tmp_path


SUPPORT_MAP = {
    "30108": {"name": "Vodka (Cool)", "rarity": "SSR", "type": "Speed"},
    "10001": {"name": "Special Week", "rarity": "R", "type": "Guts"},
}
CHARA_MAP = {
    "1004": "Maruzensky",
    "1007": "Gold Ship",
}

MINIMAL_EVENT_SUPPORT = {
    "event_id": 10001,
    "chara_id": 0,
    "story_id": 501004511,
    "play_timing": 1,
    "event_contents_info": {
        "support_card_id": 30108,
        "choice_array": [
            {"select_index": 1, "receive_item_id": 0, "target_race_id": 0},
            {"select_index": 2, "receive_item_id": 0, "target_race_id": 0},
        ],
    },
}

MINIMAL_EVENT_SCENARIO = {
    "event_id": 10002,
    "chara_id": 0,
    "story_id": 400000036,   # starts with "4" → scenario
    "play_timing": 1,
    "event_contents_info": {
        "support_card_id": 0,
        "choice_array": [
            {"select_index": 1, "receive_item_id": 0, "target_race_id": 0},
            {"select_index": 2, "receive_item_id": 0, "target_race_id": 0},
            {"select_index": 3, "receive_item_id": 0, "target_race_id": 0},
        ],
    },
}

MINIMAL_EVENT_SINGLE = {
    "event_id": 10003,
    "chara_id": 0,
    "story_id": 200099001,   # neutral prefix, no support/chara → "other"
    "play_timing": 1,
    "event_contents_info": {
        "support_card_id": 0,
        "choice_array": [],
    },
}


# ---------------------------------------------------------------------------
# build_catalog_from_logs
# ---------------------------------------------------------------------------

class TestBuildCatalogFromLogs:
    def test_returns_dict_keyed_by_story_id(self, tmp_path):
        base = _make_base(tmp_path)
        payload = {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT, MINIMAL_EVENT_SCENARIO]}
        _make_log(base, payload)

        catalog = build_catalog_from_logs(base, include_master=False)

        assert isinstance(catalog, dict)
        assert "501004511" in catalog
        assert "400000036" in catalog

    def test_distinct_story_ids(self, tmp_path):
        base = _make_base(tmp_path)
        payload = {
            "unchecked_event_array": [
                MINIMAL_EVENT_SUPPORT,
                MINIMAL_EVENT_SCENARIO,
                MINIMAL_EVENT_SINGLE,
            ]
        }
        _make_log(base, payload)

        catalog = build_catalog_from_logs(base, include_master=False)
        assert len(catalog) == 3

    def test_n_choices_correct(self, tmp_path):
        base = _make_base(tmp_path)
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT, MINIMAL_EVENT_SCENARIO]})

        catalog = build_catalog_from_logs(base, include_master=False)

        assert catalog["501004511"]["n_choices"] == 2
        assert catalog["400000036"]["n_choices"] == 3

    def test_source_support_via_support_card_id(self, tmp_path):
        base = _make_base(tmp_path)
        # Write name maps
        (base / "data" / "json" / "support_list.json").write_text(
            json.dumps(SUPPORT_MAP), encoding="utf-8"
        )
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]})

        catalog = build_catalog_from_logs(base, include_master=False)
        entry = catalog["501004511"]

        assert entry["source"] == "support"
        assert entry["label"] == "Vodka (Cool)"

    def test_source_scenario_via_4_prefix(self, tmp_path):
        base = _make_base(tmp_path)
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SCENARIO]})

        catalog = build_catalog_from_logs(base, include_master=False)
        entry = catalog["400000036"]

        assert entry["source"] == "scenario"
        assert entry["label"] == "Scenario"

    def test_source_chara(self, tmp_path):
        base = _make_base(tmp_path)
        (base / "data" / "json" / "chara_list.json").write_text(
            json.dumps(CHARA_MAP), encoding="utf-8"
        )
        chara_event = {
            "event_id": 20001,
            "chara_id": 1004,
            "story_id": 700001004,   # no "4" prefix, no support
            "play_timing": 1,
            "event_contents_info": {
                "support_card_id": 0,
                "choice_array": [{"select_index": 1, "receive_item_id": 0, "target_race_id": 0}],
            },
        }
        _make_log(base, {"unchecked_event_array": [chara_event]})

        catalog = build_catalog_from_logs(base, include_master=False)
        entry = catalog["700001004"]

        assert entry["source"] == "chara"
        assert entry["label"] == "Maruzensky"

    def test_source_other_fallback(self, tmp_path):
        base = _make_base(tmp_path)
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SINGLE]})

        catalog = build_catalog_from_logs(base, include_master=False)
        entry = catalog["200099001"]

        assert entry["source"] == "other"
        assert entry["label"] == "Event 200099001"

    def test_seen_count_increments(self, tmp_path):
        base = _make_base(tmp_path)
        payload = {
            "unchecked_event_array": [
                MINIMAL_EVENT_SUPPORT,
                MINIMAL_EVENT_SUPPORT,  # same story_id twice
            ]
        }
        _make_log(base, payload)

        catalog = build_catalog_from_logs(base, include_master=False)
        assert catalog["501004511"]["seen_count"] == 2

    def test_bad_log_does_not_abort(self, tmp_path):
        base = _make_base(tmp_path)
        log_dir = base / "uma_runtime" / "bot_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # Write a corrupt file first
        (log_dir / "career_log_bad.json").write_text("NOT VALID JSON", encoding="utf-8")
        # Then a good file
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]},
                  filename="career_log_good.json")

        catalog = build_catalog_from_logs(base, include_master=False)
        # Good file should still be processed
        assert "501004511" in catalog

    def test_mixed_case_and_lowercase_log_names_build_identical_catalogs(
        self, tmp_path,
    ):
        lowercase_base = _make_base(tmp_path / "case-insensitive")
        mixed_case_base = _make_base(tmp_path / "case-sensitive")
        _make_log(
            lowercase_base,
            {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]},
            filename="career_log_mixed.json",
        )
        _make_log(
            mixed_case_base,
            {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]},
            filename="Career_Log_Mixed.JSON",
        )

        lowercase = build_catalog_from_logs(
            lowercase_base, include_master=False,
        )
        mixed_case = build_catalog_from_logs(
            mixed_case_base, include_master=False,
        )

        assert mixed_case == lowercase
        assert mixed_case["501004511"]["seen_count"] == 1

    def test_no_logs_returns_empty_dict(self, tmp_path):
        base = _make_base(tmp_path)
        catalog = build_catalog_from_logs(base, include_master=False)
        assert catalog == {}

    def test_writes_catalog_json(self, tmp_path):
        base = _make_base(tmp_path)
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]})

        build_catalog_from_logs(base, include_master=False)

        out = base / "uma_runtime" / "event_catalog.json"
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert "501004511" in loaded

    def test_nested_unchecked_event_array(self, tmp_path):
        """Events nested inside arbitrary dicts/lists are found."""
        base = _make_base(tmp_path)
        payload = {
            "response_data": {
                "single_mode_info": {
                    "unchecked_event_array": [MINIMAL_EVENT_SCENARIO]
                }
            }
        }
        _make_log(base, payload)

        catalog = build_catalog_from_logs(base, include_master=False)
        assert "400000036" in catalog

    def test_support_fallback_label_when_id_not_in_map(self, tmp_path):
        base = _make_base(tmp_path)
        # Empty support map — support_card_id 30108 not in it
        (base / "data" / "json" / "support_list.json").write_text("{}", encoding="utf-8")
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]})

        catalog = build_catalog_from_logs(base, include_master=False)
        entry = catalog["501004511"]

        assert entry["source"] == "support"
        assert entry["label"] == "Support 30108"

    def test_seeds_rows_from_scraped_effect_db(self, tmp_path):
        """Events present only in data/event_effects_scraped.json (never logged,
        not in the bundled count map) still get a catalog row, so the full
        gametora event DB is configurable in the UI."""
        base = _make_base(tmp_path)
        (base / "data" / "json" / "event_effects_scraped.json").write_text(json.dumps({
            "830001001": {
                "event_name": "A Support Event",
                "source": "ssr",
                "choices": {
                    "1": {"label": "X", "effect": "Power +10"},
                    "2": {"label": "Y", "effect": "Speed +10"},
                },
            },
            "401001001": {
                "event_name": "A Common Event",
                "source": "shared",
                "choices": {"1": {"label": "Z", "effect": "Energy +10"}},
            },
        }), encoding="utf-8")
        # No logs at all
        catalog = build_catalog_from_logs(base, include_master=False)

        assert "830001001" in catalog
        entry = catalog["830001001"]
        assert entry["n_choices"] == 2          # from scraped choice count
        assert entry["name"] == "A Support Event"
        assert entry["source"] == "support"     # scraped source "ssr" → support
        assert entry["seen_count"] == 0         # never logged

    def test_bundled_only_story_id_is_excluded_but_scraped_id_is_included(self, tmp_path):
        """A story_id present only in data/event_choices.json is not Global.
        A story_id present in the EN scrape is Global and remains cataloged."""
        base = _make_base(tmp_path)
        (base / "data" / "json" / "event_choices.json").write_text(json.dumps({
            "899999001": 2,  # bundled only: absent from scrape/master/logs
            "830001001": 3,  # also present in scrape: allowed
        }), encoding="utf-8")
        (base / "data" / "json" / "event_effects_scraped.json").write_text(json.dumps({
            "830001001": {
                "event_name": "A Global Support Event",
                "source": "ssr",
                "choices": {
                    "1": {"label": "A", "effect": ""},
                    "2": {"label": "B", "effect": ""},
                },
            },
        }), encoding="utf-8")

        catalog = build_catalog_from_logs(base, include_master=False)

        assert "899999001" not in catalog
        assert "830001001" in catalog
        assert catalog["830001001"]["n_choices"] == 3

    def test_scraped_source_classifies_shared_as_other(self, tmp_path):
        """A 'shared' scraped event (no owner) is bucketed as 'other', overriding
        the bare story_id prefix guess."""
        base = _make_base(tmp_path)
        (base / "data" / "json" / "event_effects_scraped.json").write_text(json.dumps({
            # 8-prefix would normally guess "support"; scraped "shared" wins.
            "801001001": {
                "event_name": "Common",
                "source": "shared",
                "choices": {"1": {"label": "A", "effect": ""}},
            },
        }), encoding="utf-8")
        catalog = build_catalog_from_logs(base, include_master=False)

        assert catalog["801001001"]["source"] == "other"
        assert catalog["801001001"]["label"] == "Common event"

    def test_logged_choice_count_wins_over_scraped(self, tmp_path):
        """A live log with more choices than the scraped DB keeps the higher count."""
        base = _make_base(tmp_path)
        (base / "data" / "json" / "event_effects_scraped.json").write_text(json.dumps({
            "501004511": {
                "event_name": "Seen Event",
                "source": "char",
                "choices": {"1": {"label": "A", "effect": ""}},  # only 1 in scrape
            },
        }), encoding="utf-8")
        # Log shows 2 choices for the same story_id
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]})

        catalog = build_catalog_from_logs(base, include_master=False)
        assert catalog["501004511"]["n_choices"] == 2


# ---------------------------------------------------------------------------
# load_catalog
# ---------------------------------------------------------------------------

class TestLoadCatalog:
    def test_loads_existing_catalog(self, tmp_path):
        base = _make_base(tmp_path)
        out_dir = base / "uma_runtime"
        out_dir.mkdir(parents=True, exist_ok=True)
        fake = {"501004511": {"story_id": "501004511", "n_choices": 2}}
        (out_dir / "event_catalog.json").write_text(json.dumps(fake), encoding="utf-8")

        catalog = load_catalog(base)
        assert "501004511" in catalog

    def test_builds_if_missing(self, tmp_path):
        base = _make_base(tmp_path)
        _make_log(base, {"unchecked_event_array": [MINIMAL_EVENT_SUPPORT]})

        # No pre-existing event_catalog.json
        catalog = load_catalog(base)
        assert "501004511" in catalog

    def test_returns_dict_when_no_logs_and_no_catalog(self, tmp_path):
        base = _make_base(tmp_path)
        catalog = load_catalog(base)
        # May be non-empty if master.mdb is present (it seeds events); just a dict.
        assert isinstance(catalog, dict)


# ---------------------------------------------------------------------------
# load_prefs / save_prefs
# ---------------------------------------------------------------------------

class TestPrefs:
    def test_round_trip(self, tmp_path):
        base = _make_base(tmp_path)
        prefs = {"501004511": 1, "400000036": 0}

        save_prefs(base, base / "uma_runtime", prefs)
        loaded = load_prefs(base, base / "uma_runtime")

        assert loaded == prefs

    def test_load_missing_file_returns_empty(self, tmp_path):
        base = _make_base(tmp_path)
        assert load_prefs(base, base / "uma_runtime") == {}

    def test_junk_keys_dropped(self, tmp_path):
        base = _make_base(tmp_path)
        raw = {
            "501004511": 1,     # good
            "badkey": "notint", # bad value type
            123: 0,             # bad key type (json keys are always str after parse)
            "negval": -1,       # negative int — invalid
        }
        save_prefs(base, base / "uma_runtime", raw)
        loaded = load_prefs(base, base / "uma_runtime")

        assert "501004511" in loaded
        assert "badkey" not in loaded
        assert "negval" not in loaded

    def test_save_overwrites(self, tmp_path):
        base = _make_base(tmp_path)
        save_prefs(base, base / "uma_runtime", {"501004511": 0})
        save_prefs(base, base / "uma_runtime", {"501004511": 1})
        assert load_prefs(base, base / "uma_runtime") == {"501004511": 1}

    def test_load_corrupt_file_returns_empty(self, tmp_path):
        base = _make_base(tmp_path)
        (base / "data" / "json" / "event_prefs.json").write_text("CORRUPT", encoding="utf-8")
        assert load_prefs(base, base / "uma_runtime") == {}

    def test_zero_index_is_valid(self, tmp_path):
        base = _make_base(tmp_path)
        save_prefs(base, base / "uma_runtime", {"501004511": 0})
        assert load_prefs(base, base / "uma_runtime") == {"501004511": 0}


# ---------------------------------------------------------------------------
# EventManager.choose — prefs override + fallback
# ---------------------------------------------------------------------------

def _make_event(story_id, n_choices, support_card_id=0, chara_id=0, select_indexes=None):
    if select_indexes is None:
        select_indexes = [i + 1 for i in range(n_choices)]
    return {
        "event_id": 9999,
        "chara_id": chara_id,
        "story_id": story_id,
        "play_timing": 1,
        "event_contents_info": {
            "support_card_id": support_card_id,
            "choice_array": [
                {"select_index": select_indexes[i], "receive_item_id": 0, "target_race_id": 0}
                for i in range(len(select_indexes))
            ],
        },
    }


def _make_manager(tmp_path, prefs=None, outcomes=None, scraped_effects=None):
    """Build an EventManager with temp base_dir containing minimal data files.
    EventManager reads everything from data/json/ (commit e6c1293)."""
    base = tmp_path / "base"
    (base / "data" / "json").mkdir(parents=True, exist_ok=True)

    # Write event_outcomes.json (read by EventManager._load)
    eo = outcomes or {}
    (base / "data" / "json" / "event_outcomes.json").write_text(
        json.dumps(eo), encoding="utf-8"
    )

    if prefs is not None:
        (base / "data" / "json" / "event_prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )

    if scraped_effects is not None:
        (base / "data" / "json" / "event_effects_scraped.json").write_text(
            json.dumps(scraped_effects), encoding="utf-8"
        )

    return EventManager(base, base / "uma_runtime")


class _FixedChoiceStrategy:
    def __init__(self, choice):
        self.choice = choice

    def choose_from_event(self, event, current_turn):
        return self.choice


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def check_event(self, event_id, chara_id, choice_number, current_turn):
        call = {
            "event_id": event_id,
            "chara_id": chara_id,
            "choice_number": choice_number,
            "current_turn": current_turn,
        }
        self.calls.append(call)
        return {"data": {}}


class TestEventManagerChoosePrefs:
    # choose() returns the 0-based POSITION in choice_array (select_index is
    # unreliable, e.g. [1,1] or [2,3]); the runner maps it to the wire
    # choice_number convention. The dashboard stores the
    # pref as the same 0-based position ("Choice N" -> N-1).
    def test_pref_returns_choice_position(self, tmp_path):
        """A pref returns the 0-based choice position the user picked."""
        mgr = _make_manager(tmp_path, prefs={"501004511": 0})
        ev = _make_event(501004511, n_choices=2)
        assert mgr.choose(ev) == 0

    def test_pref_index_1(self, tmp_path):
        mgr = _make_manager(tmp_path, prefs={"501004511": 1})
        ev = _make_event(501004511, n_choices=2)
        assert mgr.choose(ev) == 1

    def test_pref_returns_position_not_select_index(self, tmp_path):
        """Even when select_index values are odd ([10,20]), the pref returns the
        POSITION (1), never the select_index (20)."""
        mgr = _make_manager(tmp_path, prefs={"501004511": 1})
        ev = _make_event(501004511, n_choices=2, select_indexes=[10, 20])
        assert mgr.choose(ev) == 1

    def test_pref_clamped_when_out_of_range(self, tmp_path):
        """Pref index >= n_choices falls through to existing logic."""
        mgr = _make_manager(tmp_path, prefs={"501004511": 5})
        ev = _make_event(501004511, n_choices=2)
        # Falls through: no outcome data, 2 choices -> default returns position 1.
        assert mgr.choose(ev) == 1

    def test_pref_0_choices_falls_through(self, tmp_path):
        """Pref set but event has no choices -> returns 0."""
        mgr = _make_manager(tmp_path, prefs={"501004511": 1})
        ev = _make_event(501004511, n_choices=0)
        assert mgr.choose(ev) == 0

    def test_no_pref_uses_existing_hardcode(self, tmp_path):
        """Without a pref, story_id 400004002 returns its hardcoded position 1."""
        mgr = _make_manager(tmp_path, prefs={})
        ev = _make_event(400004002, n_choices=3)
        assert mgr.choose(ev) == 1

    def test_runner_event_maps_position_to_wire_choice_number(self, tmp_path):
        runner = CareerRunner(tmp_path)

        cases = [
            (2, 0, 1),
            (2, 1, 2),
            (3, 2, 3),
            (1, 0, 0),
        ]

        for n_choices, position, expected_wire in cases:
            client = _RecordingClient()
            event = _make_event("111", n_choices)
            payload = {"event_id": 9999, "_event": event, "_current_turn": 1}

            runner._event(client, _FixedChoiceStrategy(position), payload)

            assert client.calls[-1]["choice_number"] == expected_wire

    def test_describe_choice_returns_name_and_effect(self, tmp_path):
        """describe_choice maps a 0-based position to (event_name, effect text)
        for the per-turn log; choices are sorted by select_index."""
        scraped = {
            "700123": {
                "event_name": "Extra Training",
                "choices": {
                    "1": {"effect": "Power +10", "label": "Choice 1"},
                    "2": {"effect": "Energy +30", "label": "Choice 2"},
                },
            }
        }
        mgr = _make_manager(tmp_path, prefs={}, scraped_effects=scraped)
        ev = _make_event("700123", n_choices=2)
        assert mgr.describe_choice(ev, 0) == ("Extra Training", "Power +10")
        assert mgr.describe_choice(ev, 1) == ("Extra Training", "Energy +30")
        # Unknown event -> blank, never raises.
        assert mgr.describe_choice(_make_event("404404", 2), 0) == ("", "")

    def test_event_choice_recorded_in_report(self, tmp_path):
        """The chosen option is persisted into the career report (bot_logs)."""
        runner = CareerRunner(tmp_path)
        runner._init_debug_log()
        client = _RecordingClient()
        event = _make_event("700123", n_choices=2)
        payload = {"event_id": 9999, "_event": event, "_current_turn": 5}

        runner._event(client, _FixedChoiceStrategy(1), payload)

        turn = next(t for t in runner.report["turns"] if t["turn"] == 5)
        rows = [e for e in turn.get("events", []) if e.get("event") == "event_choice"]
        assert rows, "event_choice row missing from report"
        assert rows[0]["position"] == 1
        assert rows[0]["choice_number"] == 2
        assert rows[0]["event_id"] == 9999

    def test_slim_api_data_keeps_check_event_choice(self):
        """check_event api_calls keep the event id + wire choice_number."""
        from career_bot.engine import _slim_api_data
        out = _slim_api_data(
            "REQ",
            "single_mode_free/check_event",
            {"payload": {"current_turn": 3, "event_id": 7017,
                         "chara_id": 1021, "choice_number": 2}},
        )
        assert out["event_id"] == 7017
        assert out["chara_id"] == 1021
        assert out["choice_number"] == 2

    def test_no_pref_400004002_no_choices_returns_0(self, tmp_path):
        """Captured logs show 400004002 can arrive with no choice_array."""
        mgr = _make_manager(tmp_path, prefs={})
        ev = _make_event(400004002, n_choices=0)
        assert mgr.choose(ev) == 0

    def test_no_pref_multi_choice_returns_position_1(self, tmp_path):
        """Without a pref and no outcome data, multi-choice -> position 1."""
        mgr = _make_manager(tmp_path, prefs={})
        ev = _make_event(999999999, n_choices=3)
        assert mgr.choose(ev) == 1

    def test_no_pref_single_choice_returns_0(self, tmp_path):
        mgr = _make_manager(tmp_path, prefs={})
        ev = _make_event(999999998, n_choices=1)
        assert mgr.choose(ev) == 0

    def test_outcome_good_still_used_without_pref(self, tmp_path):
        """Existing outcome-based logic still works when no pref set."""
        outcomes = {
            "400000036": {
                "event_name": "Defeat",
                "outcomes": {"1": "bad", "2": "bad", "3": "good", "4": "good"},
            }
        }
        mgr = _make_manager(tmp_path, prefs={}, outcomes=outcomes)
        # choice_array select_index values 1,2,3 -> the "good" select_index 3 is at
        # position 2.
        ev = _make_event(400000036, n_choices=3)
        assert mgr.choose(ev) == 2

    def test_pref_takes_priority_over_outcome(self, tmp_path):
        """Pref wins even when outcome logic would pick a different position."""
        outcomes = {
            "400000036": {
                "event_name": "Defeat",
                "outcomes": {"1": "bad", "2": "bad", "3": "good"},
            }
        }
        mgr = _make_manager(tmp_path, prefs={"400000036": 0}, outcomes=outcomes)
        ev = _make_event(400000036, n_choices=3)
        # Pref says position 0; outcome logic would pick position 2.
        assert mgr.choose(ev) == 0

    def test_auto_scoring_returns_best_choice_position(self, tmp_path):
        scraped = {
            "501004511": {
                "choices": {
                    "10": {"effect": "Speed +5"},
                    "20": {"effect": "Speed +50"},
                }
            }
        }
        mgr = _make_manager(tmp_path, prefs={}, scraped_effects=scraped)
        ev = _make_event(501004511, n_choices=2, select_indexes=[10, 20])
        # select_index 20 (Speed +50) scores best -> it is at position 1.
        assert mgr.choose(ev) == 1

    def test_pref_overrides_scoring_and_returns_pref_position(self, tmp_path):
        scraped = {
            "501004511": {
                "choices": {
                    "10": {"effect": "Speed +5"},
                    "20": {"effect": "Speed +50"},
                }
            }
        }
        mgr = _make_manager(tmp_path, prefs={"501004511": 0}, scraped_effects=scraped)
        ev = _make_event(501004511, n_choices=2, select_indexes=[10, 20])
        assert mgr.choose(ev) == 0

    def test_prefs_hot_reload(self, tmp_path):
        """Editing prefs file after construction is picked up by choose()."""
        base = tmp_path / "base"
        (base / "data" / "json").mkdir(parents=True, exist_ok=True)
        (base / "data" / "json" / "event_outcomes.json").write_text("{}", encoding="utf-8")
        seed_path = base / "data" / "json" / "event_prefs.json"
        seed_path.write_text(json.dumps({"501004511": 0}), encoding="utf-8")

        mgr = EventManager(base, base / "uma_runtime")
        prefs_path = base / "uma_runtime" / "event_prefs.json"
        ev = _make_event(501004511, n_choices=2)
        assert mgr.choose(ev) == 0  # uses pref

        # Simulate external edit (API call)
        import time
        time.sleep(0.01)  # ensure mtime changes
        prefs_path.write_text(json.dumps({"501004511": 1}), encoding="utf-8")

        # choose() should hot-reload and return the new pref
        assert mgr.choose(ev) == 1

    def test_missing_prefs_file_graceful(self, tmp_path):
        """EventManager works fine when data/event_prefs.json doesn't exist."""
        mgr = _make_manager(tmp_path, prefs=None)
        ev = _make_event(999999999, n_choices=2)
        assert mgr.choose(ev) == 1  # fallback: multi-choice -> position 1

    def test_missing_outcomes_file_graceful(self, tmp_path):
        """EventManager works fine when data/event_outcomes.json doesn't exist."""
        base = tmp_path / "base2"
        (base / "data").mkdir(parents=True, exist_ok=True)
        # No event_outcomes.json, no event_prefs.json
        mgr = EventManager(base, base / "uma_runtime")
        ev = _make_event(999999997, n_choices=2)
        assert mgr.choose(ev) == 1
