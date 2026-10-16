import json

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Request

from career_bot.bot_config import BotConfigStore
from career_bot.delay import configure_timing_dna
from career_bot.planning.presets import PresetStore, RacePresetStore, migrate_race_presets
from core.runtime_paths import (
    StatePaths,
    resolve_master_json_path,
    resolve_state_root,
    state_paths_for,
)
from uma_api.session import SessionManager, get_session_manager
import backend.app.domain.rank_point as rp
import uma_data

from core.settings import Settings


@dataclass
class AppContext:
    base_dir: Path
    state_root: Path
    state_paths: StatePaths
    dir: str
    session_manager: SessionManager
    preset_store: PresetStore
    race_preset_store: RacePresetStore
    bot_config_store: BotConfigStore
    frontend_dist: Path
    images_dir: Path
    chara_map: dict[str, Any] = field(default_factory=dict)
    support_map: dict[str, Any] = field(default_factory=dict)
    skill_data: dict[str, Any] = field(default_factory=dict)
    factor_map: dict[str, Any] = field(default_factory=dict)
    race_map: dict[str, Any] = field(default_factory=dict)
    succession_relation_points: dict[int, int] = field(default_factory=dict)
    succession_relation_members: dict[int, set[int]] = field(default_factory=dict)
    g1_win_saddle_ids: set[int] = field(default_factory=set)

    @property
    def succession_relation_loaded(self) -> bool:
        return rp.succession_relation_loaded

    @property
    def g1_win_saddle_loaded(self) -> bool:
        return rp.g1_win_saddle_loaded

    @property
    def default_account(self) -> str:
        return DEFAULT_ACCOUNT or ''


base_dir = Settings.BASE_DIR
DIR = str(base_dir)
state_paths = resolve_state_root(base_dir)
state_root = state_paths.root
DEFAULT_ACCOUNT = Settings.SWEEP_ACCOUNT
preset_store = None
race_preset_store = None
bot_config_store = None
session_manager = None
images_dir = None
frontend_dist = None


def configure_runtime(base_dir_value=None, default_account=None, state_root_value=None):
    """Rebind the app runtime state owned by this module."""
    global DIR, base_dir, state_root, state_paths
    global preset_store, race_preset_store, bot_config_store
    global session_manager, DEFAULT_ACCOUNT, images_dir, frontend_dist
    if base_dir_value is not None:
        base_dir = Path(base_dir_value).absolute()
        DIR = str(base_dir)
    state_paths = (
        state_paths_for(base_dir, state_root_value)
        if state_root_value is not None
        else resolve_state_root(base_dir)
    )
    state_root = state_paths.root
    rp.base_dir = base_dir
    rp.state_root = state_root
    import backend.app.domain.account_store as _account_store
    _account_store.state_root = state_root
    configure_timing_dna(state_root, base_dir)
    # None preserves the current base_dir, matching the legacy factory behavior.
    if default_account is not None:
        DEFAULT_ACCOUNT = default_account
    preset_store = PresetStore(state_root, base_dir)
    race_preset_store = RacePresetStore(state_root, base_dir)
    bot_config_store = BotConfigStore(base_dir, state_root)
    try:
        migrate_race_presets(state_root, base_dir)
    except Exception:
        pass
    # The production runtime shares the process singleton; alternate directories
    # receive an isolated manager so account state cannot bleed across runtimes.
    if DIR == str(Settings.BASE_DIR):
        shared_manager = get_session_manager()
        if shared_manager.state_root == str(state_root):
            session_manager = shared_manager
        else:
            session_manager = SessionManager(
                base_dir=DIR,
                state_root=str(state_root),
            )
    else:
        session_manager = SessionManager(
            base_dir=str(DIR),
            state_root=str(state_root),
        )
    images_dir = base_dir / 'data' / 'images'
    frontend_dist = base_dir / 'frontend' / 'dist'

    def _load_json(path, default):
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        # `path` is always a Path built by the caller: exists/read_text raise
        # OSError, and json.loads/decoding raise ValueError subclasses.
        except (OSError, ValueError):
            return default

    rp.base_dir = base_dir
    rp.chara_path = resolve_master_json_path(
        base_dir, 'chara_list.json', state_root,
    )
    rp.support_path = resolve_master_json_path(
        base_dir, 'support_list.json', state_root,
    )
    rp.skill_data_path = resolve_master_json_path(
        base_dir, 'skill_data.json', state_root,
    )
    rp.factor_map_path = resolve_master_json_path(
        base_dir, 'factor_map.json', state_root,
    )
    rp.race_map_path = resolve_master_json_path(
        base_dir, 'race_map.json', state_root,
    )
    rp.chara_map = _load_json(rp.chara_path, {})
    rp.support_map = _load_json(rp.support_path, {})
    rp.skill_data = _load_json(rp.skill_data_path, {})
    rp.factor_map = _load_json(rp.factor_map_path, {})
    rp.race_map = _load_json(rp.race_map_path, {})
    rp.load_succession_relation_data()
    rp.load_g1_win_saddle_data()
    rp.rank_point_master_mdb_mtime_ns = uma_data.master_mdb_mtime_ns(base_dir)
    return {
        'base_dir': base_dir,
        'state_root': state_root,
        'state_paths': state_paths,
        'dir': DIR,
        'default_account': DEFAULT_ACCOUNT,
        'session_manager': session_manager,
        'preset_store': preset_store,
        'race_preset_store': race_preset_store,
        'bot_config_store': bot_config_store,
        'frontend_dist': frontend_dist,
        'images_dir': images_dir,
    }


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def _snapshot(base: dict) -> AppContext:
    return AppContext(
        base_dir=Path(base['base_dir']),
        state_root=Path(base['state_root']),
        state_paths=base['state_paths'],
        dir=str(base['dir']),
        session_manager=base['session_manager'],
        preset_store=base['preset_store'],
        race_preset_store=base['race_preset_store'],
        bot_config_store=base['bot_config_store'],
        frontend_dist=Path(base['frontend_dist']),
        images_dir=Path(base['images_dir']),
        chara_map=rp.chara_map,
        support_map=rp.support_map,
        skill_data=rp.skill_data,
        factor_map=rp.factor_map,
        race_map=rp.race_map,
        succession_relation_points=rp.succession_relation_points,
        succession_relation_members=rp.succession_relation_members,
        g1_win_saddle_ids=rp.g1_win_saddle_ids,
    )


