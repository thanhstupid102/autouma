import importlib
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time

import pytest

import core.runtime_paths as runtime_paths
import uma_data
from backend.app.app import create_app
from career_bot.planning.spark.reroll import load_factor_context
from core.runtime_paths import (
    MASTER_JSON_FILENAMES,
    MASTER_JSON_PROVENANCE_FILENAME,
    resolve_master_json_path,
    state_paths_for,
)
import uma_data.legacy_json as legacy_json


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed_source(source_root: Path) -> dict[str, Path]:
    paths = {}
    for filename in MASTER_JSON_FILENAMES:
        path = source_root / "data" / "json" / filename
        _write_json(path, {"origin": f"seed:{filename}"})
        paths[filename] = path
    asset = source_root / "assets" / "data" / "uma_race_data.json"
    _write_json(asset, {"races": []})
    paths["uma_race_data.json"] = asset
    return paths


def _minimal_master_data():
    return {
        "tables": {
            "skill_data": [{"id": 1001, "rarity": 1, "group_id": 100}],
            "card_rarity_data": [{"card_id": 100101}],
            "support_card_data": [
                {"id": 200101, "rarity": 3, "command_id": 101}
            ],
        },
        "text": {
            "cat_4_text": [{"index": 100101, "text": "State Chara"}],
            "cat_47_text": [{"index": 1001, "text": "State Skill"}],
            "cat_75_text": [{"index": 200101, "text": "State Support"}],
            "cat_147_text": [{"index": 101, "text": "State Factor"}],
        },
    }


