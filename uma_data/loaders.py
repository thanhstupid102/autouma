import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from uma_data.mdb_config import (
    DIRECT_TABLES,
    TEXT_DATA_CATEGORIES,
    configured_master_mdb_path,
    dump_table,
    dump_text_data_category,
    path_access,
)


class _MasterUnavailable(Exception):
    """Raised by _open_master when master.mdb is absent or a required table is missing."""

    def __init__(
        self,
        reason,
        detail=None,
        *,
        master_mdb_path=None,
        missing_tables=(),
    ):
        super().__init__(detail or reason)
        self.reason = reason  # "missing_db" or "missing_tables"
        self.detail = detail
        self.master_mdb_path = master_mdb_path
        self.missing_tables = tuple(sorted(missing_tables))


@contextmanager
def _open_master(base_dir, master_mdb_path, required_tables):
    """Resolve master.mdb, open it, and verify required_tables exist.

    Yields (cursor, existing_tables) inside an open sqlite3 connection. Raises
    _MasterUnavailable (before yielding) when the db can't be found/accessed or
    when required_tables aren't all present -- callers catch this and return
    their own default result, exactly as each loader did inline before.
    """
    db_path = Path(master_mdb_path).expanduser() if master_mdb_path else configured_master_mdb_path(base_dir)
    exists, access_error = path_access(db_path)
    if not exists:
        detail = f"master.mdb not found at {db_path}"
        if access_error:
            detail = f"master.mdb could not be accessed at {db_path}: {access_error}"
        raise _MasterUnavailable(
            "missing_db",
            detail,
            master_mdb_path=db_path,
        )

    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
        missing_tables = set(required_tables) - existing_tables
        if missing_tables:
            names = ", ".join(sorted(missing_tables))
            raise _MasterUnavailable(
                "missing_tables",
                f"master.mdb at {db_path} is missing required table(s): {names}",
                master_mdb_path=db_path,
                missing_tables=missing_tables,
            )

        yield cursor, existing_tables


def load_single_use_tp_campaigns(base_dir, master_mdb_path=None):
    """Load SingleUseTP campaign rows, returning [] when master data is unavailable."""
    try:
        with _open_master(base_dir, master_mdb_path, {"campaign_data"}) as (cursor, _existing_tables):
            campaigns = []
            rows = cursor.execute(
                "SELECT campaign_id, target_id, effect_value_1, start_time, end_time "
                "FROM campaign_data WHERE target_type = 1 AND effect_type_1 = 4;"
            ).fetchall()
            for campaign_id, target_id, effect_value, start_time, end_time in rows:
                try:
                    campaign = {
                        "campaign_id": int(campaign_id or 0),
                        "target_id": int(target_id or 0),
                        "use_tp": int(effect_value or 0),
                        "start_time": int(start_time or 0),
                        "end_time": int(end_time or 0),
                    }
                except (TypeError, ValueError, OverflowError):
                    continue
                if campaign["use_tp"] <= 0:
                    continue
                campaigns.append(campaign)
            return campaigns
    except Exception:
        return []


def resolve_single_mode_use_tp(campaigns, server_time, scenario_id=None, base=30):
    """Return the active campaign TP cost for a global or matching scenario target."""
    now = int(server_time or 0)
    if now <= 0:
        return int(base)
    sid = int(scenario_id or 0)
    for campaign in campaigns:
        start_time = int(campaign.get("start_time") or 0)
        end_time = int(campaign.get("end_time") or 0)
        target_id = int(campaign.get("target_id") or 0)
        if start_time <= now <= end_time and target_id in (0, sid):
            return int(campaign.get("use_tp") or 0)
    return int(base)


