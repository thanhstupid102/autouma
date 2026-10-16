"""Small shared helper behind the per-account JSON file stores for account
config, selection, auto-delete config, and Steam tokens.

This intentionally captures only what all four stores have in common:
  - sanitizing an account name into a safe filename stem
  - the file path under a given state_root/<subdir>/
  - reading/writing JSON, optionally through the encrypted auth secret store
  - "missing file" / "corrupt JSON" both falling back to a caller-supplied default

Anything store-specific (which subdirectory, the filename suffix, whether
repeated dots in the sanitized name are additionally collapsed, and any
per-store normalization like normalize_auto_delete_config) stays in each store
module, not here.
"""
import json
import re
from pathlib import Path

from core.runtime_paths import ensure_private_dir
from uma_api import secret_store


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DOT_RUN_RE = re.compile(r"\.{2,}")


class JsonFileStore:
    """Reproduces the shared path/sanitize/serialize/read behaviour of the
    four JSON stores, parameterized per-store where they differ.
    """

    def __init__(self, state_root, subdir, suffix=".json", collapse_dot_runs=True,
                 default_stem="default", encrypted=False):
        self.state_root = Path(state_root)
        self.subdir = subdir
        self.suffix = suffix
        self.collapse_dot_runs = collapse_dot_runs
        self.default_stem = default_stem
        self.encrypted = encrypted

    def _sanitize(self, name):
        safe = _SANITIZE_RE.sub("_", str(name or "").strip())
        if self.collapse_dot_runs:
            # Collapse dot runs so a name like "../evil" can't escape the directory.
            safe = _DOT_RUN_RE.sub("_", safe)
        return safe or self.default_stem

    def path(self, name):
        stem = self._sanitize(name)
        return self.state_root / self.subdir / f"{stem}{self.suffix}"

    def save(self, name, data):
        """Write `data` as indented UTF-8 JSON. Raises on failure; callers
        wrap this to preserve their own best-effort try/except + logging."""
        path = self.path(name)
        ensure_private_dir(path.parent)
        if self.encrypted:
            secret_store.save_json(path, data, self.state_root)
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, name, default=None):
        """Return the parsed JSON for `name`, or `default` if the file is
        missing or fails to parse. Never raises."""
        path = self.path(name)
        if not path.exists():
            return default
        try:
            if self.encrypted:
                return secret_store.load_json(path, self.state_root)
            return json.loads(path.read_text(encoding="utf-8"))
        # Preserve each store's established corrupt-file fallback while letting
        # DPAPI/keyring availability failures surface to the caller.
        except (
            OSError,
            ValueError,
            secret_store.InvalidSecretFileError,
            secret_store.SecretStoreDecryptionError,
        ):
            return default

    def delete(self, name):
        path = self.path(name)
        if path.exists():
            path.unlink()
