"""Regenerate data/bot_config/default.json from the typed defaults.

The typed defaults (career_bot/bot_config/defaults.py:default_bot_config) are
the single source of truth (§12.6); the committed JSON is a generated artifact
that tests/test_bot_config_default_sync.py keeps honest.

Usage (repo root):
    python scripts/gen_default_bot_config.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_bot.bot_config.defaults import default_bot_config  # noqa: E402


def main() -> None:
    target = ROOT / "data" / "bot_config" / "default.json"
    payload = json.dumps(default_bot_config(), indent=2, ensure_ascii=False) + "\n"
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    if old == payload:
        print(f"{target} already in sync")
        return
    target.write_text(payload, encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
