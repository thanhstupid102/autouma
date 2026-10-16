import json
import logging
from pathlib import Path

import pytest

import core.runtime_paths as runtime_paths


@pytest.fixture(autouse=True)
def isolated_path_environment(monkeypatch):
    for name in (
        "UMA_RUNTIME_DIR",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "LOCALAPPDATA",
        "USERPROFILE",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_home(monkeypatch, home: Path) -> None:
    monkeypatch.setattr(
        runtime_paths.Path,
        "home",
        classmethod(lambda cls: home),
    )


def test_runtime_env_override_wins_and_relative_value_uses_cwd(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    cwd = tmp_path / "cwd"
    xdg_state = tmp_path / "xdg-state"
    source_root.mkdir()
    cwd.mkdir()
    (source_root / "uma_runtime").mkdir()
    (xdg_state / "mcqueen-uma-auto").mkdir(parents=True)
    (source_root / "settings.json").write_text(
        json.dumps({"runtime": {"state_root": "configured"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("UMA_RUNTIME_DIR", "relative-state")

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == (cwd / "relative-state").resolve()


def test_settings_state_root_beats_existing_legacy_and_resolves_from_source(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    xdg_state = tmp_path / "xdg-state"
    source_root.mkdir()
    (source_root / "uma_runtime").mkdir()
    (xdg_state / "mcqueen-uma-auto").mkdir(parents=True)
    (source_root / "settings.json").write_text(
        json.dumps({"runtime": {"state_root": "var/state"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == (source_root / "var" / "state").resolve()


def test_existing_legacy_directory_wins_without_creating_anything(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    legacy = source_root / "uma_runtime"
    xdg_state = tmp_path / "xdg-state"
    legacy.mkdir(parents=True)
    (xdg_state / "mcqueen-uma-auto").mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == legacy.resolve()


@pytest.mark.parametrize(
    ("new_exists", "legacy_exists", "expected_name"),
    (
        (True, False, "manhattancafe-uma-auto"),
        (False, True, "mcqueen-uma-auto"),
        (False, False, "manhattancafe-uma-auto"),
        (True, True, "manhattancafe-uma-auto"),
    ),
    ids=("new", "legacy-only", "neither", "both"),
)
def test_posix_xdg_state_default_prefers_new_then_existing_legacy(
    tmp_path, monkeypatch, new_exists, legacy_exists, expected_name,
):
    source_root = tmp_path / "source"
    xdg_state = tmp_path / "xdg-state"
    source_root.mkdir()
    new = xdg_state / "manhattancafe-uma-auto"
    legacy = xdg_state / "mcqueen-uma-auto"
    if new_exists:
        new.mkdir(parents=True)
    if legacy_exists:
        legacy.mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == (xdg_state / expected_name).resolve()
    assert not (source_root / "uma_runtime").exists()
    assert paths.root.exists() is (new_exists or legacy_exists)


def test_invalid_settings_and_relative_xdg_warn_and_fall_back(
    tmp_path, monkeypatch, caplog,
):
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    source_root.mkdir()
    (source_root / "settings.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    _set_home(monkeypatch, home)
    caplog.set_level(logging.WARNING)

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == (
        home / ".local" / "state" / "manhattancafe-uma-auto"
    ).resolve()
    assert "Settings file could not be read" in caplog.text
    assert "XDG_STATE_HOME must be absolute" in caplog.text


def test_posix_home_state_default_uses_existing_legacy_directory(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    legacy = home / ".local" / "state" / "mcqueen-uma-auto"
    source_root.mkdir()
    legacy.mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    _set_home(monkeypatch, home)

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == legacy.resolve()


@pytest.mark.parametrize(
    ("new_exists", "legacy_exists", "expected_name"),
    (
        (True, False, "ManhattanCafe-uma-auto"),
        (False, True, "Mcqueen-uma-auto"),
        (False, False, "ManhattanCafe-uma-auto"),
        (True, True, "ManhattanCafe-uma-auto"),
    ),
    ids=("new", "legacy-only", "neither", "both"),
)
def test_windows_state_default_prefers_new_then_existing_legacy(
    tmp_path, monkeypatch, new_exists, legacy_exists, expected_name,
):
    source_root = tmp_path / "source"
    local_app_data = tmp_path / "Local"
    source_root.mkdir()
    new = local_app_data / "ManhattanCafe-uma-auto"
    legacy = local_app_data / "Mcqueen-uma-auto"
    if new_exists:
        new.mkdir(parents=True)
    if legacy_exists:
        legacy.mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    paths = runtime_paths.resolve_state_root(source_root)

    assert paths.root == (local_app_data / expected_name).resolve()


@pytest.mark.parametrize(
    ("new_exists", "legacy_exists", "expected_name"),
    (
        (True, False, "manhattancafe-uma-auto"),
        (False, True, "mcqueen-uma-auto"),
        (False, False, "manhattancafe-uma-auto"),
        (True, True, "manhattancafe-uma-auto"),
    ),
    ids=("new", "legacy-only", "neither", "both"),
)
def test_posix_master_xdg_default_prefers_new_then_existing_legacy(
    tmp_path, monkeypatch, new_exists, legacy_exists, expected_name,
):
    xdg_data = tmp_path / "xdg-data"
    new = xdg_data / "manhattancafe-uma-auto"
    legacy = xdg_data / "mcqueen-uma-auto"
    if new_exists:
        new.mkdir(parents=True)
    if legacy_exists:
        legacy.mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))

    assert runtime_paths.default_master_mdb_path() == (
        xdg_data / expected_name / "master" / "master.mdb"
    )


def test_relative_xdg_data_home_falls_back_to_local_share(
    tmp_path, monkeypatch, caplog,
):
    home = tmp_path / "home"
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    _set_home(monkeypatch, home)
    caplog.set_level(logging.WARNING)

    path = runtime_paths.default_master_mdb_path()

    assert path == (
        home
        / ".local"
        / "share"
        / "manhattancafe-uma-auto"
        / "master"
        / "master.mdb"
    )
    assert "XDG_DATA_HOME must be absolute" in caplog.text


def test_posix_home_master_default_uses_existing_legacy_directory(
    tmp_path, monkeypatch,
):
    home = tmp_path / "home"
    legacy = home / ".local" / "share" / "mcqueen-uma-auto"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)
    _set_home(monkeypatch, home)

    assert runtime_paths.default_master_mdb_path() == (
        legacy / "master" / "master.mdb"
    )


def test_windows_master_default_is_game_compatible(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: True)
    monkeypatch.setenv("USERPROFILE", str(profile))

    assert runtime_paths.default_master_mdb_path() == (
        profile
        / "AppData"
        / "LocalLow"
        / "Cygames"
        / "Umamusume"
        / "master"
        / "master.mdb"
    )


def test_master_settings_override_beats_platform_default(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    configured = tmp_path / "custom" / "master.mdb"
    source_root.mkdir()
    (source_root / "settings.json").write_text(
        json.dumps({"master_data": {"master_mdb_path": str(configured)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_running_on_windows", lambda: False)

    assert runtime_paths.resolve_master_mdb_path(source_root) == configured


def test_state_overlay_master_path_beats_shipped_default(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    shipped = tmp_path / "shipped" / "master.mdb"
    runtime = tmp_path / "runtime" / "master.mdb"
    source_root.mkdir()
    state_root.mkdir()
    (source_root / "settings.json").write_text(
        json.dumps({"master_data": {"master_mdb_path": str(shipped)}}),
        encoding="utf-8",
    )
    (state_root / "settings.json").write_text(
        json.dumps({"master_data": {"master_mdb_path": str(runtime)}}),
        encoding="utf-8",
    )

    assert runtime_paths.resolve_master_mdb_path(
        source_root, state_root,
    ) == runtime
