"""Encrypted JSON storage for persistent account authentication data.

Files are encrypted with AES-256-GCM under a random 32-byte master key. The
master key is wrapped either with user-scoped Windows DPAPI or with a
passphrase-derived scrypt key. ``save_json`` never falls back to plaintext:
key-wrap failures raise a typed ``SecretStoreError`` and filesystem failures
propagate without leaving plaintext at the destination.

DPAPI's protection is user-scoped, not process-scoped. Passphrase protection
depends on the passphrase remaining out of band from the encrypted files.
Neither backend protects against malware running as the same OS user.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import struct
import threading
from typing import Any, cast

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

from core.runtime_paths import atomic_write_private_bytes


MAGIC = b"UMAENC1"
KEYRING_MAGIC = b"UMAKEY1"
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
_SALT_LEN = 16
_NONCE_LEN = 12
_TAG_LEN = 16
_KEY_LEN = 32
_MIN_BLOB_LEN = len(MAGIC) + _SALT_LEN + _NONCE_LEN + _TAG_LEN
_KEYRING_MAGIC_PREFIX = b"UMAKEY"
_KEYRING_BACKEND_DPAPI = b"\x01"
_KEYRING_BACKEND_PASSPHRASE = b"\x02"
_KDF_SCRYPT = b"\x01"
_KDF_SALT_LEN = 16
_SCRYPT_PARAMS = struct.Struct(">QIII")
_PASSPHRASE_KEYRING_LEN = (
    len(KEYRING_MAGIC) + 1 + 1 + _SCRYPT_PARAMS.size
    + _KDF_SALT_LEN + _NONCE_LEN + _TAG_LEN + _KEY_LEN
)
_VALID_BACKENDS = ("dpapi", "passphrase")
_PASSPHRASE_ENV = "UMA_SECRET_PASSPHRASE"
_PASSPHRASE_FILE_ENV = "UMA_SECRET_PASSPHRASE_FILE"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_KEYRING_LOCK = threading.Lock()
_KeyringIdentity = tuple[int, int, int | None]
_KeyCacheKey = tuple[Path, int, int, int | None, bytes]
_KEY_CACHE: dict[_KeyCacheKey, bytes] = {}


log = logging.getLogger(__name__)


class SecretStoreError(RuntimeError):
    """Base class for typed secret-store failures."""


class SecretStoreUnavailableError(SecretStoreError):
    """No configured key-wrap backend is available or an operation failed."""


class SecretStoreKeyError(SecretStoreError):
    """The master-key file is missing or invalid."""


class SecretStorePassphraseError(SecretStoreKeyError):
    """The configured passphrase does not unlock the existing keyring."""


class InvalidSecretFileError(SecretStoreError):
    """The payload is neither legacy plaintext JSON nor a valid at-rest file."""


class SecretStoreDecryptionError(SecretStoreError):
    """The encrypted payload cannot be authenticated or decrypted."""


class SecretStorePathError(SecretStoreError):
    """The encrypted payload path is outside its declared state root."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _is_windows() -> bool:
    """Whether this host is Windows, i.e. whether DPAPI can exist at all.

    Routed through one helper so a test can simulate a non-Windows host by
    patching this function. Patching ``os.name`` instead would also change what
    ``pathlib.Path()`` constructs, which on Python <= 3.12 makes ``Path`` raise
    ``NotImplementedError`` for the foreign flavour.
    """
    return os.name == "nt"


