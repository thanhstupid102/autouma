from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile


log = logging.getLogger("runtime_paths")

MASTER_JSON_FILENAMES = (
    "chara_list.json",
    "support_list.json",
    "skill_data.json",
    "race_map.json",
    "factor_map.json",
)
MASTER_JSON_PROVENANCE_FILENAME = ".provenance.json"


@dataclass(frozen=True)
class StatePaths:
    source_root: Path
    root: Path

    @property
    def accounts_dir(self) -> Path:
        return self.root / "accounts"

    @property
    def keyring_path(self) -> Path:
        return self.root / ".keyring"

    @property
    def selections_dir(self) -> Path:
        return self.root / "selections"

    @property
    def auto_delete_dir(self) -> Path:
        return self.root / "auto_delete_trained"

    @property
    def api_warehouse_dir(self) -> Path:
        return self.root / "api_warehouse"

    @property
    def bot_config_dir(self) -> Path:
        return self.root / "bot_config"

    @property
    def bot_config_path(self) -> Path:
        return self.bot_config_dir / "active.json"

    @property
    def presets_dir(self) -> Path:
        return self.root / "presets"

    @property
    def race_presets_dir(self) -> Path:
        return self.root / "race_presets"

    @property
    def bot_logs_dir(self) -> Path:
        return self.root / "bot_logs"

    @property
    def trace_logs_dir(self) -> Path:
        return self.root / "trace_logs"

    @property
    def client_version_path(self) -> Path:
        return self.root / "client_version.json"

    @property
    def update_status_path(self) -> Path:
        return self.root / "update_status.json"

    @property
    def discord_path(self) -> Path:
        return self.root / "discord.json"

    @property
    def event_catalog_path(self) -> Path:
        return self.root / "event_catalog.json"

    @property
    def event_prefs_path(self) -> Path:
        return self.root / "event_prefs.json"

    @property
    def master_json_dir(self) -> Path:
        return self.root / "master_json"

    @property
    def settings_overlay_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def master_json_provenance_path(self) -> Path:
        return self.master_json_dir / MASTER_JSON_PROVENANCE_FILENAME

    @property
    def rankpoint_probes_path(self) -> Path:
        return self.root / "rankpoint_probes.jsonl"

    @property
    def crash_trace_path(self) -> Path:
        return self.root / "crash_trace.txt"

    @property
    def timing_dna_path(self) -> Path:
        return self.root / ".timing_dna"


def state_paths_for(source_root: str | os.PathLike[str], state_root: str | os.PathLike[str]) -> StatePaths:
    return StatePaths(
        source_root=Path(source_root).expanduser().resolve(),
        root=Path(state_root).expanduser().resolve(),
    )


def _read_settings(source_root: Path) -> dict:
    return _read_settings_file(source_root / "settings.json")