def reload_master_json_data(base_dir_value=None, state_root_value=None) -> bool:
    """Rebind generated master JSON maps without replacing live context objects."""
    source_root = Path(base_dir_value or base_dir).absolute()
    runtime_root = Path(state_root_value or state_root).resolve()

    def load(name):
        path = resolve_master_json_path(source_root, name, runtime_root)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return path, value if isinstance(value, dict) else {}

    for path_attr, map_attr, filename in (
        ("chara_path", "chara_map", "chara_list.json"),
        ("support_path", "support_map", "support_list.json"),
        ("skill_data_path", "skill_data", "skill_data.json"),
        ("factor_map_path", "factor_map", "factor_map.json"),
        ("race_map_path", "race_map", "race_map.json"),
    ):
        path, value = load(filename)
        setattr(rp, path_attr, path)
        target = getattr(rp, map_attr)
        target.clear()
        target.update(value)

    from backend.app.domain.rank_point import lineage
    lineage.skill_data_path = rp.skill_data_path
    lineage.factor_map_path = rp.factor_map_path
    lineage.race_map_path = rp.race_map_path

    from career_bot.planning.spark import keep_filter
    keep_filter._FACTOR_MAP = None
    keep_filter._SKILL_DATA = None
    return True


def create_context(
    base_dir: str | Path | None = None,
    default_account: str | None = None,
    state_root: str | Path | None = None,
) -> AppContext:
    return _snapshot(configure_runtime(base_dir, default_account, state_root))


def load_succession_relation_data(ctx: AppContext | None = None) -> bool:
    ok = rp.load_succession_relation_data()
    if ctx is not None:
        ctx.succession_relation_points = rp.succession_relation_points
        ctx.succession_relation_members = rp.succession_relation_members
    return ok


def load_g1_win_saddle_data(ctx: AppContext | None = None) -> bool:
    ok = rp.load_g1_win_saddle_data()
    if ctx is not None:
        ctx.g1_win_saddle_ids = rp.g1_win_saddle_ids
    return ok


configure_runtime()