def load_item_exchange(base_dir, exchange_id, master_mdb_path=None):
    """Return the item/cost fields for one item_exchange row, or None."""
    try:
        with _open_master(base_dir, master_mdb_path, {"item_exchange"}) as (
            cursor,
            _existing_tables,
        ):
            row = cursor.execute(
                "SELECT change_item_id, change_item_num, pay_item_id, pay_item_num "
                "FROM item_exchange WHERE id = ?;",
                (int(exchange_id),),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return {
            "exchange_id": int(exchange_id),
            "change_item_id": int(row[0] or 0),
            "change_item_num": int(row[1] or 0),
            "pay_item_id": int(row[2] or 0),
            "pay_item_num": int(row[3] or 0),
        }
    except (TypeError, ValueError, OverflowError):
        return None


def load_succession_relations(base_dir, master_mdb_path=None):
    try:
        with _open_master(
            base_dir, master_mdb_path, {"succession_relation", "succession_relation_member"}
        ) as (cursor, _existing_tables):
            points = {
                int(row[0]): int(row[1] or 0)
                for row in cursor.execute("SELECT relation_type, relation_point FROM succession_relation;").fetchall()
                if row[0] is not None
            }
            members: dict[int, set[int]] = {}
            for relation_type, chara_id in cursor.execute(
                "SELECT relation_type, chara_id FROM succession_relation_member;"
            ).fetchall():
                if relation_type is None or chara_id is None:
                    continue
                members.setdefault(int(chara_id), set()).add(int(relation_type))
    except _MasterUnavailable as exc:
        detail = exc.detail if exc.reason == "missing_db" else "succession relation tables missing"
        return {"success": False, "points": {}, "members": {}, "detail": detail}

    return {"success": True, "points": points, "members": members}


def load_g1_win_saddle_ids(base_dir, master_mdb_path=None):
    """Load the win-saddle fields used by ``CalcRelationPoint``.

    The client compares ``group_id`` between two characters' win arrays, then
    awards three points when the saddle on the *left* has
    ``win_saddle_type == 3`` (G1).  Keep the G1 id set for callers that only
    need classification, and expose the group/type maps for the exact
    directional comparison.
    """
    default = {
        "success": False,
        "g1_saddle_ids": set(),
        "saddle_groups": {},
        "saddle_types": {},
    }
    try:
        with _open_master(base_dir, master_mdb_path, {"single_mode_wins_saddle"}) as (cursor, _existing_tables):
            columns = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(single_mode_wins_saddle);").fetchall()
            }
            if not {"id", "group_id", "win_saddle_type"}.issubset(columns):
                return default

            saddle_groups = {}
            saddle_types = {}
            for saddle_id, group_id, saddle_type in cursor.execute(
                "SELECT id, group_id, win_saddle_type FROM single_mode_wins_saddle;"
            ).fetchall():
                if saddle_id is None or group_id is None or saddle_type is None:
                    continue
                saddle_id = int(saddle_id)
                saddle_groups[saddle_id] = int(group_id)
                saddle_types[saddle_id] = int(saddle_type)
    except _MasterUnavailable:
        return default

    return {
        "success": True,
        "g1_saddle_ids": {
            saddle_id for saddle_id, saddle_type in saddle_types.items()
            if saddle_type == 3
        },
        "saddle_groups": saddle_groups,
        "saddle_types": saddle_types,
    }


SCOUT_APTITUDE_COLUMNS = [
    "chara_id",
    "proper_distance_short",
    "proper_distance_mile",
    "proper_distance_middle",
    "proper_distance_long",
    "proper_running_style_nige",
    "proper_running_style_senko",
    "proper_running_style_sashi",
    "proper_running_style_oikomi",
    "proper_ground_turf",
    "proper_ground_dirt",
]


def load_scout_aptitudes(base_dir, master_mdb_path=None):
    """chara_id -> aptitude row from single_mode_scout_chara.

    Needed to build Unity Cup team_data_array client-side (the server sends
    team_data_array back as null before single_mode_team/team_edit -- see
    TeamRosterBuilder.build in career_bot/scenarios/unity_cup/team_roster.py).
    single_mode_scout_chara has multiple rows
    per chara_id (one per support card variant) but the aptitude columns are
    identical across all of them, so the first row per chara_id wins.
    """
    try:
        with _open_master(base_dir, master_mdb_path, {"single_mode_scout_chara"}) as (cursor, _existing_tables):
            columns = ", ".join(SCOUT_APTITUDE_COLUMNS)
            aptitudes = {}
            for row in cursor.execute(f"SELECT {columns} FROM single_mode_scout_chara;").fetchall():
                row_dict = dict(zip(SCOUT_APTITUDE_COLUMNS, row))
                chara_id = row_dict.get("chara_id")
                if chara_id is None:
                    continue
                chara_id = int(chara_id)
                if chara_id not in aptitudes:
                    aptitudes[chara_id] = row_dict
    except _MasterUnavailable as exc:
        return {
            "success": False,
            "aptitudes": {},
            "reason": exc.reason,
            "detail": exc.detail,
            "master_mdb_path": exc.master_mdb_path,
            "missing_tables": list(exc.missing_tables),
        }

    return {"success": True, "aptitudes": aptitudes}


