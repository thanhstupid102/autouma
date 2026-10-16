import errno
import os
import stat
from pathlib import Path

import pytest

import core.runtime_paths as runtime_paths
from backend.app.domain.jsonstore import JsonFileStore
from career_bot.bot_config import BotConfigStore
from career_bot.planning.presets import PresetStore, RacePresetStore
from integrations.discord import notify
from uma_api import account_io, api_warehouse, client_version, secret_store
from uma_api.session import SessionManager
from uma_api.trace import TraceLog


@pytest.fixture(autouse=True)
def _clear_secret_cache():
    secret_store.clear_key_cache()
    yield
    secret_store.clear_key_cache()


def _configure_portable_secrets(monkeypatch) -> None:
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", "state-root-test-passphrase")
    monkeypatch.setattr(secret_store, "SCRYPT_N", 2 ** 10)
    secret_store.clear_key_cache()


def _assert_under(path: Path, root: Path) -> None:
    assert Path(path).resolve().is_relative_to(root.resolve())


def test_existing_legacy_root_keeps_encrypted_accounts_decryptable_and_discoverable(
    tmp_path, monkeypatch,
):
    source_root = tmp_path / "source"
    state_root = source_root / "uma_runtime"
    accounts_dir = state_root / "accounts"
    accounts_dir.mkdir(parents=True)
    monkeypatch.delenv("UMA_RUNTIME_DIR", raising=False)
    _configure_portable_secrets(monkeypatch)

    game = {"viewer_id": 1234, "auth_key": "encrypted-game-auth"}
    steam = {"refresh_token": "encrypted-steam-token", "steam_id": "7656"}
    game_path = accounts_dir / "legacy-user.json"
    steam_path = accounts_dir / "legacy-user.steam.json"
    secret_store.save_json(game_path, game, state_root)
    secret_store.save_json(steam_path, steam, state_root)
    assert game_path.read_bytes().startswith(secret_store.MAGIC)
    assert steam_path.read_bytes().startswith(secret_store.MAGIC)
    assert (state_root / ".keyring").read_bytes().startswith(
        secret_store.KEYRING_MAGIC
    )

    paths = runtime_paths.resolve_state_root(source_root)
    secret_store.clear_key_cache()
    loaded = account_io.read_account_files(
        str(paths.accounts_dir), paths.root, "legacy-user",
    )
    manager = SessionManager(str(source_root), str(paths.root))

    assert paths.root == state_root.resolve()
    assert loaded == {"game": game, "steam": steam}
    assert manager.known_account_names() == ["legacy-user"]


