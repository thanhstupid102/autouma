import pytest

from backend.app.domain import account_store, jsonstore
from uma_api import account_io, identity


FINGERPRINT = {
    "device_id": "registered-device-id",
    "device_name": "registered-device-name",
    "graphics_device_name": "registered-gpu",
    "ip_address": "10.20.30.40",
    "platform_os_version": "Windows 11 registered",
}

FORBIDDEN = {"steam_password_seed", "password", "steam_session_ticket"}


@pytest.fixture
def captured_account_writes(monkeypatch):
    writes = []

    def capture(path, payload, state_root):
        writes.append((path, dict(payload)))

    monkeypatch.setattr(jsonstore.secret_store, "save_json", capture)
    return writes


def test_explicit_fingerprint_permits_seed_removal_without_hardware_probe(
        tmp_account_store, captured_account_writes, monkeypatch):
    monkeypatch.setattr(
        identity, "get_hwid",
        lambda _seed: pytest.fail("explicit fingerprint must not probe hardware"),
    )
    cfg = {
        **FINGERPRINT,
        "auth_key": "auth",
        "steam_password_seed": "old-password",
        "password": "typed-password",
        "steam_session_ticket": "short-lived",
    }

    assert tmp_account_store.save_account_config("alice", cfg) is True

    saved = captured_account_writes[-1][1]
    assert all(saved[key] == value for key, value in FINGERPRINT.items())
    assert FORBIDDEN.isdisjoint(saved)


def test_legacy_body_materializes_fingerprint_before_seed_removal(
        tmp_account_store, captured_account_writes, monkeypatch):
    monkeypatch.setattr(identity, "unpack_request", lambda body, udid: dict(FINGERPRINT))
    monkeypatch.setattr(
        identity, "get_hwid",
        lambda _seed: pytest.fail("complete captured fingerprint must not probe hardware"),
    )
    cfg = {
        "auth_key": "auth",
        "udid": "legacy-udid",
        "body": "legacy-captured-body",
        "steam_password_seed": "old-password",
    }

    assert tmp_account_store.save_account_config("legacy", cfg) is True

    saved = captured_account_writes[-1][1]
    assert all(saved[key] == value for key, value in FINGERPRINT.items())
    assert "steam_password_seed" not in saved


def test_old_seed_fallback_preserves_exact_pre_migration_device_id(
        tmp_account_store, captured_account_writes, monkeypatch):
    derived = {**FINGERPRINT, "device_id": "sha1-produced-by-the-old-password"}
    calls = []

    def fake_hwid(seed):
        calls.append(seed)
        return dict(derived)

    monkeypatch.setattr(identity, "get_hwid", fake_hwid)
    cfg = {"auth_key": "auth", "steam_password_seed": "old-password"}
    pre_migration = identity.resolve_device_identity(cfg, derived)

    assert tmp_account_store.save_account_config("seeded", cfg) is True

    saved = captured_account_writes[-1][1]
    assert calls == ["old-password"]
    assert saved["device_id"] == pre_migration["device_id"]
    assert saved["device_id"] == "sha1-produced-by-the-old-password"
    assert "steam_password_seed" not in saved


def test_failed_materialization_does_not_strip_seed_or_replace_existing_file(
        tmp_account_store, monkeypatch):
    path = tmp_account_store.account_store_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"steam_password_seed":"only-reproducible-seed"}'
    path.write_bytes(original)
    cfg = {"auth_key": "auth", "steam_password_seed": "only-reproducible-seed"}

    def fail_hwid(_seed):
        raise RuntimeError("hardware probe failed")

    monkeypatch.setattr(identity, "get_hwid", fail_hwid)
    monkeypatch.setattr(
        jsonstore.secret_store, "save_json",
        lambda *_args, **_kwargs: pytest.fail("failed materialization must not write"),
    )

    with pytest.raises(identity.FingerprintMaterializationError, match="hardware probe failed"):
        tmp_account_store.save_account_config("broken", cfg)

    assert path.read_bytes() == original
    assert cfg["steam_password_seed"] == "only-reproducible-seed"


def test_save_and_import_never_write_password_seed_or_session_ticket(
        tmp_account_store, monkeypatch, tmp_path):
    writes = []

    def capture(path, payload, state_root):
        writes.append((path, dict(payload)))

    monkeypatch.setattr(jsonstore.secret_store, "save_json", capture)
    monkeypatch.setattr(account_io.secret_store, "save_json", capture)
    cfg = {
        **FINGERPRINT,
        "auth_key": "auth",
        "steam_password_seed": "old-password",
        "password": "typed-password",
        "steam_session_ticket": "short-lived",
    }

    assert account_store.save_account_config("saved", cfg) is True
    account_io.write_account_files(
        str(tmp_path / "uma_runtime" / "accounts"),
        tmp_path / "uma_runtime",
        "imported",
        {"game": cfg, "steam": {"refresh_token": "token"}},
    )

    game_payloads = [payload for path, payload in writes if not str(path).endswith(".steam.json")]
    assert len(game_payloads) == 2
    assert all(FORBIDDEN.isdisjoint(payload) for payload in game_payloads)