def load_card_chara_map(base_dir, master_mdb_path=None):
    """card_id -> chara_id lookup from card_data.

    Needed to resolve the trainee's chara_id from chara_info.card_id when
    building the Unity Cup team roster (TeamRosterBuilder.build in
    career_bot/scenarios/unity_cup/team_roster.py); falls back to card_id // 100
    when master.mdb is unavailable or the row is missing.
    """
    try:
        with _open_master(base_dir, master_mdb_path, {"card_data"}) as (cursor, _existing_tables):
            card_chara_map = {
                int(card_id): int(chara_id)
                for card_id, chara_id in cursor.execute("SELECT id, chara_id FROM card_data;").fetchall()
                if card_id is not None and chara_id is not None
            }
    except _MasterUnavailable:
        return {"success": False, "card_chara_map": {}}

    return {"success": True, "card_chara_map": card_chara_map}


ROUTE_RACE_COLUMNS = [
    "id",
    "race_set_id",
    "scenario_group_id",
    "target_type",
    "sort_id",
    "turn",
    "race_type",
    "condition_type",
    "condition_id",
    "condition_value_1",
    "condition_value_2",
    "determine_race",
    "determine_race_flag",
]


def load_route_race_objectives(base_dir, master_mdb_path=None):
    """Load route-objective rows and their ordered race-program groups.

    Unity Cup / URA-style scenarios hand each trainee its own route objective
    rows via chara_info.route_race_id_array -- the array elements are
    primary keys directly into single_mode_route_race (verified against a
    real client capture, 2026-07-08: chara 1051's route_race_id_array
    [657..668] are exactly the ids of its objective rows in this table).
    condition_type 1 = race objective (condition_id = race_group_id into
    single_mode_race_group, except target_type 3 rows -- turns 74/76/78
    finals -- whose condition_id is a server-forced sentinel). Most groups
    map identically to one single_mode_program id; the JBC turn-69 groups
    20002/20003 map to four year variants. Resolving condition_id as a program
    id caused Copano Rickey to enter the QE2 Cup instead of JBC Classic and
    fail its route at turn 69 on 2026-07-17.
    condition_type 3 = fan objective (condition_value_1 = fans required by
    `turn`) and is deliberately ignored by the bot; users schedule optional
    races through presets. condition_type 2/7/8/9 are MANT-specific point
    objectives. All rows are returned as-is; scenario callers filter what they
    consume (see career_bot/scenarios/objectives.py)."""
    try:
        with _open_master(
            base_dir,
            master_mdb_path,
            {"single_mode_route_race", "single_mode_race_group"},
        ) as (cursor, existing_tables):
            columns = ", ".join(ROUTE_RACE_COLUMNS)
            objectives = {}
            for row in cursor.execute(f"SELECT {columns} FROM single_mode_route_race;").fetchall():
                row_dict = {col: int(val or 0) for col, val in zip(ROUTE_RACE_COLUMNS, row)}
                route_race_id = row_dict.get("id")
                if not route_race_id:
                    continue
                objectives[route_race_id] = row_dict

            race_groups: dict[int, list[int]] = {}
            rows = cursor.execute(
                "SELECT race_group_id, race_program_id "
                "FROM single_mode_race_group ORDER BY id;"
            ).fetchall()
            for race_group_id, race_program_id in rows:
                group_id = int(race_group_id or 0)
                program_id = int(race_program_id or 0)
                race_groups.setdefault(group_id, []).append(program_id)
    except _MasterUnavailable as exc:
        return {
            "success": False,
            "objectives": {},
            "race_groups": {},
            "reason": exc.reason,
            "detail": exc.detail,
            "master_mdb_path": exc.master_mdb_path,
            "missing_tables": list(exc.missing_tables),
        }

    return {"success": True, "objectives": objectives, "race_groups": race_groups}


LIVE_SQUARE_COLUMNS = [
    "id",
    "square_title_text_id",
    "square_content_text_id",
    "master_bonus_id",
    "square_type",
    "perf_type_1",
    "perf_value_1",
    "perf_type_2",
    "perf_value_2",
    "perf_type_3",
    "perf_value_3",
    "perf_type_4",
    "perf_value_4",
    "perf_type_5",
    "perf_value_5",
]

LIVE_MASTER_BONUS_COLUMNS = [
    "id",
    "master_bonus_type",
    "master_bonus_type_value",
    "master_bonus_gain_type_1",
    "master_bonus_gain_value_1_1",
    "master_bonus_gain_value_1_2",
    "master_bonus_gain_value_1_3",
    "master_bonus_gain_value_1_4",
    "master_bonus_gain_type_2",
    "master_bonus_gain_value_2_1",
    "master_bonus_gain_value_2_2",
    "master_bonus_gain_value_2_3",
    "master_bonus_gain_value_2_4",
    "master_bonus_gain_type_3",
    "master_bonus_gain_value_3_1",
    "master_bonus_gain_value_3_2",
    "master_bonus_gain_value_3_3",
    "master_bonus_gain_value_3_4",
]

