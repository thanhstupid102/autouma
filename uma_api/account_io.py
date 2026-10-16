import json
import os
import re
from pathlib import Path
from typing import Any, cast
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256

from core.runtime_paths import ensure_private_dir
from uma_api import secret_store
from uma_api.identity import prepare_account_config_for_storage

MAGIC = b"UMAACCT1"
_PBKDF2_ITERS = 200_000
_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32


class BadPassphrase(Exception):
    pass


def safe_account_name(name: str) -> str:
    """Sanitize an account name for safe use in a filename (no path traversal)."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "").strip())
    cleaned = cleaned.strip(".") or "account"
    return cleaned


def _derive(passphrase: str, salt: bytes) -> bytes:
    return PBKDF2(cast(str, passphrase.encode("utf-8")), salt, dkLen=_KEY_LEN,
                  count=_PBKDF2_ITERS, hmac_hash_module=SHA256)


def encrypt_bundle(payload: dict, passphrase: str) -> bytes:
    raw = json.dumps(payload).encode("utf-8")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(raw)
    # MAGIC | salt | nonce | tag(16) | ciphertext
    return MAGIC + salt + nonce + tag + ct


_MIN_BLOB_LEN = len(MAGIC) + _SALT_LEN + _NONCE_LEN + 16  # 52: header + GCM tag


def decrypt_bundle(blob: bytes, passphrase: str) -> dict:
    if blob[:len(MAGIC)] != MAGIC or len(blob) < _MIN_BLOB_LEN:
        raise BadPassphrase("Not a valid account bundle")
    off = len(MAGIC)
    salt = blob[off:off + _SALT_LEN]; off += _SALT_LEN
    nonce = blob[off:off + _NONCE_LEN]; off += _NONCE_LEN
    tag = blob[off:off + 16]; off += 16
    ct = blob[off:]
    key = _derive(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        raw = cipher.decrypt_and_verify(ct, tag)
    except ValueError:
        raise BadPassphrase("Wrong passphrase or corrupted bundle")
    return json.loads(raw.decode("utf-8"))


def read_account_files(accounts_dir: str, state_root: str | Path, name: str) -> dict:
    """Return {'game': <name>.json, 'steam': <name>.steam.json or None}."""
    out: dict[str, Any] = {}
    game_path = Path(accounts_dir) / f"{name}.json"
    steam_path = Path(accounts_dir) / f"{name}.steam.json"
    if not game_path.exists():
        raise FileNotFoundError(f"Account '{name}' not found")
    out["game"] = secret_store.load_json(game_path, Path(state_root))
    if steam_path.exists():
        out["steam"] = secret_store.load_json(steam_path, Path(state_root))
    else:
        out["steam"] = None
    return out


def write_account_files(accounts_dir: str, state_root: str | Path, name: str, data: dict):
    ensure_private_dir(accounts_dir)
    safe = safe_account_name(name)
    game_path = Path(accounts_dir) / f"{safe}.json"
    steam_path = Path(accounts_dir) / f"{safe}.steam.json"
    game_config = prepare_account_config_for_storage(data["game"])
    secret_store.save_json(game_path, game_config, Path(state_root))
    if data.get("steam") is not None:
        secret_store.save_json(steam_path, data["steam"], Path(state_root))
