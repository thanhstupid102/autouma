from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from career_bot.bot_config.defaults import SCENARIOS, default_bot_config
from career_bot.bot_config.schema import validate_bot_config
from career_bot.bot_config.ui_metadata import bot_config_field_specs
from core.runtime_paths import atomic_write_private_text, ensure_private_dir

log = logging.getLogger(__name__)


class BotConfigStore:
    """Reads the shipped default and writes active config under the state root.

    Every path here goes through ``validate_bot_config``, which runs
    ``career_bot.bot_config.migrations.migrate_bot_config`` first -- so a
    ``default.json``/``active.json`` written by an older schema version is
    upgraded on LOAD (and on save/import) instead of failing the strict
    unknown-key check.
    """

    def __init__(self, source_root: str | Path, state_root: str | Path):
        self.source_root = Path(source_root)
        self.state_root = Path(state_root)
        self.config_dir = self.state_root / "bot_config"
        self.default_path = self.source_root / "data" / "bot_config" / "default.json"
        self.legacy_active_path = self.source_root / "data" / "bot_config" / "active.json"
        self.active_path = self.config_dir / "active.json"

    def ensure(self) -> None:
        ensure_private_dir(self.config_dir)

    def read_default(self) -> dict[str, Any]:
        try:
            return validate_bot_config(json.loads(self.default_path.read_text(encoding="utf-8")))
        # read_text -> OSError / UnicodeDecodeError(ValueError); json.loads ->
        # JSONDecodeError(ValueError); validate_bot_config only ever raises
        # BotConfigValidationError, which subclasses ValueError.
        except (OSError, ValueError) as exc:
            log.warning(f"Default bot config load failed: {exc}")
            return default_bot_config()

    def read_active(self) -> dict[str, Any]:
        self.ensure()
        if not self.active_path.exists():
            if self.legacy_active_path.is_file():
                config = validate_bot_config(json.loads(
                    self.legacy_active_path.read_text(encoding="utf-8")
                ))
                self.write_active(config)
                log.info(
                    "Migrated legacy active bot config from %s to %s",
                    self.legacy_active_path,
                    self.active_path,
                )
                return config
            return self.read_default()
        return validate_bot_config(json.loads(self.active_path.read_text(encoding="utf-8")))

    def write_active(self, raw: Any) -> dict[str, Any]:
        self.ensure()
        config = validate_bot_config(raw)
        atomic_write_private_text(
            self.active_path,
            json.dumps(config, ensure_ascii=False, indent=2),
        )
        return config

    def reset_active(self) -> dict[str, Any]:
        self.ensure()
        if self.active_path.exists():
            self.active_path.unlink()
        return self.read_default()

    def response(self) -> dict[str, Any]:
        return {
            "success": True,
            "config": self.read_active(),
            "default_config": self.read_default(),
            "scenarios": list(SCENARIOS.values()),
            "fields": bot_config_field_specs(),
        }
