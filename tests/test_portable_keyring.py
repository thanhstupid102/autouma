import pytest

from scripts import portable_keyring
from uma_api import secret_store


TEST_PASSPHRASE = "portable-keyring-test-passphrase"
MOCK_DPAPI_PREFIX = b"portable-keyring-mock-dpapi:"


@pytest.fixture(autouse=True)
def isolated_keyring(monkeypatch, tmp_path):
    secret_store.clear_key_cache()
    for name in (
        "UMA_RUNTIME_DIR",
        "UMA_SECRET_BACKEND",
        "UMA_SECRET_PASSPHRASE",
        "UMA_SECRET_PASSPHRASE_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UMA_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(secret_store, "SCRYPT_N", 2 ** 10)
    monkeypatch.setattr(secret_store, "SCRYPT_R", 8)
    monkeypatch.setattr(secret_store, "SCRYPT_P", 1)
    monkeypatch.setattr(secret_store, "SCRYPT_DKLEN", 32)
    _mock_dpapi(monkeypatch)
    yield
    secret_store.clear_key_cache()


def _mock_dpapi(monkeypatch):
    monkeypatch.setattr(secret_store, "_dpapi_is_available", lambda: True)
    monkeypatch.setattr(
        secret_store,
        "_dpapi_protect",
        lambda payload: MOCK_DPAPI_PREFIX + payload,
    )

    def unprotect(payload):
        if not payload.startswith(MOCK_DPAPI_PREFIX):
            raise secret_store.SecretStoreUnavailableError("mock DPAPI unwrap failed")
        return payload[len(MOCK_DPAPI_PREFIX):]

    monkeypatch.setattr(secret_store, "_dpapi_unprotect", unprotect)


def _create_account(tmp_path, monkeypatch, backend):
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir()
    account_path = accounts_dir / "Main.json"
    payload = {
        "auth_key": f"{backend}-auth",
        "udid": "registered-device-identity",
        "device_id": "registered-device-id",
    }
    monkeypatch.setenv("UMA_SECRET_BACKEND", backend)
    if backend == "passphrase":
        monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(account_path, payload, tmp_path)
    keyring_path = tmp_path / ".keyring"
    master_key = secret_store.load_master_key(keyring_path)
    return account_path, payload, keyring_path, master_key


@pytest.mark.parametrize(
    "source_backend,target_backend",
    (("dpapi", "passphrase"), ("passphrase", "dpapi")),
)
def test_conversion_preserves_master_key_and_existing_account(
    tmp_path,
    monkeypatch,
    source_backend,
    target_backend,
):
    account_path, payload, keyring_path, master_key = _create_account(
        tmp_path,
        monkeypatch,
        source_backend,
    )
    original_keyring = keyring_path.read_bytes()
    original_account = account_path.read_bytes()
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    result = portable_keyring.main(["--to", target_backend, "--apply"])

    assert result == 0
    assert secret_store.keyring_backend(keyring_path) == target_backend
    secret_store.clear_key_cache()
    assert secret_store.load_master_key(keyring_path) == master_key
    assert secret_store.load_json(account_path, tmp_path) == payload
    assert account_path.read_bytes() == original_account
    backups = list(tmp_path.glob(".keyring.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_keyring


def test_legacy_headerless_dpapi_source_converts(tmp_path, monkeypatch):
    account_path, payload, keyring_path, master_key = _create_account(
        tmp_path,
        monkeypatch,
        "dpapi",
    )
    wrapped = keyring_path.read_bytes()
    header_length = len(secret_store.KEYRING_MAGIC) + 1
    keyring_path.write_bytes(wrapped[header_length:])
    original_legacy = keyring_path.read_bytes()
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.clear_key_cache()

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    assert result == 0
    assert secret_store.keyring_backend(keyring_path) == "passphrase"
    secret_store.clear_key_cache()
    assert secret_store.load_master_key(keyring_path) == master_key
    assert secret_store.load_json(account_path, tmp_path) == payload
    backups = list(tmp_path.glob(".keyring.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_legacy


def test_verification_failure_leaves_live_keyring_unchanged(
    tmp_path,
    monkeypatch,
):
    _account_path, _payload, keyring_path, _master_key = _create_account(
        tmp_path,
        monkeypatch,
        "dpapi",
    )
    original = keyring_path.read_bytes()
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    def fail_verification(*_args):
        raise RuntimeError("injected verification failure")

    monkeypatch.setattr(portable_keyring, "_verify_candidate", fail_verification)

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    assert result == portable_keyring.EXIT_VERIFICATION
    assert keyring_path.read_bytes() == original
    assert not list(tmp_path.glob(".keyring.backup-*"))


def test_missing_target_passphrase_is_actionable_and_writes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
):
    account_path, _payload, keyring_path, _master_key = _create_account(
        tmp_path,
        monkeypatch,
        "dpapi",
    )
    original_keyring = keyring_path.read_bytes()
    original_account = account_path.read_bytes()
    monkeypatch.delenv("UMA_SECRET_PASSPHRASE", raising=False)

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    captured = capsys.readouterr()
    assert result == portable_keyring.EXIT_BACKEND
    assert captured.err == (
        "Error: Target backend 'passphrase' requires a passphrase; set "
        "UMA_SECRET_PASSPHRASE or UMA_SECRET_PASSPHRASE_FILE before running "
        "the conversion.\n"
    )
    assert keyring_path.read_bytes() == original_keyring
    assert account_path.read_bytes() == original_account
    assert not list(tmp_path.glob(".keyring.backup-*"))


def test_default_dry_run_reports_and_modifies_nothing(
    tmp_path,
    monkeypatch,
    capsys,
):
    _account_path, _payload, keyring_path, _master_key = _create_account(
        tmp_path,
        monkeypatch,
        "dpapi",
    )
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    original = keyring_path.read_bytes()
    original_mtime = keyring_path.stat().st_mtime_ns

    result = portable_keyring.main(["--to", "passphrase"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == (
        f"State root: {tmp_path.resolve()}\n"
        f"Keyring path: {keyring_path.resolve()}\n"
        "Current backend: dpapi\n"
        "Encrypted files protected: 1\n"
        "Conversion: dpapi -> passphrase\n"
        "Action: re-wrap the existing master key, back up the original, and "
        "atomically replace only the keyring\n"
        "Mode: dry-run (no files will be modified)\n"
        "Verification: re-read the staged keyring and decrypt one existing "
        "account file\n"
        "Run again with --apply to convert in place.\n"
    )
    assert keyring_path.read_bytes() == original
    assert keyring_path.stat().st_mtime_ns == original_mtime
    assert not list(tmp_path.glob(".keyring.backup-*"))


@pytest.mark.parametrize("verification_fails", (False, True))
def test_output_and_logs_never_include_passphrase_or_master_key(
    tmp_path,
    monkeypatch,
    capsys,
    caplog,
    verification_fails,
):
    passphrase_marker = "PASSPHRASE_OUTPUT_MARKER_874123"
    master_key_marker = b"MASTER_KEY_OUTPUT_MARKER_1234567"
    assert len(master_key_marker) == 32
    original_urandom = secret_store.os.urandom

    def marked_master_key(length):
        if length == 32:
            return master_key_marker
        return original_urandom(length)

    monkeypatch.setattr(secret_store.os, "urandom", marked_master_key)
    _create_account(tmp_path, monkeypatch, "dpapi")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", passphrase_marker)
    if verification_fails:
        def fail_verification(*_args):
            raise RuntimeError(
                f"{passphrase_marker} {master_key_marker.decode('ascii')}",
            )

        monkeypatch.setattr(portable_keyring, "_verify_candidate", fail_verification)

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err + caplog.text
    assert result == (
        portable_keyring.EXIT_VERIFICATION if verification_fails else 0
    )
    assert passphrase_marker not in combined
    assert master_key_marker.decode("ascii") not in combined


def test_missing_keyring_fails_without_creating_one(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    keyring_path = tmp_path / ".keyring"

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    captured = capsys.readouterr()
    assert result == portable_keyring.EXIT_KEYRING
    assert "does not exist" in captured.err
    assert str(keyring_path.resolve()) in captured.err
    assert not keyring_path.exists()


def test_apply_requires_an_encrypted_account_file_for_verification(
    tmp_path,
    monkeypatch,
):
    account_path, _payload, keyring_path, _master_key = _create_account(
        tmp_path,
        monkeypatch,
        "dpapi",
    )
    account_path.unlink()
    original = keyring_path.read_bytes()
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    result = portable_keyring.main(["--to", "passphrase", "--apply"])

    assert result == portable_keyring.EXIT_VERIFICATION
    assert keyring_path.read_bytes() == original
    assert not list(tmp_path.glob(".keyring.backup-*"))