def test_account_and_steam_payloads_share_only_the_state_root_keyring(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    accounts_dir = state_root / "accounts"
    accounts_dir.mkdir(parents=True)
    _configure_portable_secrets(monkeypatch)

    game_path = accounts_dir / "account.json"
    steam_path = accounts_dir / "account.steam.json"
    secret_store.save_json(game_path, {"auth_key": "game"}, state_root)
    secret_store.save_json(steam_path, {"refresh_token": "steam"}, state_root)

    expected = state_root / ".keyring"
    assert secret_store._keyring_path_for(game_path, state_root) == expected.resolve()
    assert secret_store._keyring_path_for(steam_path, state_root) == expected.resolve()
    assert list(state_root.rglob(".keyring")) == [expected]
    assert secret_store.load_json(game_path, state_root) == {"auth_key": "game"}
    assert secret_store.load_json(steam_path, state_root) == {
        "refresh_token": "steam"
    }

    outside = tmp_path / "outside" / "account.json"
    with pytest.raises(secret_store.SecretStorePathError):
        secret_store.save_json(outside, {"auth_key": "must-not-write"}, state_root)
    assert not outside.exists()
    outside.parent.mkdir()
    outside.write_text('{"auth_key": "legacy-plaintext"}', encoding="utf-8")
    with pytest.raises(secret_store.SecretStorePathError):
        secret_store.load_json(outside, state_root)
    with pytest.raises(secret_store.SecretStorePathError):
        secret_store.migrate_file(outside, state_root)
    assert outside.read_text(encoding="utf-8") == '{"auth_key": "legacy-plaintext"}'


def test_discovery_scans_only_the_selected_accounts_directory(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "selected-state"
    selected_accounts = state_root / "accounts"
    legacy_accounts = source_root / "uma_runtime" / "accounts"
    selected_accounts.mkdir(parents=True)
    legacy_accounts.mkdir(parents=True)
    (selected_accounts / "selected.json").write_text("{}", encoding="utf-8")
    (selected_accounts / "selected.steam.json").write_text("{}", encoding="utf-8")
    (legacy_accounts / "legacy-only.json").write_text("{}", encoding="utf-8")

    manager = SessionManager(str(source_root), str(state_root))

    assert Path(manager.accounts_dir()) == selected_accounts.resolve()
    assert manager.known_account_names() == ["selected"]


def test_production_state_and_shipped_asset_paths_stay_in_their_roots(tmp_path):
    source_root = (tmp_path / "source").resolve()
    state_root = (tmp_path / "state").resolve()
    source_root.mkdir()
    paths = runtime_paths.state_paths_for(source_root, state_root)
    bot_config = BotConfigStore(source_root, state_root)
    account_store = JsonFileStore(state_root, "accounts", encrypted=True)
    session_manager = SessionManager(str(source_root), str(state_root))

    state_paths = {
        "account config": account_store.path("account"),
        "account discovery": Path(session_manager.accounts_dir()),
        "keyring": paths.keyring_path,
        "selections": paths.selections_dir / "account.json",
        "auto-delete": paths.auto_delete_dir / "account.json",
        "API warehouse": api_warehouse.response_path(
            state_root, "account", "load/index",
        ),
        "client version": client_version.client_version_path(state_root),
        "update status": paths.update_status_path,
        "Discord": notify._discord_path(state_root),
        "trace": TraceLog(paths.trace_logs_dir).trace_dir,
        "career logs": paths.bot_logs_dir / "career_log_account.json",
        "crash trace": paths.crash_trace_path,
        "event catalog": paths.event_catalog_path,
        "event prefs": paths.event_prefs_path,
        "master JSON": paths.master_json_dir,
        "settings overlay": paths.settings_overlay_path,
        "master JSON provenance": paths.master_json_provenance_path,
        "rank-point probes": paths.rankpoint_probes_path,
        "bot config": bot_config.active_path,
        "presets": PresetStore(state_root).preset_dir,
        "race presets": RacePresetStore(state_root).preset_dir,
        "timing DNA": paths.timing_dna_path,
    }
    for label, path in state_paths.items():
        _assert_under(path, state_root), label

    shipped_paths = {
        "settings": source_root / "settings.json",
        "bot config default": bot_config.default_path,
        "event prefs seed": source_root / "data" / "json" / "event_prefs.json",
        "character list": source_root / "data" / "json" / "chara_list.json",
        "support list": source_root / "data" / "json" / "support_list.json",
        "skill data": source_root / "data" / "json" / "skill_data.json",
        "race map": source_root / "data" / "json" / "race_map.json",
        "factor map": source_root / "data" / "json" / "factor_map.json",
        "event choices": source_root / "data" / "json" / "event_choices.json",
        "event effects": source_root / "data" / "json" / "event_effects_scraped.json",
        "event outcomes": source_root / "data" / "json" / "event_outcomes.json",
        "event owners": source_root / "data" / "json" / "event_owners.json",
        "images": source_root / "data" / "images",
        "race asset": source_root / "assets" / "data" / "uma_race_data.json",
        "frontend": source_root / "frontend" / "dist",
        "Frida hooks": source_root / "integrations" / "frida" / "js",
        "Steam scripts": source_root / "integrations" / "steam",
    }
    for label, path in shipped_paths.items():
        _assert_under(path, source_root), label


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_private_helpers_create_0700_directories_and_0600_files(tmp_path):
    state_root = tmp_path / "state"
    secret_path = state_root / "accounts" / "account.json"

    runtime_paths.atomic_write_private_text(secret_path, "secret")

    assert stat.S_IMODE(state_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600


def test_preexisting_directory_chmod_eperm_is_best_effort(
    tmp_path, monkeypatch, caplog,
):
    state_root = tmp_path / "bind-mounted-state"
    state_root.mkdir()
    monkeypatch.setattr(runtime_paths, "_posix_permissions", lambda: True)

    def deny_chmod(path, mode):
        raise PermissionError(errno.EPERM, "bind mount owned by another uid", path)

    monkeypatch.setattr(runtime_paths.os, "chmod", deny_chmod)

    assert runtime_paths.ensure_private_dir(state_root) == state_root
    assert state_root.is_dir()
    assert "Could not tighten directory permissions" in caplog.text


def test_timing_dna_configuration_is_lazy(tmp_path, monkeypatch):
    from career_bot import delay

    state_root = tmp_path / "state"
    for name in ("_timing_dna_path", "_dna_seed", "_default_dna"):
        monkeypatch.setattr(delay, name, getattr(delay, name))
    monkeypatch.setattr(delay.TimingDNA, "_registry", {})
    delay.configure_timing_dna(state_root)

    assert not state_root.exists()
    assert not (state_root / ".timing_dna").exists()


def test_timing_dna_imports_legacy_seed_once(tmp_path, monkeypatch, caplog):
    from career_bot import delay

    caplog.set_level("INFO", logger=delay.__name__)
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    legacy_path = source_root / "career_bot" / ".timing_dna"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text("7654321\n", encoding="utf-8")
    for name in (
        "_timing_dna_path",
        "_legacy_timing_dna_path",
        "_dna_seed",
        "_default_dna",
    ):
        monkeypatch.setattr(delay, name, getattr(delay, name))
    monkeypatch.setattr(delay.TimingDNA, "_registry", {})

    delay.configure_timing_dna(state_root, source_root)
    assert delay._installation_seed() == 7654321

    assert (state_root / ".timing_dna").read_text(encoding="utf-8") == "7654321"
    assert legacy_path.read_text(encoding="utf-8") == "7654321\n"
    assert "Imported legacy timing DNA seed" in caplog.text

    legacy_path.write_text("1234567\n", encoding="utf-8")
    monkeypatch.setattr(delay, "_dna_seed", None)
    assert delay._installation_seed() == 7654321