def _load_dpapi_libraries() -> tuple[Any, Any]:
    if not _is_windows():
        raise SecretStoreUnavailableError("Windows DPAPI is unavailable on this platform")
    try:
        win_dll = getattr(ctypes, "WinDLL")
        crypt32 = win_dll("crypt32", use_last_error=True)
        kernel32 = win_dll("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise SecretStoreUnavailableError(f"Windows DPAPI is unavailable: {exc}") from exc

    blob_ptr = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [
        blob_ptr, wintypes.LPCWSTR, blob_ptr, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_ptr,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_ptr, ctypes.c_void_p, blob_ptr, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_ptr,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _dpapi_is_available() -> bool:
    if not _is_windows():
        return False
    try:
        _load_dpapi_libraries()
    except SecretStoreUnavailableError:
        return False
    return True


def _forced_backend() -> str | None:
    value = os.environ.get("UMA_SECRET_BACKEND", "").strip().lower()
    if not value:
        return None
    if value not in _VALID_BACKENDS:
        valid = ", ".join(_VALID_BACKENDS)
        raise SecretStoreUnavailableError(
            f"Invalid UMA_SECRET_BACKEND value; valid values are: {valid}",
        )
    return value


def _strip_one_trailing_newline(value: str) -> str:
    if value.endswith("\r\n"):
        return value[:-2]
    if value.endswith(("\n", "\r")):
        return value[:-1]
    return value


def _encode_passphrase(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise SecretStoreUnavailableError(
            "The configured secret-store passphrase must be valid UTF-8 text",
        ) from exc


def _passphrase() -> bytes | None:
    direct = os.environ.get(_PASSPHRASE_ENV)
    if direct is not None and direct.strip():
        return _encode_passphrase(direct)

    file_name = os.environ.get(_PASSPHRASE_FILE_ENV)
    if file_name is None or not file_name.strip():
        return None
    try:
        value = Path(file_name).read_text(encoding="utf-8")
    except OSError as exc:
        raise SecretStoreUnavailableError(
            f"Cannot read {_PASSPHRASE_FILE_ENV}: {exc}",
        ) from exc
    except UnicodeError as exc:
        raise SecretStoreUnavailableError(
            f"{_PASSPHRASE_FILE_ENV} must contain valid UTF-8 text",
        ) from exc
    value = _strip_one_trailing_newline(value)
    if not value.strip():
        return None
    return _encode_passphrase(value)


def is_available() -> bool:
    """Return whether some configured key-wrap backend is usable here."""
    forced = _forced_backend()
    try:
        has_passphrase = _passphrase() is not None
    except SecretStoreUnavailableError:
        has_passphrase = False
    if forced == "passphrase":
        return has_passphrase
    if forced == "dpapi":
        return _dpapi_is_available()
    return has_passphrase or _dpapi_is_available()


def _input_blob(payload: bytes) -> tuple[_DataBlob, Any]:
    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    blob = _DataBlob(
        len(payload),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _last_windows_error(operation: str) -> SecretStoreUnavailableError:
    get_last_error = getattr(ctypes, "get_last_error")
    code = int(get_last_error())
    detail = ctypes.FormatError(code).strip() if code else "unknown Windows error"
    return SecretStoreUnavailableError(f"{operation} failed: {detail} (error {code})")


def _returned_blob_bytes(blob: _DataBlob, kernel32: Any) -> bytes:
    pointer = ctypes.cast(blob.pbData, ctypes.c_void_p)
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if pointer.value:
            kernel32.LocalFree(pointer)


def _dpapi_protect(payload: bytes) -> bytes:
    crypt32, kernel32 = _load_dpapi_libraries()
    input_blob, input_buffer = _input_blob(payload)
    output_blob = _DataBlob()
    result = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        # szDataDescr is cosmetic metadata and is not needed to unwrap the blob.
        "ManhattanCafe Uma auth master key",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not result:
        raise _last_windows_error("CryptProtectData")
    return _returned_blob_bytes(output_blob, kernel32)


def _dpapi_unprotect(payload: bytes) -> bytes:
    crypt32, kernel32 = _load_dpapi_libraries()
    input_blob, input_buffer = _input_blob(payload)
    output_blob = _DataBlob()
    result = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not result:
        raise _last_windows_error("CryptUnprotectData")
    return _returned_blob_bytes(output_blob, kernel32)


def _keyring_path_for(path: Path, state_root: Path) -> Path:
    resolved_path = Path(path).resolve()
    resolved_root = Path(state_root).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SecretStorePathError(
            f"Secret payload path is outside state root: {resolved_path}",
        ) from exc
    return resolved_root / ".keyring"


def _atomic_write(path: Path, payload: bytes) -> None:
    atomic_write_private_bytes(path, payload)


def clear_key_cache() -> None:
    """Clear cached master keys after keyring rotation or in test isolation."""
    with _KEYRING_LOCK:
        _KEY_CACHE.clear()


def _keyring_identity(stat_result: os.stat_result) -> _KeyringIdentity:
    inode = stat_result.st_ino or None
    return stat_result.st_mtime_ns, stat_result.st_size, inode


def _read_keyring_snapshot(
    keyring_path: Path,
) -> tuple[bytes, _KeyringIdentity]:
    for _attempt in range(3):
        try:
            before = _keyring_identity(os.stat(keyring_path))
            wrapped = keyring_path.read_bytes()
            after = _keyring_identity(os.stat(keyring_path))
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SecretStoreKeyError(
                f"Cannot read secret-store keyring: {exc}",
            ) from exc
        if before == after:
            return wrapped, after
    raise SecretStoreKeyError(
        f"Secret-store keyring changed while being read: {keyring_path}",
    )


def _key_cache_key(
    keyring_path: Path,
    identity: _KeyringIdentity,
    passphrase: bytes | None,
) -> _KeyCacheKey:
    material = b"\x00" if passphrase is None else b"\x01" + passphrase
    passphrase_digest = sha256(material).digest()
    mtime_ns, size, inode = identity
    return keyring_path.resolve(), mtime_ns, size, inode, passphrase_digest


def _remember_master_key(cache_key: _KeyCacheKey, key: bytes) -> None:
    keyring_path = cache_key[0]
    for existing_key in tuple(_KEY_CACHE):
        if existing_key[0] == keyring_path and existing_key != cache_key:
            del _KEY_CACHE[existing_key]
    _KEY_CACHE[cache_key] = key


def _keyring_parse_error(keyring_path: Path) -> SecretStoreKeyError:
    return SecretStoreKeyError(
        f"Secret-store keyring is truncated or unparseable: {keyring_path}",
    )


def _keyring_backend_from_blob(blob: bytes, keyring_path: Path) -> str:
    if not blob:
        raise _keyring_parse_error(keyring_path)
    if blob.startswith(_KEYRING_MAGIC_PREFIX) and not blob.startswith(KEYRING_MAGIC):
        raise _keyring_parse_error(keyring_path)
    if not blob.startswith(KEYRING_MAGIC):
        return "dpapi"
    if len(blob) <= len(KEYRING_MAGIC):
        raise _keyring_parse_error(keyring_path)

    backend = blob[len(KEYRING_MAGIC):len(KEYRING_MAGIC) + 1]
    body = blob[len(KEYRING_MAGIC) + 1:]
    if backend == _KEYRING_BACKEND_DPAPI:
        if not body:
            raise _keyring_parse_error(keyring_path)
        return "dpapi"
    if backend == _KEYRING_BACKEND_PASSPHRASE:
        _stored_scrypt_parameters(blob, keyring_path)
        return "passphrase"
    raise _keyring_parse_error(keyring_path)


def keyring_backend(keyring_path: Path) -> str:
    """Return the backend encoded by an existing keyring without unwrapping it."""
    path = Path(keyring_path).resolve()
    try:
        wrapped, _identity = _read_keyring_snapshot(path)
    except FileNotFoundError as exc:
        raise SecretStoreKeyError(f"Secret-store keyring is missing: {path}") from exc
    return _keyring_backend_from_blob(wrapped, path)


def _validated_master_key(key: bytes, backend: str) -> bytes:
    if len(key) != _KEY_LEN:
        raise SecretStoreKeyError(
            f"{backend} keyring did not contain a 32-byte master key",
        )
    return key


def _derive_scrypt_key(
    passphrase: bytes,
    salt: bytes,
    *,
    n: int,
    r: int,
    p: int,
    dklen: int,
) -> bytes:
    return cast(
        bytes,
        scrypt(
            cast(str, passphrase), cast(str, salt), dklen,
            N=n, r=r, p=p,
        ),
    )


def _wrap_passphrase_key(key: bytes, passphrase: bytes) -> bytes:
    salt = os.urandom(_KDF_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    params = _SCRYPT_PARAMS.pack(SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    header = (
        KEYRING_MAGIC + _KEYRING_BACKEND_PASSPHRASE + _KDF_SCRYPT
        + params + salt + nonce
    )
    try:
        kek = _derive_scrypt_key(
            passphrase,
            salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_DKLEN,
        )
    except (TypeError, ValueError) as exc:
        raise SecretStoreUnavailableError(
            "Cannot derive a passphrase key with the configured scrypt parameters",
        ) from exc
    cipher = AES.new(kek, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_LEN)
    cipher.update(header)
    wrapped_key, tag = cipher.encrypt_and_digest(key)
    return header + tag + wrapped_key


def _stored_scrypt_parameters(
    blob: bytes,
    keyring_path: Path,
) -> tuple[int, int, int, int]:
    if len(blob) != _PASSPHRASE_KEYRING_LEN:
        raise _keyring_parse_error(keyring_path)

    offset = len(KEYRING_MAGIC) + 1
    kdf = blob[offset:offset + 1]
    offset += 1
    if kdf != _KDF_SCRYPT:
        raise _keyring_parse_error(keyring_path)

    params_end = offset + _SCRYPT_PARAMS.size
    try:
        n, r, p, dklen = _SCRYPT_PARAMS.unpack(blob[offset:params_end])
    except struct.error as exc:
        raise _keyring_parse_error(keyring_path) from exc
    if n < 2 or n & (n - 1) or r < 1 or p < 1 or dklen not in (16, 24, 32):
        raise _keyring_parse_error(keyring_path)
    return n, r, p, dklen


def _effective_passphrase_for_keyring(
    blob: bytes,
    keyring_path: Path,
) -> bytes | None:
    if not blob.startswith(KEYRING_MAGIC):
        return None
    backend = blob[len(KEYRING_MAGIC):len(KEYRING_MAGIC) + 1]
    if backend != _KEYRING_BACKEND_PASSPHRASE:
        return None
    _stored_scrypt_parameters(blob, keyring_path)
    return _passphrase()


def _unwrap_passphrase_key(
    blob: bytes,
    keyring_path: Path,
    passphrase: bytes | None,
) -> bytes:
    n, r, p, dklen = _stored_scrypt_parameters(blob, keyring_path)
    offset = len(KEYRING_MAGIC) + 1 + 1 + _SCRYPT_PARAMS.size
    salt = blob[offset:offset + _KDF_SALT_LEN]
    offset += _KDF_SALT_LEN
    nonce = blob[offset:offset + _NONCE_LEN]
    offset += _NONCE_LEN
    header = blob[:offset]
    tag = blob[offset:offset + _TAG_LEN]
    offset += _TAG_LEN
    wrapped_key = blob[offset:]

    if passphrase is None:
        raise SecretStoreUnavailableError(
            "No secret-store passphrase is configured; set "
            f"{_PASSPHRASE_ENV} or {_PASSPHRASE_FILE_ENV} to the passphrase "
            "used to create the existing keyring.",
        )
    try:
        kek = _derive_scrypt_key(
            passphrase, salt, n=n, r=r, p=p, dklen=dklen,
        )
    except (TypeError, ValueError) as exc:
        raise _keyring_parse_error(keyring_path) from exc
    cipher = AES.new(kek, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_LEN)
    cipher.update(header)
    try:
        key = cipher.decrypt_and_verify(wrapped_key, tag)
    except ValueError as exc:
        raise SecretStorePassphraseError(
            "Configured passphrase does not match the existing keyring; set "
            f"{_PASSPHRASE_ENV} or {_PASSPHRASE_FILE_ENV} to the passphrase "
            "used when the keyring was created.",
        ) from exc
    return _validated_master_key(key, "Passphrase")


def _unwrap_existing_keyring(
    blob: bytes,
    keyring_path: Path,
    passphrase: bytes | None,
) -> bytes:
    backend = _keyring_backend_from_blob(blob, keyring_path)
    if not blob.startswith(KEYRING_MAGIC):
        return _validated_master_key(_dpapi_unprotect(blob), "Legacy DPAPI")

    body = blob[len(KEYRING_MAGIC) + 1:]
    if backend == "dpapi":
        return _validated_master_key(_dpapi_unprotect(body), "DPAPI")
    if backend == "passphrase":
        return _unwrap_passphrase_key(blob, keyring_path, passphrase)
    raise _keyring_parse_error(keyring_path)


def _target_backend_material(backend: str) -> bytes | None:
    if backend not in _VALID_BACKENDS:
        valid = ", ".join(_VALID_BACKENDS)
        raise SecretStoreUnavailableError(
            f"Invalid target backend {backend!r}; valid values are: {valid}",
        )
    if backend == "passphrase":
        passphrase = _passphrase()
        if passphrase is None:
            raise SecretStoreUnavailableError(
                "Target backend 'passphrase' requires a passphrase; set "
                f"{_PASSPHRASE_ENV} or {_PASSPHRASE_FILE_ENV} before running "
                "the conversion.",
            )
        return passphrase
    if not _dpapi_is_available():
        raise SecretStoreUnavailableError(
            "Target backend 'dpapi' requires Windows DPAPI, but it is unavailable.",
        )
    return None


def validate_keyring_backend(backend: str) -> None:
    """Validate that an explicit key-wrap backend is usable on this host."""
    _target_backend_material(backend)


def wrap_master_key(key: bytes, backend: str) -> bytes:
    """Wrap one existing 32-byte master key for an explicit backend."""
    key = _validated_master_key(key, "Secret-store")
    material = _target_backend_material(backend)
    if backend == "dpapi":
        return KEYRING_MAGIC + _KEYRING_BACKEND_DPAPI + _dpapi_protect(key)
    assert material is not None
    return _wrap_passphrase_key(key, material)


def _creation_backend() -> tuple[str, bytes | None]:
    forced = _forced_backend()
    if forced == "passphrase":
        passphrase = _passphrase()
        if passphrase is None:
            raise SecretStoreUnavailableError(
                "UMA_SECRET_BACKEND=passphrase requires a passphrase; set "
                f"{_PASSPHRASE_ENV} or {_PASSPHRASE_FILE_ENV} before saving.",
            )
        return forced, passphrase
    if forced == "dpapi":
        if not is_available():
            raise SecretStoreUnavailableError(
                "UMA_SECRET_BACKEND=dpapi requires Windows DPAPI, but it is unavailable.",
            )
        return forced, None

    passphrase = _passphrase()
    if passphrase is not None:
        return "passphrase", passphrase
    if _is_windows() and is_available():
        return "dpapi", None
    raise SecretStoreUnavailableError(
        "No portable secret-store backend is configured; set "
        f"{_PASSPHRASE_ENV} or {_PASSPHRASE_FILE_ENV} before saving encrypted "
        "account data on a non-Windows system.",
    )


def _load_master_key_locked(keyring_path: Path) -> bytes:
    wrapped, identity = _read_keyring_snapshot(keyring_path)
    passphrase = _effective_passphrase_for_keyring(wrapped, keyring_path)
    cache_key = _key_cache_key(keyring_path, identity, passphrase)
    cached_key = _KEY_CACHE.get(cache_key)
    if cached_key is not None:
        return cached_key
    key = _unwrap_existing_keyring(wrapped, keyring_path, passphrase)
    _remember_master_key(cache_key, key)
    return key


def load_master_key(keyring_path: Path) -> bytes:
    """Unwrap an existing keyring through the production backend dispatcher."""
    path = Path(keyring_path).resolve()
    with _KEYRING_LOCK:
        _forced_backend()
        try:
            return _load_master_key_locked(path)
        except FileNotFoundError as exc:
            raise SecretStoreKeyError(f"Secret-store keyring is missing: {path}") from exc


def _master_key(path: Path, state_root: Path, *, create: bool) -> bytes:
    keyring_path = _keyring_path_for(path, state_root).resolve()
    with _KEYRING_LOCK:
        _forced_backend()
        try:
            return _load_master_key_locked(keyring_path)
        except FileNotFoundError:
            pass

        if not create:
            raise SecretStoreKeyError(f"Secret-store keyring is missing: {keyring_path}")

        key = os.urandom(_KEY_LEN)
        backend, passphrase = _creation_backend()
        if backend == "dpapi":
            wrapped = (
                KEYRING_MAGIC + _KEYRING_BACKEND_DPAPI + _dpapi_protect(key)
            )
        else:
            assert passphrase is not None
            wrapped = _wrap_passphrase_key(key, passphrase)
        _atomic_write(keyring_path, wrapped)
        current_wrapped, identity = _read_keyring_snapshot(keyring_path)
        if current_wrapped != wrapped:
            passphrase = _effective_passphrase_for_keyring(
                current_wrapped, keyring_path,
            )
            key = _unwrap_existing_keyring(
                current_wrapped, keyring_path, passphrase,
            )
        cache_key = _key_cache_key(keyring_path, identity, passphrase)
        _remember_master_key(cache_key, key)
        return key


def _decode_json(raw: bytes, source: Path) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidSecretFileError(f"Invalid JSON in {source}") from exc
    if not isinstance(payload, dict):
        raise InvalidSecretFileError(f"Expected a JSON object in {source}")
    return payload


def _encrypt(payload: dict, key: bytes) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_LEN)
    cipher.update(MAGIC + salt)
    ciphertext, tag = cipher.encrypt_and_digest(raw)
    return MAGIC + salt + nonce + tag + ciphertext


def _decrypt(blob: bytes, key: bytes, source: Path) -> dict:
    if len(blob) < _MIN_BLOB_LEN or not blob.startswith(MAGIC):
        raise InvalidSecretFileError(f"Not a valid encrypted secret file: {source}")
    offset = len(MAGIC)
    salt = blob[offset:offset + _SALT_LEN]
    offset += _SALT_LEN
    nonce = blob[offset:offset + _NONCE_LEN]
    offset += _NONCE_LEN
    tag = blob[offset:offset + _TAG_LEN]
    offset += _TAG_LEN
    ciphertext = blob[offset:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_LEN)
    cipher.update(MAGIC + salt)
    try:
        raw = cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as exc:
        raise SecretStoreDecryptionError(
            f"Cannot authenticate {source}; it may be damaged or use a different keyring",
        ) from exc
    return _decode_json(raw, source)


def decrypt_encrypted_json(blob: bytes, key: bytes, source: Path) -> dict:
    """Decrypt one UMAENC1 JSON blob with an already-unwrapped master key."""
    return _decrypt(blob, _validated_master_key(key, "Secret-store"), Path(source))


def load_json(path: Path, state_root: Path) -> dict:
    """Read legacy plaintext or encrypted JSON, migrating plaintext in place."""
    path = Path(path)
    _keyring_path_for(path, state_root)
    blob = path.read_bytes()
    if blob.lstrip().startswith(b"{"):
        payload = _decode_json(blob, path)
        try:
            save_json(path, payload, state_root)
        except SecretStoreError as exc:
            log.warning("Secret-file migration failed for %s: %s", path, exc)
        return payload
    if not blob.startswith(MAGIC):
        raise InvalidSecretFileError(f"Unrecognized secret-file magic: {path}")
    return decrypt_encrypted_json(
        blob,
        _master_key(path, state_root, create=False),
        path,
    )


def save_json(path: Path, payload: dict, state_root: Path) -> None:
    """Atomically write an encrypted JSON object, never plaintext."""
    path = Path(path)
    _keyring_path_for(path, state_root)
    if not isinstance(payload, dict):
        raise TypeError("secret-store payload must be a dict")
    encrypted = _encrypt(payload, _master_key(path, state_root, create=True))
    _atomic_write(path, encrypted)


def migrate_file(path: Path, state_root: Path) -> bool:
    """Encrypt a legacy plaintext JSON file in place; return whether it changed."""
    path = Path(path)
    _keyring_path_for(path, state_root)
    blob = path.read_bytes()
    if blob.startswith(MAGIC):
        return False
    if not blob.lstrip().startswith(b"{"):
        raise InvalidSecretFileError(f"Unrecognized secret-file magic: {path}")
    payload = _decode_json(blob, path)
    save_json(path, payload, state_root)
    return True
