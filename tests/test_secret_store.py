import ctypes
import json
import logging
import os
import stat

import pytest

from uma_api import secret_store


pytestmark = pytest.mark.no_default_secret_store_backend

TEST_PASSPHRASE = "portable-test-passphrase"
MOCK_DPAPI_PREFIX = b"mock-dpapi:"


@pytest.fixture(autouse=True)
def isolated_secret_store(monkeypatch, tmp_path):
    secret_store.clear_key_cache()
    production_scrypt_params = (
        secret_store.SCRYPT_N,
        secret_store.SCRYPT_R,
        secret_store.SCRYPT_P,
        secret_store.SCRYPT_DKLEN,
    )
    original_save_json = secret_store.save_json
    original_load_json = secret_store.load_json
    original_migrate_file = secret_store.migrate_file

    def save_json(path, payload, state_root=None):
        return original_save_json(path, payload, state_root or tmp_path)

    def load_json(path, state_root=None):
        return original_load_json(path, state_root or tmp_path)

    def migrate_file(path, state_root=None):
        return original_migrate_file(path, state_root or tmp_path)

    monkeypatch.setattr(secret_store, "save_json", save_json)
    monkeypatch.setattr(secret_store, "load_json", load_json)
    monkeypatch.setattr(secret_store, "migrate_file", migrate_file)
    for name in (
        "UMA_SECRET_BACKEND",
        "UMA_SECRET_PASSPHRASE",
        "UMA_SECRET_PASSPHRASE_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(secret_store, "SCRYPT_N", 2 ** 10)
    monkeypatch.setattr(secret_store, "SCRYPT_R", 8)
    monkeypatch.setattr(secret_store, "SCRYPT_P", 1)
    monkeypatch.setattr(secret_store, "SCRYPT_DKLEN", 32)
    yield production_scrypt_params
    secret_store.clear_key_cache()


def _mock_dpapi(monkeypatch):
    monkeypatch.setattr(secret_store, "_dpapi_is_available", lambda: True)
    monkeypatch.setattr(
        secret_store,
        "_dpapi_protect",
        lambda payload: MOCK_DPAPI_PREFIX + payload,
    )
    monkeypatch.setattr(
        secret_store,
        "_dpapi_unprotect",
        lambda payload: payload.removeprefix(MOCK_DPAPI_PREFIX),
    )


def _protect_with_dpapi_description(payload: bytes, description: str) -> bytes:
    crypt32, kernel32 = secret_store._load_dpapi_libraries()
    input_blob, input_buffer = secret_store._input_blob(payload)
    output_blob = secret_store._DataBlob()
    result = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        description,
        None,
        None,
        None,
        secret_store._CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not result:
        raise secret_store._last_windows_error("CryptProtectData")
    return secret_store._returned_blob_bytes(output_blob, kernel32)


def _count_scrypt_derivations(monkeypatch):
    calls = []
    original = secret_store._derive_scrypt_key

    def counting_derive(passphrase, salt, *, n, r, p, dklen):
        calls.append((n, r, p, dklen))
        return original(
            passphrase,
            salt,
            n=n,
            r=r,
            p=p,
            dklen=dklen,
        )

    monkeypatch.setattr(secret_store, "_derive_scrypt_key", counting_derive)
    return calls


@pytest.fixture(params=("dpapi", "passphrase"))
def key_backend(request, monkeypatch):
    backend = request.param
    monkeypatch.setenv("UMA_SECRET_BACKEND", backend)
    if backend == "dpapi":
        _mock_dpapi(monkeypatch)
    else:
        monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    return backend


def test_real_dpapi_round_trip_when_available(tmp_path, monkeypatch):
    if not secret_store._dpapi_is_available():
        pytest.skip("Windows DPAPI is unavailable")
    path = tmp_path / "account.json"

    backend, passphrase = secret_store._creation_backend()
    assert backend == "dpapi"
    assert passphrase is None

    secret_store.save_json(path, {"auth_key": "real-dpapi"})
    assert secret_store.keyring_backend(tmp_path / ".keyring") == "dpapi"
    secret_store.clear_key_cache()

    assert secret_store.load_json(path) == {"auth_key": "real-dpapi"}


def test_real_dpapi_keyring_with_legacy_description_still_opens(tmp_path):
    if not secret_store._dpapi_is_available():
        pytest.skip("Windows DPAPI is unavailable")
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    master_key = b"L" * secret_store._KEY_LEN
    payload = {"auth_key": "legacy-description"}
    wrapped = _protect_with_dpapi_description(
        master_key,
        "Mcqueen Uma auth master key",
    )
    keyring.write_bytes(
        secret_store.KEYRING_MAGIC
        + secret_store._KEYRING_BACKEND_DPAPI
        + wrapped
    )
    path.write_bytes(secret_store._encrypt(payload, master_key))

    assert secret_store.load_json(path) == payload


def test_round_trip_encrypts_every_field_name_and_value(
    tmp_path, key_backend,
):
    keyring = tmp_path / ".keyring"
    path = tmp_path / "account.json"
    payload = {
        "auth_key": "plain-auth-secret",
        "udid": "plain-device-identifier",
        "viewer_id": 123456,
    }

    secret_store.save_json(path, payload)

    blob = path.read_bytes()
    assert blob.startswith(secret_store.MAGIC)
    for plaintext in (
        b"auth_key",
        b"plain-auth-secret",
        b"udid",
        b"plain-device-identifier",
    ):
        assert plaintext not in blob
    assert keyring.read_bytes().startswith(secret_store.KEYRING_MAGIC)
    secret_store.clear_key_cache()
    assert secret_store.load_json(path) == payload


def test_legacy_plaintext_read_is_migrated_in_place(tmp_path, key_backend):
    path = tmp_path / "legacy.json"
    payload = {"refresh_token": "legacy-token", "steam_id": "7656119"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert secret_store.load_json(path) == payload

    migrated = path.read_bytes()
    assert migrated.startswith(secret_store.MAGIC)
    assert b"refresh_token" not in migrated
    assert b"legacy-token" not in migrated


def test_legacy_plaintext_read_survives_migration_failure_without_log_leak(
    tmp_path, monkeypatch, caplog,
):
    path = tmp_path / "legacy.json"
    payload = {"auth_key": "still-readable"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    passphrase_marker = "passphrase-must-not-be-logged"
    master_key_marker = b"master-key-must-not-be-logged!!!"

    original_urandom = secret_store.os.urandom

    def known_master_key(length):
        if length == secret_store._KEY_LEN:
            return master_key_marker
        return original_urandom(length)

    def fail_wrap(key, passphrase):
        assert key == master_key_marker
        assert passphrase == passphrase_marker.encode("utf-8")
        raise secret_store.SecretStoreUnavailableError(
            "Cannot derive a passphrase key with the configured parameters",
        )

    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", passphrase_marker)
    monkeypatch.setattr(secret_store.os, "urandom", known_master_key)
    monkeypatch.setattr(secret_store, "_wrap_passphrase_key", fail_wrap)
    caplog.set_level(logging.WARNING)

    assert secret_store.load_json(path) == payload
    assert path.read_text(encoding="utf-8") == json.dumps(payload)
    assert "migration" in caplog.text.lower()
    assert "configured parameters" in caplog.text
    assert passphrase_marker not in caplog.text
    assert master_key_marker.decode("ascii") not in caplog.text


def test_legacy_migration_warning_includes_actionable_failure_message(
    tmp_path, monkeypatch, caplog,
):
    path = tmp_path / "legacy.json"
    payload = {"auth_key": "still-readable"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    caplog.set_level(logging.WARNING)

    assert secret_store.load_json(path) == payload
    assert "UMA_SECRET_PASSPHRASE" in caplog.text
    assert "UMA_SECRET_PASSPHRASE_FILE" in caplog.text


def test_tmp_dir_write_never_reads_or_creates_repo_keyring(
    tmp_path, monkeypatch, key_backend,
):
    path = tmp_path / "account.json"
    original_read_bytes = secret_store.Path.read_bytes
    read_paths = []

    def guarded_read_bytes(candidate):
        resolved = candidate.resolve()
        read_paths.append(resolved)
        return original_read_bytes(candidate)

    monkeypatch.setattr(secret_store.Path, "read_bytes", guarded_read_bytes)

    secret_store.save_json(path, {"auth_key": "tmp-only"})

    assert (tmp_path / ".keyring").exists()
    assert all(candidate.is_relative_to(tmp_path) for candidate in read_paths)
    secret_store.clear_key_cache()
    assert secret_store.load_json(path) == {"auth_key": "tmp-only"}


def test_atomic_write_failure_leaves_original_file_untouched(
    tmp_path, monkeypatch, key_backend,
):
    path = tmp_path / "account.json"
    secret_store.save_json(path, {"auth_key": "original"})
    original = path.read_bytes()

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        secret_store.save_json(path, {"auth_key": "replacement"})

    assert path.read_bytes() == original


@pytest.mark.parametrize("blob", [
    b"UMAACCT1-not-an-at-rest-file",
    b"FOREIGN1-not-an-at-rest-file",
])
def test_foreign_magic_is_rejected(tmp_path, blob, key_backend):
    path = tmp_path / "foreign.json"
    path.write_bytes(blob)

    with pytest.raises(secret_store.InvalidSecretFileError):
        secret_store.load_json(path)


def test_key_wrap_failure_raises_without_writing_plaintext(
    tmp_path, monkeypatch, key_backend,
):
    path = tmp_path / "account.json"

    if key_backend == "dpapi":
        def fail_wrap(_payload):
            raise secret_store.SecretStoreUnavailableError("DPAPI call failed")

        monkeypatch.setattr(secret_store, "_dpapi_protect", fail_wrap)
        expected = "DPAPI call failed"
    else:
        def fail_wrap(_key, _passphrase):
            raise secret_store.SecretStoreKeyError("Passphrase wrap failed")

        monkeypatch.setattr(secret_store, "_wrap_passphrase_key", fail_wrap)
        expected = "Passphrase wrap failed"

    with pytest.raises(secret_store.SecretStoreError, match=expected):
        secret_store.save_json(path, {"password": "must-never-be-plaintext"})

    assert not path.exists()
    assert not (tmp_path / ".keyring").exists()


def test_wrong_passphrase_has_distinct_typed_error(tmp_path, monkeypatch, caplog):
    path = tmp_path / "account.json"
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(path, {"auth_key": "encrypted"})
    keyring_before = (tmp_path / ".keyring").read_bytes()
    secret_store.clear_key_cache()

    wrong_passphrase = "definitely-the-wrong-passphrase"
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", wrong_passphrase)
    with pytest.raises(secret_store.SecretStorePassphraseError) as caught:
        secret_store.load_json(path)

    message = str(caught.value).lower()
    assert "does not match" in message
    assert "corrupt" not in message
    assert TEST_PASSPHRASE not in str(caught.value)
    assert wrong_passphrase not in str(caught.value)
    assert TEST_PASSPHRASE not in caplog.text
    assert wrong_passphrase not in caplog.text
    assert (tmp_path / ".keyring").read_bytes() == keyring_before


@pytest.mark.parametrize("existing", (False, True))
def test_non_windows_without_passphrase_does_not_modify_destination(
    tmp_path, monkeypatch, existing,
):
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    original = b"existing-destination"
    if existing:
        path.write_bytes(original)
    monkeypatch.setattr(
        secret_store,
        "_keyring_path_for",
        lambda _path, _state_root: keyring,
    )
    monkeypatch.setattr(secret_store, "_is_windows", lambda: False)

    with pytest.raises(secret_store.SecretStoreUnavailableError) as caught:
        secret_store.save_json(path, {"password": "never-plaintext"})

    message = str(caught.value)
    assert "UMA_SECRET_PASSPHRASE" in message
    assert "UMA_SECRET_PASSPHRASE_FILE" in message
    assert "before saving" in message.lower()
    assert path.exists() is existing
    if existing:
        assert path.read_bytes() == original
    assert not keyring.exists()


def test_legacy_headerless_dpapi_keyring_is_read_on_any_platform(
    tmp_path, monkeypatch,
):
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    key = b"L" * 32
    legacy_blob = b"legacy-headerless-dpapi"
    payload = {"refresh_token": "portable-reader"}
    calls = []
    keyring.write_bytes(legacy_blob)
    path.write_bytes(secret_store._encrypt(payload, key))

    def unwrap(blob):
        calls.append(blob)
        return key

    monkeypatch.setattr(secret_store, "_dpapi_unprotect", unwrap)

    assert secret_store.load_json(path) == payload
    assert calls == [legacy_blob]


def test_passphrase_file_accepts_one_trailing_newline(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    passphrase_file = tmp_path / "credential"
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(path, {"auth_key": "file-source"})

    monkeypatch.delenv("UMA_SECRET_PASSPHRASE")
    passphrase_file.write_text(TEST_PASSPHRASE + "\n", encoding="utf-8")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE_FILE", str(passphrase_file))
    secret_store.clear_key_cache()

    assert secret_store.load_json(path) == {"auth_key": "file-source"}


@pytest.mark.parametrize("backend", ("dpapi", "passphrase"))
def test_backend_forcing_selects_requested_new_keyring(
    tmp_path, monkeypatch, backend,
):
    path = tmp_path / "account.json"
    monkeypatch.setenv("UMA_SECRET_BACKEND", backend)
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    _mock_dpapi(monkeypatch)

    secret_store.save_json(path, {"auth_key": backend})

    blob = (tmp_path / ".keyring").read_bytes()
    expected = {
        "dpapi": secret_store._KEYRING_BACKEND_DPAPI,
        "passphrase": secret_store._KEYRING_BACKEND_PASSPHRASE,
    }[backend]
    assert blob.startswith(secret_store.KEYRING_MAGIC + expected)
    secret_store.clear_key_cache()
    assert secret_store.load_json(path) == {"auth_key": backend}


@pytest.mark.parametrize("created_backend", ("dpapi", "passphrase"))
def test_existing_keyring_format_overrides_forced_backend_on_read(
    tmp_path, monkeypatch, created_backend,
):
    path = tmp_path / "account.json"
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    monkeypatch.setenv("UMA_SECRET_BACKEND", created_backend)
    _mock_dpapi(monkeypatch)
    secret_store.save_json(path, {"auth_key": created_backend})
    keyring_before = (tmp_path / ".keyring").read_bytes()

    forced_backend = {
        "dpapi": "passphrase",
        "passphrase": "dpapi",
    }[created_backend]
    monkeypatch.setenv("UMA_SECRET_BACKEND", forced_backend)
    secret_store.clear_key_cache()

    assert secret_store.load_json(path) == {"auth_key": created_backend}
    assert (tmp_path / ".keyring").read_bytes() == keyring_before


@pytest.mark.parametrize("has_passphrase, expected", (
    (True, "passphrase"),
    (False, "dpapi"),
))
def test_unforced_windows_creation_prefers_available_passphrase(
    monkeypatch, has_passphrase, expected,
):
    monkeypatch.setattr(secret_store, "_is_windows", lambda: True)
    monkeypatch.setattr(secret_store, "_dpapi_is_available", lambda: True)
    if has_passphrase:
        monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    backend, _passphrase = secret_store._creation_backend()

    assert backend == expected


def test_unknown_backend_is_typed_and_names_valid_values(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    monkeypatch.setenv("UMA_SECRET_BACKEND", "unknown")

    with pytest.raises(secret_store.SecretStoreUnavailableError) as caught:
        secret_store.save_json(path, {"auth_key": "never-written"})

    message = str(caught.value)
    assert "dpapi" in message
    assert "passphrase" in message
    assert not path.exists()
    assert not (tmp_path / ".keyring").exists()


def test_repeated_loads_derive_passphrase_key_once(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    payload = {"auth_key": "cached"}
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(path, payload)
    secret_store.clear_key_cache()
    calls = _count_scrypt_derivations(monkeypatch)

    assert secret_store.load_json(path) == payload
    assert secret_store.load_json(path) == payload
    assert len(calls) == 1


def test_first_keyring_race_adopts_the_persisted_winner(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    persisted_key = b"p" * secret_store._KEY_LEN
    passphrase = TEST_PASSPHRASE.encode("utf-8")
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    persisted_wrapped = secret_store._wrap_passphrase_key(
        persisted_key, passphrase,
    )

    def concurrent_winner(_path, _payload):
        keyring.write_bytes(persisted_wrapped)

    monkeypatch.setattr(secret_store, "_atomic_write", concurrent_winner)

    assert secret_store._master_key(path, tmp_path, create=True) == persisted_key


def test_rewritten_keyring_causes_passphrase_rederivation(
    tmp_path, monkeypatch,
):
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    payload = {"auth_key": "rotated-wrapper"}
    passphrase = TEST_PASSPHRASE.encode("utf-8")
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(path, payload)
    master_key = secret_store._master_key(path, tmp_path, create=False)
    original_blob = keyring.read_bytes()
    replacement_blob = secret_store._wrap_passphrase_key(
        master_key,
        passphrase,
    )
    assert replacement_blob != original_blob

    secret_store.clear_key_cache()
    calls = _count_scrypt_derivations(monkeypatch)
    assert secret_store.load_json(path) == payload
    assert len(calls) == 1

    before = keyring.stat()
    secret_store._atomic_write(keyring, replacement_blob)
    rewritten = keyring.stat()
    newer_mtime = max(before.st_mtime_ns, rewritten.st_mtime_ns) + 1_000_000_000
    os.utime(keyring, ns=(rewritten.st_atime_ns, newer_mtime))
    after = keyring.stat()
    assert secret_store._keyring_identity(after) != (
        secret_store._keyring_identity(before)
    )

    assert secret_store.load_json(path) == payload
    assert len(calls) == 2


def test_changed_passphrase_misses_cache_and_raises(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    payload = {"auth_key": "passphrase-sensitive-cache"}
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    secret_store.save_json(path, payload)
    secret_store.clear_key_cache()
    calls = _count_scrypt_derivations(monkeypatch)

    assert secret_store.load_json(path) == payload
    assert len(calls) == 1

    monkeypatch.setenv(
        "UMA_SECRET_PASSPHRASE",
        "definitely-the-wrong-passphrase",
    )
    with pytest.raises(secret_store.SecretStorePassphraseError):
        secret_store.load_json(path)
    assert len(calls) == 2


def test_stored_scrypt_parameters_survive_default_changes(
    tmp_path, monkeypatch, isolated_secret_store,
):
    path = tmp_path / "account.json"
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    written_params = isolated_secret_store
    assert written_params == (2 ** 16, 8, 1, 32)
    for name, value in zip(
        ("SCRYPT_N", "SCRYPT_R", "SCRYPT_P", "SCRYPT_DKLEN"),
        written_params,
    ):
        monkeypatch.setattr(secret_store, name, value)
    secret_store.save_json(path, {"auth_key": "durable-parameters"})

    monkeypatch.setattr(secret_store, "SCRYPT_N", 2 ** 9)
    monkeypatch.setattr(secret_store, "SCRYPT_R", 4)
    monkeypatch.setattr(secret_store, "SCRYPT_P", 2)
    monkeypatch.setattr(secret_store, "SCRYPT_DKLEN", 16)
    secret_store.clear_key_cache()
    calls = _count_scrypt_derivations(monkeypatch)

    assert secret_store.load_json(path) == {"auth_key": "durable-parameters"}
    assert calls == [written_params]

    keyring = (tmp_path / ".keyring").read_bytes()
    offset = len(secret_store.KEYRING_MAGIC) + 2
    stored_params = secret_store._SCRYPT_PARAMS.unpack(
        keyring[offset:offset + secret_store._SCRYPT_PARAMS.size],
    )
    assert stored_params == written_params


def test_posix_writes_use_owner_only_modes(tmp_path, monkeypatch):
    secret_dir = tmp_path / "secrets"
    path = secret_dir / "account.json"
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    secret_store.save_json(path, {"auth_key": "mode-test"})
    secret_store.clear_key_cache()
    assert secret_store.load_json(path) == {"auth_key": "mode-test"}

    if os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / ".keyring").stat().st_mode) == 0o600


def test_windows_legacy_dpapi_read_ignores_configured_passphrase(
    tmp_path, monkeypatch,
):
    path = tmp_path / "account.json"
    keyring = tmp_path / ".keyring"
    key = b"D" * 32
    legacy_blob = b"existing-windows-dpapi-keyring"
    payload = {"auth_key": "legacy-windows"}
    keyring.write_bytes(legacy_blob)
    path.write_bytes(secret_store._encrypt(payload, key))
    before = keyring.read_bytes()
    calls = []
    monkeypatch.setattr(
        secret_store,
        "_keyring_path_for",
        lambda _path, _state_root: keyring,
    )
    monkeypatch.setattr(secret_store, "_is_windows", lambda: True)
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    def unwrap(blob):
        calls.append(blob)
        return key

    monkeypatch.setattr(secret_store, "_dpapi_unprotect", unwrap)

    assert secret_store.load_json(path) == payload
    assert calls == [legacy_blob]
    assert keyring.read_bytes() == before


@pytest.mark.parametrize("blob", (
    secret_store.KEYRING_MAGIC,
    secret_store.KEYRING_MAGIC + secret_store._KEYRING_BACKEND_PASSPHRASE,
    b"UMAKEY2\x02",
))
def test_truncated_or_unparseable_keyring_has_distinct_error(
    tmp_path, monkeypatch, blob,
):
    path = tmp_path / "account.json"
    (tmp_path / ".keyring").write_bytes(blob)
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)

    with pytest.raises(secret_store.SecretStoreKeyError) as caught:
            secret_store._master_key(path, tmp_path, create=False)

    message = str(caught.value).lower()
    assert "truncated or unparseable" in message
    assert "does not match" not in message


def test_is_available_is_backend_aware(monkeypatch, tmp_path):
    monkeypatch.setattr(secret_store, "_is_windows", lambda: False)
    assert secret_store.is_available() is False

    monkeypatch.setenv("UMA_SECRET_PASSPHRASE", TEST_PASSPHRASE)
    assert secret_store.is_available() is True

    monkeypatch.setenv("UMA_SECRET_BACKEND", "dpapi")
    assert secret_store.is_available() is False

    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    assert secret_store.is_available() is True


def test_whitespace_only_passphrase_file_is_absent(tmp_path, monkeypatch):
    path = tmp_path / "account.json"
    passphrase_file = tmp_path / "credential"
    passphrase_file.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("UMA_SECRET_BACKEND", "passphrase")
    monkeypatch.setenv("UMA_SECRET_PASSPHRASE_FILE", str(passphrase_file))

    with pytest.raises(secret_store.SecretStoreUnavailableError) as caught:
        secret_store.save_json(path, {"auth_key": "never-written"})

    assert "requires a passphrase" in str(caught.value)
    assert not path.exists()
