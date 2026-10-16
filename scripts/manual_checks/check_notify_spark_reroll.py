"""Manual assertion check: the Discord webhook embed renders a spark reroll.

Run from the repo root: `python scripts/manual_checks/check_notify_spark_reroll.py`
(prints nothing and exits 0 on success; raises AssertionError on failure).
"""
import pathlib
import sys

# scripts/manual_checks/<file>.py -> parents[2] is the repo root. (This file used
# to live in tests/, where parent.parent reached the root; the move one level
# deeper needs parents[2].)
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from integrations.discord import notify  # noqa: E402


embed = notify._build_embed({
    "status": "finished",
    "spark_reroll_sparks": [
        [{"name": "Speed", "stars": 3, "category": "stat"}],
        [{"name": "Stamina", "stars": 2, "category": "stat"}],
    ],
    "spark_reroll_choice": 2,
})
field = next(field for field in embed["fields"] if "spark" in field["name"].lower())
assert "**Original**\n**📊 Stat:** Speed ★★★" in field["value"]
assert "**Rerolled:**\n**📊 Stat:** Stamina ★★" in field["value"]
assert field["value"].endswith("🤖 Bot chose: **Rerolled**")