LIVE_DATA_COLUMNS = [
    "id",
    "live_type",
    "turn_num",
    "great_success_num",
    "song_num",
    "normal_music_id",
    "special_music_id",
]


def load_live_squares(base_dir, master_mdb_path=None):
    """Grand Live (scenario 3) tree-square catalog, bonuses, and live schedule.

    A square is bought with the five performance tokens the trainee earns from
    training (Dance/Passion/Vocal/Visual/Mental = perf_type 1..5, see
    Gallop.SingleModeScenarioLiveDefine.Performance). single_mode_live_square
    carries the price as five perf_type_N/perf_value_N pairs, which this
    flattens into `cost` ({perf_type: value}); square_type is 1=Parameter,
    2=Skill, 3=Hp, 4=Song. The 21 square_type 4 rows (ids 40000-40020) are the
    rare unique songs -- exactly the ids observed once each in the 2026-07-26
    capture.

    `master_bonus_id` joins single_mode_live_master_bonus, i.e. what the square
    pays out. Gain groups are returned raw because only some of their value
    slots are pinned down by the metadata dump: gain_type 1=Parameter,
    2=Skill, 3=Hp, 5=TrainingBonus (single_mode_live_master_bonus has no
    gain_type 4 row). Callers that only rank squares should use `square_type`
    and `cost`; anything reading the value slots must treat them as unverified.

    `lives` is single_mode_live_live_data, whose turn_num column (24, 36, 48,
    60, 72) is the live_start schedule the capture confirmed."""
    try:
        with _open_master(base_dir, master_mdb_path, {"single_mode_live_square"}) as (cursor, existing_tables):
            bonuses: dict[int, dict[str, int]] = {}
            if "single_mode_live_master_bonus" in existing_tables:
                columns = ", ".join(LIVE_MASTER_BONUS_COLUMNS)
                for row in cursor.execute(f"SELECT {columns} FROM single_mode_live_master_bonus;").fetchall():
                    bonus = {col: int(val or 0) for col, val in zip(LIVE_MASTER_BONUS_COLUMNS, row)}
                    bonuses[bonus["id"]] = bonus

            squares: dict[int, dict[str, Any]] = {}
            columns = ", ".join(LIVE_SQUARE_COLUMNS)
            for row in cursor.execute(f"SELECT {columns} FROM single_mode_live_square;").fetchall():
                square: dict[str, Any] = {col: int(val or 0) for col, val in zip(LIVE_SQUARE_COLUMNS, row)}
                square_id = int(square.get("id") or 0)
                if not square_id:
                    continue
                cost: dict[int, int] = {}
                for slot in range(1, 6):
                    perf_type = square.pop(f"perf_type_{slot}", 0)
                    perf_value = square.pop(f"perf_value_{slot}", 0)
                    if perf_type and perf_value:
                        cost[perf_type] = cost.get(perf_type, 0) + perf_value
                square["cost"] = cost
                square["cost_total"] = sum(cost.values())
                square["bonus"] = bonuses.get(int(square.get("master_bonus_id") or 0))
                squares[square_id] = square

            lives = []
            if "single_mode_live_live_data" in existing_tables:
                columns = ", ".join(LIVE_DATA_COLUMNS)
                rows = cursor.execute(
                    f"SELECT {columns} FROM single_mode_live_live_data ORDER BY turn_num;"
                ).fetchall()
                lives = [{col: int(val or 0) for col, val in zip(LIVE_DATA_COLUMNS, row)} for row in rows]
    except _MasterUnavailable:
        return {"success": False, "squares": {}, "bonuses": {}, "lives": []}

    return {"success": True, "squares": squares, "bonuses": bonuses, "lives": lives}


def load_master_data(cursor, existing_tables):
    # {"tables": {table_name: rows}, "text": {filename: rows}} -- both halves are
    # raw master.mdb dumps, so the row shape is per-table and stays Any.
    master_data: dict[str, dict[str, Any]] = {"tables": {}, "text": {}}
    extracted = []
    skipped = []

    for table in DIRECT_TABLES:
        if table not in existing_tables:
            skipped.append(table)
            continue
        rows = dump_table(cursor, table)
        master_data["tables"][table] = rows
        extracted.append({"table": table, "rows": len(rows)})

    if "text_data" in existing_tables:
        for filename, category in TEXT_DATA_CATEGORIES.items():
            rows = dump_text_data_category(cursor, category)
            master_data["text"][filename] = rows
            extracted.append({"table": filename, "rows": len(rows)})
    else:
        skipped.extend(TEXT_DATA_CATEGORIES)

    return master_data, extracted, skipped