def test_master_json_precedence_is_per_file_for_context_and_reroll(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    seeds = _seed_source(source_root)
    generated_dir = state_paths_for(source_root, state_root).master_json_dir
    _write_json(
        generated_dir / "chara_list.json",
        {"origin": "state:chara_list.json"},
    )
    _write_json(
        generated_dir / "factor_map.json",
        {"origin": "state:factor_map.json"},
    )

    assert resolve_master_json_path(
        source_root, "chara_list.json", state_root,
    ) == generated_dir / "chara_list.json"
    assert resolve_master_json_path(
        source_root, "support_list.json", state_root,
    ) == seeds["support_list.json"]

    app = create_app(source_root, state_root=state_root)
    assert app.state.ctx.chara_map == {"origin": "state:chara_list.json"}
    assert app.state.ctx.support_map == {"origin": "seed:support_list.json"}

    factor_map, skill_data = load_factor_context(source_root, state_root)
    assert factor_map == {"origin": "state:factor_map.json"}
    assert skill_data == {"origin": "seed:skill_data.json"}


def test_generate_writes_state_root_and_preserves_shipped_files(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    shipped = _seed_source(source_root)
    before = {
        name: (path.read_bytes(), path.stat().st_mtime_ns)
        for name, path in shipped.items()
    }
    database_path = tmp_path / "master.mdb"
    with sqlite3.connect(database_path):
        pass
    monkeypatch.setattr(
        legacy_json,
        "load_master_data",
        lambda cursor, tables: (_minimal_master_data(), [], []),
    )

    result = legacy_json.generate(
        source_root,
        database_path,
        state_root=state_root,
    )

    assert result["success"] is True
    generated_dir = state_paths_for(source_root, state_root).master_json_dir
    assert {path.name for path in generated_dir.iterdir()} == set(
        (*MASTER_JSON_FILENAMES, MASTER_JSON_PROVENANCE_FILENAME)
    )
    for name, path in shipped.items():
        assert path.read_bytes() == before[name][0]
        assert path.stat().st_mtime_ns == before[name][1]


def _prepare_startup(tmp_path, monkeypatch):
    app_module = importlib.import_module("backend.app.app")
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    source_root.mkdir()
    database_path = tmp_path / "master.mdb"
    database_path.write_bytes(b"master")
    master_mtime_ns = time.time_ns() - 2_000_000_000
    os.utime(database_path, ns=(master_mtime_ns, master_mtime_ns))
    _write_json(
        source_root / "settings.json",
        {"master_data": {"master_mdb_path": str(database_path)}},
    )
    monkeypatch.setattr(app_module, "configure_console_logging", lambda: None)
    monkeypatch.setattr(
        app_module.client_version,
        "read_app_ver_from_game",
        lambda: "1.0.0",
    )
    monkeypatch.setattr(
        app_module.client_version,
        "set_app_ver",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        importlib.import_module("uma_api.appstore_version"),
        "fetch_app_ver_from_store",
        lambda: "1.0.0",
    )
    monkeypatch.setattr(
        importlib.import_module("uma_data.master_updater"),
        "ensure_current_headless",
        lambda *args, **kwargs: False,
    )
    return app_module, source_root, state_root, database_path


def _write_current_generated_files(
    source_root: Path,
    state_root: Path,
    database_path: Path,
    mtimes_ns: tuple[int, ...] = (),
) -> None:
    output_dir = state_paths_for(source_root, state_root).master_json_dir
    for index, filename in enumerate(MASTER_JSON_FILENAMES):
        path = output_dir / filename
        _write_json(path, {})
        if mtimes_ns:
            mtime_ns = mtimes_ns[index % len(mtimes_ns)]
            os.utime(path, ns=(mtime_ns, mtime_ns))
    legacy_json._write_provenance(
        source_root,
        state_root,
        legacy_json.master_mdb_sha256(database_path),
        complete=True,
    )


@pytest.mark.parametrize(
    "stale_kind",
    ["missing", "missing_provenance", "mismatched_provenance"],
)
def test_startup_generation_runs_only_when_output_is_stale(
    tmp_path, monkeypatch, stale_kind,
):
    app_module, source_root, state_root, database_path = _prepare_startup(
        tmp_path, monkeypatch,
    )
    if stale_kind != "missing":
        _write_current_generated_files(
            source_root, state_root, database_path,
        )
        provenance = state_paths_for(
            source_root, state_root,
        ).master_json_provenance_path
        if stale_kind == "missing_provenance":
            provenance.unlink()
        else:
            legacy_json._write_provenance(
                source_root,
                state_root,
                hashlib.sha256(b"different-master").hexdigest(),
                complete=True,
            )

    calls = []

    def regenerate(base_dir, *, state_root):
        calls.append((Path(base_dir), Path(state_root)))
        _write_current_generated_files(
            source_root, state_root, database_path,
        )
        return {"success": True}

    monkeypatch.delenv("SWEEPY_SKIP_STARTUP_GEN", raising=False)
    monkeypatch.setattr(app_module.uma_data, "generate", regenerate)

    app_module._run_startup_side_effects(source_root, state_root)

    assert calls == [(source_root, state_root)]


def test_startup_generation_skips_current_output(tmp_path, monkeypatch):
    app_module, source_root, state_root, database_path = _prepare_startup(
        tmp_path, monkeypatch,
    )
    master_mtime_ns = database_path.stat().st_mtime_ns
    _write_current_generated_files(
        source_root,
        state_root,
        database_path,
        (
            master_mtime_ns - 5_000_000_000,
            master_mtime_ns + 5_000_000_000,
            master_mtime_ns,
        ),
    )
    monkeypatch.delenv("SWEEPY_SKIP_STARTUP_GEN", raising=False)
    monkeypatch.setattr(
        app_module.uma_data,
        "generate",
        lambda *args, **kwargs: pytest.fail("current output must not regenerate"),
    )

    app_module._run_startup_side_effects(source_root, state_root)


def test_suppressed_startup_generation_warns_with_remedy(
    tmp_path, monkeypatch, caplog,
):
    app_module, source_root, state_root, _ = _prepare_startup(
        tmp_path, monkeypatch,
    )
    monkeypatch.setenv("SWEEPY_SKIP_STARTUP_GEN", "1")
    monkeypatch.setattr(
        app_module.uma_data,
        "generate",
        lambda *args, **kwargs: pytest.fail("skip flag must suppress generation"),
    )
    caplog.set_level(logging.WARNING)

    app_module._run_startup_side_effects(source_root, state_root)

    assert "chara_list.json" in caplog.text
    assert "python scripts/generate_master_data.py" in caplog.text


def test_generate_succeeds_without_writing_below_source_root(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    _seed_source(source_root)
    database_path = tmp_path / "master.mdb"
    with sqlite3.connect(database_path):
        pass
    monkeypatch.setattr(
        legacy_json,
        "load_master_data",
        lambda cursor, tables: (_minimal_master_data(), [], []),
    )

    source_write_attempts = []
    if os.name == "nt":
        original_write_text = Path.write_text

        def guarded_write_text(path, *args, **kwargs):
            if path.resolve().is_relative_to(source_root.resolve()):
                source_write_attempts.append(path)
                raise AssertionError(f"source-tree write attempted: {path}")
            return original_write_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", guarded_write_text)
    else:
        for path in source_root.rglob("*"):
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
        os.chmod(source_root, 0o555)

    try:
        result = legacy_json.generate(
            source_root,
            database_path,
            state_root=state_root,
        )
    finally:
        if os.name != "nt":
            os.chmod(source_root, 0o755)
            for path in source_root.rglob("*"):
                os.chmod(path, 0o755 if path.is_dir() else 0o644)

    assert result["success"] is True
    assert source_write_attempts == []
    output_dir = state_paths_for(source_root, state_root).master_json_dir
    assert all((output_dir / name).is_file() for name in MASTER_JSON_FILENAMES)


def test_master_path_override_survives_restart_with_read_only_source(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    shipped_path = tmp_path / "shipped" / "master.mdb"
    override_path = tmp_path / "runtime" / "master.mdb"
    _write_json(
        source_root / "settings.json",
        {"master_data": {"master_mdb_path": str(shipped_path)}},
    )
    before = (source_root / "settings.json").read_bytes()
    original_write = runtime_paths.atomic_write_private_bytes

    def reject_source_write(path, payload):
        destination = Path(path).resolve()
        if destination.is_relative_to(source_root.resolve()):
            raise PermissionError(f"source tree is read-only: {destination}")
        return original_write(destination, payload)

    monkeypatch.setattr(
        runtime_paths,
        "atomic_write_private_bytes",
        reject_source_write,
    )

    uma_data.set_master_mdb_path(
        source_root, override_path, state_root,
    )

    assert (source_root / "settings.json").read_bytes() == before
    assert state_paths_for(
        source_root, state_root,
    ).settings_overlay_path.is_file()
    # A fresh resolve is the restart boundary; no in-memory settings cache exists.
    assert runtime_paths.resolve_master_mdb_path(
        source_root, state_root,
    ) == override_path
