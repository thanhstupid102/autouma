"""Re-wrap the state root's master key without rewriting encrypted payloads."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime_paths import atomic_write_private_bytes, resolve_state_root  # noqa: E402
from uma_api import secret_store  # noqa: E402


EXIT_KEYRING = 3
EXIT_BACKEND = 4
EXIT_PAYLOAD_SCAN = 5
EXIT_VERIFICATION = 6
EXIT_WRITE = 7
EXIT_UNEXPECTED = 8


class ConversionError(RuntimeError):
    def __init__(self, exit_code: int, message: str):
        super().__init__(message)
        self.exit_code = exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the existing state-root keyring between Windows DPAPI and "
            "passphrase protection without changing encrypted account files."
        ),
    )
    parser.add_argument(
        "--to",
        choices=("dpapi", "passphrase"),
        required=True,
        dest="target_backend",
        help="Backend that should protect the existing master key.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Verify, back up, and atomically replace the live keyring.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the conversion without modifying anything (the default).",
    )
    return parser


def _encrypted_account_files(accounts_dir: Path) -> list[Path]:
    if not accounts_dir.is_dir():
        return []
    encrypted: list[Path] = []
    try:
        candidates = sorted(path for path in accounts_dir.rglob("*") if path.is_file())
        for path in candidates:
            with path.open("rb") as source:
                if source.read(len(secret_store.MAGIC)) == secret_store.MAGIC:
                    encrypted.append(path)
    except OSError as exc:
        raise ConversionError(
            EXIT_PAYLOAD_SCAN,
            f"Could not inspect encrypted account files under {accounts_dir}.",
        ) from exc
    return encrypted


def _print_report(
    state_root: Path,
    keyring_path: Path,
    source_backend: str,
    target_backend: str,
    encrypted_count: int,
    *,
    legacy_headerless: bool,
    apply: bool,
) -> None:
    current = source_backend
    if legacy_headerless:
        current += " (legacy headerless)"
    print(f"State root: {state_root}")
    print(f"Keyring path: {keyring_path}")
    print(f"Current backend: {current}")
    print(f"Encrypted files protected: {encrypted_count}")
    print(f"Conversion: {source_backend} -> {target_backend}")
    print(
        "Action: re-wrap the existing master key, back up the original, and "
        "atomically replace only the keyring",
    )
    if apply:
        print("Mode: apply")
    else:
        print("Mode: dry-run (no files will be modified)")
    print(
        "Verification: re-read the staged keyring and decrypt one existing "
        "account file",
    )


def _staging_path(keyring_path: Path) -> Path:
    return keyring_path.with_name(
        f".{keyring_path.name}.portable-{uuid.uuid4().hex}.tmp",
    )


def _backup_path(keyring_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    candidate = keyring_path.with_name(f"{keyring_path.name}.backup-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = keyring_path.with_name(
            f"{keyring_path.name}.backup-{timestamp}.{counter}",
        )
        counter += 1
    return candidate


def _verify_candidate(
    staging_path: Path,
    encrypted_path: Path,
    original_key: bytes,
) -> None:
    secret_store.clear_key_cache()
    recovered_key = secret_store.load_master_key(staging_path)
    if not hmac.compare_digest(recovered_key, original_key):
        raise RuntimeError("staged keyring recovered a different master key")
    encrypted_blob = encrypted_path.read_bytes()
    secret_store.decrypt_encrypted_json(
        encrypted_blob,
        recovered_key,
        encrypted_path,
    )


def _read_original_keyring(keyring_path: Path) -> bytes:
    try:
        return keyring_path.read_bytes()
    except FileNotFoundError as exc:
        raise ConversionError(
            EXIT_KEYRING,
            f"Secret-store keyring does not exist: {keyring_path}",
        ) from exc
    except OSError as exc:
        raise ConversionError(
            EXIT_KEYRING,
            f"Could not read the secret-store keyring: {keyring_path}",
        ) from exc


def _run(target_backend: str, *, apply: bool) -> int:
    paths = resolve_state_root(ROOT)
    state_root = paths.root
    keyring_path = paths.keyring_path
    original_blob = _read_original_keyring(keyring_path)
    try:
        source_backend = secret_store.keyring_backend(keyring_path)
    except secret_store.SecretStoreError as exc:
        raise ConversionError(EXIT_KEYRING, str(exc)) from exc

    encrypted_files = _encrypted_account_files(paths.accounts_dir)
    legacy_headerless = not original_blob.startswith(secret_store.KEYRING_MAGIC)
    _print_report(
        state_root,
        keyring_path,
        source_backend,
        target_backend,
        len(encrypted_files),
        legacy_headerless=legacy_headerless,
        apply=apply,
    )

    if source_backend == target_backend:
        print(f"No conversion needed; the keyring already uses {target_backend}.")
        return 0

    try:
        secret_store.validate_keyring_backend(target_backend)
    except secret_store.SecretStoreUnavailableError as exc:
        raise ConversionError(EXIT_BACKEND, str(exc)) from exc

    if not apply:
        print("Run again with --apply to convert in place.")
        return 0

    if not encrypted_files:
        raise ConversionError(
            EXIT_VERIFICATION,
            "No encrypted account file is available for end-to-end verification; "
            "the live keyring was not changed.",
        )

    try:
        original_key = secret_store.load_master_key(keyring_path)
    except secret_store.SecretStoreError as exc:
        raise ConversionError(
            EXIT_BACKEND,
            f"Could not unwrap the existing {source_backend} keyring: {exc}",
        ) from exc

    try:
        candidate_blob = secret_store.wrap_master_key(original_key, target_backend)
    except secret_store.SecretStoreUnavailableError as exc:
        raise ConversionError(EXIT_BACKEND, str(exc)) from exc
    except secret_store.SecretStoreError as exc:
        raise ConversionError(
            EXIT_BACKEND,
            f"Could not wrap the master key for {target_backend}.",
        ) from exc

    staging_path = _staging_path(keyring_path)
    try:
        try:
            atomic_write_private_bytes(staging_path, candidate_blob)
        except OSError as exc:
            raise ConversionError(
                EXIT_WRITE,
                f"Could not write the staged keyring beside {keyring_path}.",
            ) from exc
        try:
            _verify_candidate(staging_path, encrypted_files[0], original_key)
        except Exception as exc:
            raise ConversionError(
                EXIT_VERIFICATION,
                "Verification failed; the staged keyring was discarded and the "
                "live keyring was not changed.",
            ) from exc
    finally:
        secret_store.clear_key_cache()
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    if _read_original_keyring(keyring_path) != original_blob:
        raise ConversionError(
            EXIT_KEYRING,
            "The live keyring changed during conversion; no replacement was made.",
        )

    backup_path = _backup_path(keyring_path)
    try:
        atomic_write_private_bytes(backup_path, original_blob)
    except OSError as exc:
        raise ConversionError(
            EXIT_WRITE,
            f"Could not create the required keyring backup: {backup_path}",
        ) from exc
    print(f"Verified account file: {encrypted_files[0]}")
    print(f"Backup: {backup_path}")

    if _read_original_keyring(keyring_path) != original_blob:
        raise ConversionError(
            EXIT_KEYRING,
            "The live keyring changed after backup; no replacement was made.",
        )
    try:
        atomic_write_private_bytes(keyring_path, candidate_blob)
    except OSError as exc:
        raise ConversionError(
            EXIT_WRITE,
            f"Could not atomically replace the live keyring: {keyring_path}. "
            f"The backup remains at {backup_path}.",
        ) from exc
    secret_store.clear_key_cache()
    print(f"Converted keyring: {source_backend} -> {target_backend}")
    print("Encrypted payloads modified: 0")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args.target_backend, apply=args.apply)
    except ConversionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print(
            "Error: keyring conversion failed unexpectedly; the live keyring "
            "was not intentionally changed.",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
