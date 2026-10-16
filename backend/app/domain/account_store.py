import logging
import time

from backend.app.domain.jsonstore import JsonFileStore
from core.runtime_paths import resolve_state_root
from core.settings import Settings
from uma_api.identity import prepare_account_config_for_storage


log = logging.getLogger(__name__)

state_root = resolve_state_root(Settings.BASE_DIR).root

# These best-effort wrappers retain ordinary path/serialization failure handling.
# Typed secret-store/DPAPI failures intentionally propagate so auth is never
# silently downgraded to plaintext or reported as successfully persisted.
_STORE_WRITE_ERRORS = (OSError, TypeError, ValueError)


def _account_config_store():
    # Unlike the other three stores, account names here do NOT get their
    # repeated-dot runs collapsed (pre-existing behaviour, preserved as-is).
    return JsonFileStore(
        state_root, "accounts", collapse_dot_runs=False, encrypted=True,
    )


def account_store_path(name):
    return _account_config_store().path(name)


def save_account_config(name, cfg):
    if not name or not cfg:
        return False
    safe_cfg = prepare_account_config_for_storage(cfg)
    try:
        _account_config_store().save(name, safe_cfg)
        return True
    except _STORE_WRITE_ERRORS as exc:
        log.warning(f"Failed to save account '{name}': {exc}")
        return False


def load_account_config(name):
    if not name:
        return None
    return _account_config_store().load(name, None)


def _selection_store():
    # Separate dir from accounts/ so it never pollutes SessionManager.known_account_names().
    return JsonFileStore(state_root, "selections")


def selection_store_path(name):
    return _selection_store().path(name)


def save_selection(name, selection):
    """Persist a per-account team selection (deck/trainee/friend/parents/event) so it
    survives re-login and server restart. Best-effort; never raises."""
    if not name:
        return False
    try:
        _selection_store().save(name, selection or {})
        return True
    except _STORE_WRITE_ERRORS as exc:
        log.warning(f"Failed to save selection for '{name}': {type(exc).__name__}")
        return False


def load_selection(name):
    if not name:
        return None
    data = _selection_store().load(name, None)
    return data if isinstance(data, dict) else None


AUTO_DELETE_DEFAULT_CONFIG = {
    "enabled": False,
    "min_blue": 0,
    "min_pink": 0,
    "min_white": 0,
    "min_green": 0,
    "conditions": [],
}


def normalize_auto_delete_config(cfg):
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(AUTO_DELETE_DEFAULT_CONFIG)
    out["enabled"] = bool(cfg.get("enabled", False))
    for key in ("min_blue", "min_pink", "min_white", "min_green"):
        try:
            out[key] = int(cfg.get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    conditions = []
    for condition in cfg.get("conditions") or []:
        if not isinstance(condition, dict):
            continue
        try:
            min_stars = int(condition.get("min_stars", condition.get("minStars", 1)) or 1)
        except (TypeError, ValueError):
            min_stars = 1
        conditions.append({
            "name": str(condition.get("name") or ""),
            "mode": "exclude" if condition.get("mode") == "exclude" else "include",
            "min_stars": min_stars,
        })
    out["conditions"] = conditions
    return out


def _auto_delete_config_store():
    return JsonFileStore(state_root, "auto_delete_trained")


def auto_delete_config_store_path(name):
    return _auto_delete_config_store().path(name)


def save_auto_delete_config(name, cfg):
    if not name:
        return False
    try:
        _auto_delete_config_store().save(name, normalize_auto_delete_config(cfg))
        return True
    except _STORE_WRITE_ERRORS as exc:
        log.warning(f"Failed to save auto-delete config for '{name}': {type(exc).__name__}")
        return False


def _auto_delete_default_config():
    return {**AUTO_DELETE_DEFAULT_CONFIG, "conditions": []}


def load_auto_delete_config(name):
    if not name:
        return _auto_delete_default_config()
    data = _auto_delete_config_store().load(name, None)
    if data is None:
        return _auto_delete_default_config()
    return normalize_auto_delete_config(data)


def apply_auto_delete_config(session):
    cfg = load_auto_delete_config(session.name)
    if session.runner:
        session.runner.auto_delete_trained = cfg
    return cfg


def _steam_token_store():
    # Collapse runs of dots so a name like "../evil" cannot escape the directory.
    return JsonFileStore(
        state_root, "accounts", suffix=".steam.json", encrypted=True,
    )


def steam_token_path(name):
    return _steam_token_store().path(name)


def save_steam_token(name, refresh_token, steam_id=""):
    if not name or not refresh_token:
        return False
    try:
        payload = {
            "refresh_token": refresh_token,
            "steam_id": str(steam_id or ""),
            "saved_at": int(time.time()),
        }
        _steam_token_store().save(name, payload)
        return True
    except _STORE_WRITE_ERRORS as exc:
        log.warning(f"Failed to save Steam token for '{name}': {type(exc).__name__}")
        return False


def load_steam_token(name):
    if not name:
        return None
    return _steam_token_store().load(name, None)


def clear_steam_token(name):
    if not name:
        return
    try:
        _steam_token_store().delete(name)
    except (OSError, TypeError):
        pass
