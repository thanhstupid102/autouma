import json
import logging
from pathlib import Path

from core.runtime_paths import (
    atomic_write_private_text,
    default_master_mdb_path as _default_master_mdb_path,
    resolve_master_mdb_path,
    resolve_state_root,
    state_paths_for,
)

log = logging.getLogger(__name__)


DIRECT_TABLES = [
    "skill_data",
    "single_mode_skill_need_point",
    "race",
    "race_course_set",
    "race_instance",
    "single_mode_program",
    "single_mode_scout_chara",
    "card_rarity_data",
    "available_skill_set",
    "support_card_data",
]

TEXT_DATA_CATEGORIES = {
    "cat_4_text": 4,
    "cat_28_text": 28,
    "cat_47_text": 47,
    "cat_75_text": 75,
    "cat_147_text": 147,
    "cat_181_text": 181,
}


def default_master_mdb_path():
    return _default_master_mdb_path()


def settings_path(base_dir, state_root=None):
    paths = (
        state_paths_for(base_dir, state_root)
        if state_root is not None
        else resolve_state_root(base_dir)
    )
    return paths.settings_overlay_path


def read_settings(base_dir, state_root=None):
    path = settings_path(base_dir, state_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Master data settings load failed: {exc}")
        return {}


def write_settings(base_dir, settings, state_root=None):
    path = settings_path(base_dir, state_root)
    atomic_write_private_text(
        path,
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    )


def configured_master_mdb_path(base_dir, state_root=None):
    return resolve_master_mdb_path(base_dir, state_root)


def master_mdb_mtime_ns(base_dir):
    """Return master.mdb's nanosecond mtime, or None when it is unavailable."""
    try:
        return configured_master_mdb_path(base_dir).stat().st_mtime_ns
    except OSError:
        return None


def set_master_mdb_path(base_dir, master_mdb_path, state_root=None):
    settings = read_settings(base_dir, state_root)
    master_settings = settings.setdefault("master_data", {})
    master_settings["master_mdb_path"] = str(Path(master_mdb_path).expanduser())
    write_settings(base_dir, settings, state_root)
    return status(base_dir, state_root)


def path_access(path):
    try:
        return path.exists(), None
    except OSError as exc:
        return False, str(exc)


def status(base_dir, state_root=None):
    db_path = configured_master_mdb_path(base_dir, state_root)
    exists, access_error = path_access(db_path)
    return {
        "success": True,
        "master_mdb_path": str(db_path),
        "exists": exists,
        "access_error": access_error,
        "requires_user_action": not exists,
    }


def dump_table(cursor, table):
    cursor.execute(f'SELECT * FROM "{table}";')
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor]


def dump_text_data_category(cursor, category):
    cursor.execute(
        'SELECT id, category, "index", text FROM text_data WHERE category = ?;',
        (category,),
    )
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor]


def write_json(path, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    Path(path).write_bytes(payload)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads -> ValueError.
    except (OSError, ValueError) as exc:
        log.warning(f"Master data JSON load failed for {path}: {exc}")
        return default
