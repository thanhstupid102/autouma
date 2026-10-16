"""Shared, auth-independent game client version state.

Account captures intentionally keep only account-specific auth authoritative.
Global APP-VER/RES-VER state lives in ``<state_root>/client_version.json`` so a
headless bot can update every imported account with one file change.
"""

import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

from core.runtime_paths import atomic_write_private_text


def client_version_path(state_root):
    return Path(state_root) / "client_version.json"


def load_client_version(base_dir) -> dict:
    """Return the shared version document, tolerating missing/bad state."""
    try:
        value = json.loads(client_version_path(base_dir).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    # Path(base_dir) (TypeError), read_text (OSError / UnicodeDecodeError) and
    # json.loads (JSONDecodeError) -- the latter two both subclass ValueError.
    except (OSError, TypeError, ValueError):
        return {}


def _version_value(base_dir, key) -> str | None:
    value = load_client_version(base_dir).get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


# Registry of shared-state keys tracked via get_field/set_field, mapping each
# key to the default "source" tag used when a setter's caller omits one.
TRACKED_FIELDS = {
    "app_ver": "manual",
    "res_ver": "server",
    "resource_server": "server",
    "master_res_ver": "master-updater",
}


def get_field(base_dir, key) -> str | None:
    """Generic reader for any key registered in TRACKED_FIELDS."""
    return _version_value(base_dir, key)


def get_app_ver(base_dir) -> str | None:
    return get_field(base_dir, "app_ver")


def get_res_ver(base_dir) -> str | None:
    return get_field(base_dir, "res_ver")


def get_resource_server(base_dir) -> str | None:
    """CDN base URL from the last tool/start_session's data_headers.server_list."""
    return get_field(base_dir, "resource_server")


def get_master_res_ver(base_dir) -> str | None:
    """RES-VER the local master.mdb was last refreshed against (master_updater marker)."""
    return get_field(base_dir, "master_res_ver")


def resolve_versions(cv, cfg, default_app, default_res) -> tuple[str, str]:
    """Resolve shared -> captured -> fallback precedence for request headers."""
    cv = cv if isinstance(cv, dict) else {}
    cfg = cfg if isinstance(cfg, dict) else {}
    app_ver = cv.get("app_ver") or cfg.get("app_ver") or default_app
    res_ver = cv.get("res_ver") or cfg.get("res_ver") or default_res
    return str(app_ver), str(res_ver)


def _set_version(base_dir, key, ver, source) -> bool:
    """Best-effort read-modify-write; callers must never fail on local I/O."""
    try:
        value = str(ver or "").strip()
        if not value:
            return False
        state = load_client_version(base_dir)
        state[key] = value
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["source"] = str(source or "").strip() or "manual"
        path = client_version_path(base_dir)
        atomic_write_private_text(path, json.dumps(state, indent=2) + "\n")
        return True
    # load_client_version() never raises; what is left is Path building
    # (TypeError), mkdir/write_text (OSError / UnicodeEncodeError) and
    # json.dumps (TypeError on an unserializable value, ValueError on a cycle).
    except (OSError, TypeError, ValueError):
        return False


def set_field(base_dir, key, ver, source=None):
    """Generic writer for any key registered in TRACKED_FIELDS.

    ``source`` defaults to the key's registered default (TRACKED_FIELDS) when
    omitted."""
    if source is None:
        source = TRACKED_FIELDS.get(key, "manual")
    return _set_version(base_dir, key, ver, source)


def set_app_ver(base_dir, ver, source="manual"):
    return set_field(base_dir, "app_ver", ver, source)


def set_res_ver(base_dir, ver, source="server"):
    return set_field(base_dir, "res_ver", ver, source)


def set_resource_server(base_dir, url, source="server"):
    return set_field(base_dir, "resource_server", url, source)


def set_master_res_ver(base_dir, ver, source="master-updater"):
    return set_field(base_dir, "master_res_ver", ver, source)


def update_res_ver_from_headers(base_dir, current_res_ver, data_headers):
    """Persist a newly surfaced Gallop.DataHeader resource_version.

    Most gameplay responses omit this field. Empty/unchanged values are a no-op;
    a valid new value is returned even if the best-effort disk write fails so the
    live client can immediately use it.
    """
    try:
        value = (data_headers or {}).get("resource_version")
        if not isinstance(value, str) or not value.strip():
            return current_res_ver
        value = value.strip()
        if value == current_res_ver:
            return current_res_ver
        set_res_ver(base_dir, value, source="server")
        return value
    except Exception:
        return current_res_ver


# --- Game-install probing --------------------------------------------------
# Moved here (2026-07) from scripts/publish_client_version.py so the game-machine
# startup auto-publish path (backend.app.app._run_startup_side_effects) and the manual CLI share ONE
# implementation instead of two copies drifting apart. publish_client_version.py
# now imports these names back from this module for its own (more verbose,
# step-by-step) CLI diagnostics; read_app_ver_from_game() below is the terse
# best-effort wrapper the auto-startup path uses.

APP_ID = "3224770"
GAME_DIR_NAME = "UmamusumePrettyDerby"
GLOBAL_GAME_MANAGERS = Path("UmamusumePrettyDerby_Data") / "globalgamemanagers"
APP_VERSION_RE = re.compile(r"^\d{1,2}\.\d{1,3}\.\d{1,3}$")
ENGINE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+f\d+$")


def iter_unity_aligned_strings(blob):
    """Yield printable int32-length-prefixed strings found in a Unity blob."""
    data = memoryview(blob)
    for offset in range(max(0, len(data) - 4)):
        length = struct.unpack_from("<i", data, offset)[0]
        if length < 1 or length > 4096:
            continue
        end = offset + 4 + length
        if end > len(data):
            continue
        raw = bytes(data[offset + 4:end])
        if all(0x20 <= byte <= 0x7E for byte in raw):
            yield offset, raw.decode("ascii")


def app_version_candidates(blob):
    candidates = set()
    for _offset, value in iter_unity_aligned_strings(blob):
        # Unity's player version is adjacent metadata, but its fN suffix is not
        # bundleVersion. Keep the explicit known exclusion as an evidence guard.
        if value == "22.3.62f2" or ENGINE_VERSION_RE.fullmatch(value):
            continue
        if APP_VERSION_RE.fullmatch(value):
            candidates.add(value)
    return sorted(candidates)


def parse_app_version(blob):
    candidates = app_version_candidates(blob)
    if len(candidates) != 1:
        raise ValueError(
            "expected exactly one app-version candidate in globalgamemanagers; "
            f"found {candidates}"
        )
    return candidates[0]


def _read_steam_install_path():
    try:
        import winreg
    except ImportError:
        return None

    locations = [
        (r"SOFTWARE\WOW6432Node\Valve\Steam", winreg.KEY_READ),
        (r"SOFTWARE\Valve\Steam", winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
        (r"SOFTWARE\Valve\Steam", winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
    ]
    for key_name, access in locations:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name, 0, access) as key:
                value, _kind = winreg.QueryValueEx(key, "InstallPath")
            path = Path(str(value)).expanduser()
            if path.is_dir():
                return path
        except OSError:
            continue
    return None


def _decode_vdf_string(value):
    return value.replace(r"\\", "\\").replace(r'\"', '"')


def steam_library_paths(steam_dir):
    """Return Steam's root plus every libraryfolders.vdf path, deduplicated."""
    steam_dir = Path(steam_dir)
    paths = [steam_dir]
    vdf_path = steam_dir / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for match in re.finditer(r'"path"\s*"((?:\\.|[^"\\])*)"', text, re.IGNORECASE):
        paths.append(Path(_decode_vdf_string(match.group(1))))

    result = []
    seen = set()
    for path in paths:
        key = str(path).rstrip("\\/").casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return result


def find_game_dir(steam_dir=None):
    """Find app 3224770 through Steam's registered library folders."""
    steam_dir = Path(steam_dir) if steam_dir else _read_steam_install_path()
    if not steam_dir:
        return None
    for library in steam_library_paths(steam_dir):
        steamapps = library / "steamapps"
        manifest = steamapps / f"appmanifest_{APP_ID}.acf"
        game_dir = steamapps / "common" / GAME_DIR_NAME
        managers = game_dir / GLOBAL_GAME_MANAGERS
        # appmanifest is Steam's authoritative marker that this library contains
        # app 3224770; --game-dir remains the escape hatch for copied installs.
        if manifest.is_file() and managers.is_file():
            return game_dir
    return None


def read_app_ver_from_game(game_dir=None) -> str | None:
    """Best-effort bundleVersion read for the app startup auto-publish path.

    Headless bot boxes have no Steam install of the game -- that, an unreadable
    globalgamemanagers, or an ambiguous version blob are all ordinary outcomes
    here (not errors): every failure mode returns None instead of raising, so a
    caller can silently skip publishing rather than block boot. Callers that want
    granular diagnostics (the manual scripts/publish_client_version.py CLI) should
    call find_game_dir()/parse_app_version() directly instead of this wrapper.
    """
    try:
        resolved = Path(game_dir).expanduser() if game_dir else find_game_dir()
        if not resolved:
            return None
        managers = Path(resolved) / GLOBAL_GAME_MANAGERS
        if not managers.is_file():
            return None
        return parse_app_version(managers.read_bytes())
    except Exception:
        return None
