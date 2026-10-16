"""Regression tests for the canonical uma_data master-data pipeline."""

import pathlib
import sqlite3

import uma_data

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _build_test_db(db_path):
    """A minimal sqlite db containing 2 DIRECT_TABLES + a text_data table
    covering one TEXT_DATA_CATEGORIES category (cat_47_text -> category 47)."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE skill_data (id INTEGER, name TEXT)")
        cur.executemany(
            "INSERT INTO skill_data (id, name) VALUES (?, ?)",
            [(1, "Speed Up"), (2, "Guts Up")],
        )
        cur.execute("CREATE TABLE race (id INTEGER, name TEXT)")
        cur.executemany(
            "INSERT INTO race (id, name) VALUES (?, ?)",
            [(10, "Race A"), (20, "Race B")],
        )
        cur.execute(
            'CREATE TABLE text_data (id INTEGER, category INTEGER, "index" INTEGER, text TEXT)'
        )
        cur.execute(
            'INSERT INTO text_data (id, category, "index", text) VALUES (?, ?, ?, ?)',
            (1, 47, 1001, "Skill Name"),
        )
        conn.commit()


class TestMasterDataLoading:
    def test_load_returns_tables_text_extracted_skipped(self, tmp_path):
        db_path = tmp_path / "master.mdb"
        _build_test_db(str(db_path))

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            existing_tables = {row[0] for row in cursor.fetchall()}
            loaded, extracted, skipped = uma_data.load_master_data(
                cursor,
                existing_tables,
            )

        # Direct tables that exist in the db are dumped in full.
        assert len(loaded["tables"]["skill_data"]) == 2
        assert {row["id"] for row in loaded["tables"]["skill_data"]} == {1, 2}
        assert len(loaded["tables"]["race"]) == 2
        assert {row["id"] for row in loaded["tables"]["race"]} == {10, 20}

        # text_data category present in the db is extracted under its filename key.
        assert "cat_47_text" in loaded["text"]
        assert len(loaded["text"]["cat_47_text"]) == 1
        assert loaded["text"]["cat_47_text"][0]["text"] == "Skill Name"

        # extracted records both direct tables and every text category
        # (text_data table exists, so ALL categories are queried, most with 0 rows).
        extracted_names = {item["table"] for item in extracted}
        assert "skill_data" in extracted_names
        assert "race" in extracted_names
        assert "cat_47_text" in extracted_names
        skill_entry = next(item for item in extracted if item["table"] == "skill_data")
        assert skill_entry["rows"] == 2
        race_entry = next(item for item in extracted if item["table"] == "race")
        assert race_entry["rows"] == 2
        cat47_entry = next(item for item in extracted if item["table"] == "cat_47_text")
        assert cat47_entry["rows"] == 1

        # DIRECT_TABLES not present in the db are skipped; text_data categories
        # are NOT skipped because the text_data table itself exists.
        expected_skipped_tables = set(uma_data.DIRECT_TABLES) - {
            "skill_data",
            "race",
        }
        assert expected_skipped_tables <= set(skipped)
        assert not (set(uma_data.TEXT_DATA_CATEGORIES) & set(skipped))

    def test_load_skips_text_categories_when_text_data_table_absent(self, tmp_path):
        db_path = tmp_path / "master_no_text.mdb"
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE skill_data (id INTEGER, name TEXT)")
            cur.execute("INSERT INTO skill_data (id, name) VALUES (1, 'x')")
            conn.commit()

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            existing_tables = {row[0] for row in cursor.fetchall()}
            loaded, extracted, skipped = uma_data.load_master_data(
                cursor,
                existing_tables,
            )

        assert loaded["tables"]["skill_data"] == [{"id": 1, "name": "x"}]
        assert loaded["text"] == {}
        assert set(uma_data.TEXT_DATA_CATEGORIES) <= set(skipped)


class TestSynthesizeAssetRaceData:
    """Regression coverage for canonical race and factor synthesis."""

    def _race_context(self):
        return {
            1: {
                "program": {
                    "month": 1,
                    "half": 1,
                    "race_permission": 1,
                    "base_program_id": 0,
                },
                "race_instance_id": 100,
                "race": {"grade": 100, "course_set": 1},
                "course": {"ground": 1, "distance": 2000, "race_track_id": 10006},
                "name": "Test Race",
            }
        }

    def test_factor_category(self):
        assert uma_data.factor_category(101) == "stat"
        # 4-digit id -> "aptitude"
        assert uma_data.factor_category(1001) == "aptitude"

    def test_returns_dict_with_file_and_rows_and_writes_file(self, tmp_path):
        assets_dir = tmp_path / "assets" / "data"
        assets_dir.mkdir(parents=True)

        result = uma_data.synthesize_asset_race_data(
            tmp_path,
            self._race_context(),
            {},
        )

        assert result is not None
        assert isinstance(result, dict)
        assert result["rows"] == 1
        assert "file" in result

        output_path = assets_dir / "uma_race_data.json"
        assert output_path.exists()

    def test_excludes_non_ui_selectable_races(self, tmp_path):
        assets_dir = tmp_path / "assets" / "data"
        assets_dir.mkdir(parents=True)

        race_context = self._race_context()
        # Make Debut races are filtered out by is_ui_selectable_race.
        race_context[1]["name"] = "Make Debut"

        result = uma_data.synthesize_asset_race_data(
            tmp_path,
            race_context,
            {},
        )

        assert result["rows"] == 0


def test_load_succession_relations_reads_relation_tables(tmp_path):
    import sqlite3
    import uma_data

    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE succession_relation (relation_type INTEGER, relation_point INTEGER)")
        conn.execute("CREATE TABLE succession_relation_member (id INTEGER, relation_type INTEGER, chara_id INTEGER)")
        conn.executemany("INSERT INTO succession_relation VALUES (?, ?)", [(101, 2), (102, 3)])
        conn.executemany("INSERT INTO succession_relation_member VALUES (?, ?, ?)", [
            (1, 101, 1004),
            (2, 101, 1014),
            (3, 102, 1004),
        ])

    result = uma_data.load_succession_relations(ROOT, db_path)

    assert result == {
        "success": True,
        "points": {101: 2, 102: 3},
        "members": {1004: {101, 102}, 1014: {101}},
    }


def test_load_g1_win_saddle_ids_reads_client_group_and_type_fields(tmp_path):
    import sqlite3
    import uma_data

    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE single_mode_wins_saddle "
            "(id INTEGER, group_id INTEGER, win_saddle_type INTEGER)"
        )
        conn.executemany(
            "INSERT INTO single_mode_wins_saddle VALUES (?, ?, ?)",
            [(101, 12, 3), (102, 12, 2), (103, 99, 3)],
        )

    result = uma_data.load_g1_win_saddle_ids(ROOT, db_path)

    assert result == {
        "success": True,
        "g1_saddle_ids": {101, 103},
        "saddle_groups": {101: 12, 102: 12, 103: 99},
        "saddle_types": {101: 3, 102: 2, 103: 3},
    }


def test_load_item_exchange_reads_alarm_clock_cost(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE item_exchange ("
            "id INTEGER, change_item_id INTEGER, change_item_num INTEGER, "
            "pay_item_id INTEGER, pay_item_num INTEGER)"
        )
        conn.execute(
            "INSERT INTO item_exchange VALUES (?, ?, ?, ?, ?)",
            (9001, 95, 1, 43, 10),
        )

    assert uma_data.load_item_exchange(
        ROOT,
        9001,
        master_mdb_path=db_path,
    ) == {
        "exchange_id": 9001,
        "change_item_id": 95,
        "change_item_num": 1,
        "pay_item_id": 43,
        "pay_item_num": 10,
    }