def _read_settings_file(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            log.warning("Settings file is not a JSON object: %s", path)
            return {}
        return value
    except (OSError, ValueError) as exc:
        log.warning("Settings file could not be read from %s: %s", path, exc)
        return {}


def _configured_state_root(source_root: Path, settings: dict) -> Path | None:
    runtime = settings.get("runtime")
    if runtime is None:
        return None
    if not isinstance(runtime, dict):
        log.warning("settings.json runtime must be an object; ignoring runtime.state_root")
        return None
    configured = runtime.get("state_root")
    if configured is None:
        return None
    if not isinstance(configured, str) or not configured.strip():
        log.warning("settings.json runtime.state_root must be a non-blank string")
        return None
    try:
        path = Path(configured.strip()).expanduser()
        if not path.is_absolute():
            path = source_root / path
        return path.resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning("Invalid settings.json runtime.state_root %r: %s", configured, exc)
        return None


def _running_on_windows() -> bool:
    return os.name == "nt"


def _posix_permissions() -> bool:
    return os.name != "nt"


def _renamed_default_directory(
    parent: Path,
    new_name: str,
    legacy_name: str,
) -> Path:
    new = parent / new_name
    if new.is_dir():
        return new
    legacy = parent / legacy_name
    if legacy.is_dir():
        return legacy
    return new


def _default_state_root() -> Path:
    if _running_on_windows():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data and local_app_data.strip():
            try:
                return _renamed_default_directory(
                    Path(local_app_data.strip()).expanduser(),
                    "ManhattanCafe-uma-auto",
                    "Mcqueen-uma-auto",
                ).resolve()
            except (OSError, RuntimeError, ValueError) as exc:
                log.warning("Invalid LOCALAPPDATA %r: %s", local_app_data, exc)
        return _renamed_default_directory(
            Path.home() / "AppData" / "Local",
            "ManhattanCafe-uma-auto",
            "Mcqueen-uma-auto",
        ).resolve()

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home and xdg_state_home.strip():
        try:
            candidate = Path(xdg_state_home.strip())
            if candidate.is_absolute():
                return _renamed_default_directory(
                    candidate.expanduser(),
                    "manhattancafe-uma-auto",
                    "mcqueen-uma-auto",
                ).resolve()
            log.warning("XDG_STATE_HOME must be absolute; ignoring %r", xdg_state_home)
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("Invalid XDG_STATE_HOME %r: %s", xdg_state_home, exc)
    return _renamed_default_directory(
        Path.home() / ".local" / "state",
        "manhattancafe-uma-auto",
        "mcqueen-uma-auto",
    ).resolve()


def resolve_state_root(source_root: str | os.PathLike[str]) -> StatePaths:
    source = Path(source_root).expanduser().resolve()

    override = os.environ.get("UMA_RUNTIME_DIR")
    if override and override.strip():
        try:
            # Deliberately resolve relative overrides against the current working
            # directory, preserving the existing UMA_RUNTIME_DIR contract.
            return state_paths_for(source, Path(override.strip()).expanduser().resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("Invalid UMA_RUNTIME_DIR %r: %s", override, exc)

    configured = _configured_state_root(source, _read_settings(source))
    if configured is not None:
        return state_paths_for(source, configured)

    legacy = source / "uma_runtime"
    try:
        if legacy.is_dir():
            return state_paths_for(source, legacy)
        if legacy.exists():
            log.warning("Legacy state root exists but is not a directory: %s", legacy)
    except OSError as exc:
        log.warning("Legacy state root could not be inspected at %s: %s", legacy, exc)

    return state_paths_for(source, _default_state_root())


def resolve_master_json_path(
    source_root: str | os.PathLike[str],
    filename: str,
    state_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Prefer one generated state-root file, then its shipped source seed."""
    paths = (
        state_paths_for(source_root, state_root)
        if state_root is not None
        else resolve_state_root(source_root)
    )
    generated = paths.master_json_dir / filename
    if generated.is_file():
        return generated
    return paths.source_root / "data" / "json" / filename


def default_master_mdb_path() -> Path:
    if _running_on_windows():
        profile = os.environ.get("USERPROFILE")
        home = Path(profile).expanduser() if profile and profile.strip() else Path.home()
        return home / "AppData" / "LocalLow" / "Cygames" / "Umamusume" / "master" / "master.mdb"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home and xdg_data_home.strip():
        try:
            candidate = Path(xdg_data_home.strip())
            if candidate.is_absolute():
                return _renamed_default_directory(
                    candidate.expanduser(),
                    "manhattancafe-uma-auto",
                    "mcqueen-uma-auto",
                ) / "master" / "master.mdb"
            log.warning("XDG_DATA_HOME must be absolute; ignoring %r", xdg_data_home)
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("Invalid XDG_DATA_HOME %r: %s", xdg_data_home, exc)
    return _renamed_default_directory(
        Path.home() / ".local" / "share",
        "manhattancafe-uma-auto",
        "mcqueen-uma-auto",
    ) / "master" / "master.mdb"


def _configured_master_mdb_path(settings: dict, label: str) -> Path | None:
    master_data = settings.get("master_data")
    if master_data is None:
        return None
    if not isinstance(master_data, dict):
        log.warning("%s master_data must be an object; ignoring it", label)
        return None
    configured = master_data.get("master_mdb_path")
    if configured is None:
        return None
    if not isinstance(configured, str) or not configured.strip():
        log.warning(
            "%s master_data.master_mdb_path must be a non-blank string",
            label,
        )
        return None
    try:
        # Preserve the established relative-to-CWD behavior for this override.
        return Path(configured.strip()).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning(
            "Invalid %s master_data.master_mdb_path %r: %s",
            label,
            configured,
            exc,
        )
        return None


def resolve_master_mdb_path(
    source_root: str | os.PathLike[str],
    state_root: str | os.PathLike[str] | None = None,
) -> Path:
    source = Path(source_root).expanduser().resolve()
    paths = (
        state_paths_for(source, state_root)
        if state_root is not None
        else resolve_state_root(source)
    )
    overlay = _configured_master_mdb_path(
        _read_settings_file(paths.settings_overlay_path),
        "state-root settings overlay",
    )
    if overlay is not None:
        return overlay
    shipped = _configured_master_mdb_path(
        _read_settings(source),
        "shipped settings.json",
    )
    return shipped if shipped is not None else default_master_mdb_path()


def _chmod_best_effort(path: Path, mode: int, kind: str) -> None:
    if not _posix_permissions():
        return
    try:
        os.chmod(path, mode)
    except OSError as exc:
        log.warning("Could not tighten %s permissions for %s: %s", kind, path, exc)


def ensure_private_dir(path: str | os.PathLike[str]) -> Path:
    directory = Path(path)
    missing: list[Path] = []
    current = directory
    try:
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
    except OSError:
        missing = [directory]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _posix_permissions():
        for created in reversed(missing):
            _chmod_best_effort(created, 0o700, "directory")
        if not missing:
            _chmod_best_effort(directory, 0o700, "directory")
    return directory


def tighten_private_file(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path)
    if resolved.exists():
        _chmod_best_effort(resolved, 0o600, "file")
    return resolved


def _atomic_write_private_bytes(
    path: str | os.PathLike[str], payload: bytes, *, durable: bool,
) -> Path:
    destination = Path(path)
    ensure_private_dir(destination.parent)
    fd = -1
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        if _posix_permissions():
            os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "wb") as output:
            fd = -1
            output.write(payload)
            output.flush()
            if durable:
                os.fsync(output.fileno())
        os.replace(temp_path, destination)
        temp_path = None
        return destination
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_private_bytes(path: str | os.PathLike[str], payload: bytes) -> Path:
    return _atomic_write_private_bytes(path, payload, durable=True)


def atomic_write_private_text(
    path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8",
) -> Path:
    return atomic_write_private_bytes(path, text.encode(encoding))


def atomic_write_private_text_nondurable(
    path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8",
) -> Path:
    """Atomically replace a private cache file without an fsync barrier."""
    return _atomic_write_private_bytes(
        path, text.encode(encoding), durable=False,
    )


def create_private_text_once(
    path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8",
) -> bool:
    destination = Path(path)
    ensure_private_dir(destination.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(destination, flags, 0o600)
    except FileExistsError:
        tighten_private_file(destination)
        return False
    try:
        if _posix_permissions():
            os.chmod(destination, 0o600)
        with os.fdopen(fd, "w", encoding=encoding) as output:
            fd = -1
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return True


def append_private_text(
    path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8",
) -> Path:
    destination = Path(path)
    ensure_private_dir(destination.parent)
    fd = os.open(destination, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if _posix_permissions():
            _chmod_best_effort(destination, 0o600, "file")
        with os.fdopen(fd, "a", encoding=encoding) as output:
            fd = -1
            output.write(text)
    finally:
        if fd >= 0:
            os.close(fd)
    return destination
