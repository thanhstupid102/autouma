"""Publish APP-VER from an installed Steam game into shared runtime state.

Run this on the machine that has Umamusume installed, then copy/sync
``<state_root>/client_version.json`` to the headless bot (or place the state root on
a shared location). RES-VER is deliberately untouched because it is server-led.

The game-dir lookup + bundleVersion parsing this script needs live in
``uma_api.client_version`` (moved there 2026-07) so the auto-startup path
(``backend.app.app``) shares one implementation instead of a second copy --
this script re-imports the names below purely for its own more granular,
step-by-step CLI diagnostics (see main()).
"""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uma_api import client_version  # noqa: E402
from core.runtime_paths import resolve_state_root  # noqa: E402
from uma_api.client_version import (  # noqa: E402
    GLOBAL_GAME_MANAGERS,
    find_game_dir,
    parse_app_version,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish Umamusume bundleVersion to state-root/client_version.json."
    )
    parser.add_argument("--game-dir", help="Path to the UmamusumePrettyDerby install directory")
    parser.add_argument("--dry-run", action="store_true", help="Detect and print without writing")
    args = parser.parse_args(argv)

    game_dir = Path(args.game_dir).expanduser() if args.game_dir else find_game_dir()
    if not game_dir:
        print(
            "Could not find Steam app 3224770. Pass --game-dir pointing to the "
            "UmamusumePrettyDerby install directory.",
            file=sys.stderr,
        )
        return 2

    managers = game_dir / GLOBAL_GAME_MANAGERS
    if not managers.is_file():
        print(
            f"globalgamemanagers not found at {managers}. Pass the correct --game-dir.",
            file=sys.stderr,
        )
        return 2

    try:
        version = parse_app_version(managers.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"Could not determine app_ver: {exc}", file=sys.stderr)
        return 1

    state_root = resolve_state_root(ROOT).root
    old = client_version.get_app_ver(state_root)
    destination = client_version.client_version_path(state_root)
    print(f"app_ver: {old or '<unset>'} -> {version}")
    print(f"client_version.json: {destination}")
    if args.dry_run:
        print("dry-run: no file written")
        return 0
    if not client_version.set_app_ver(state_root, version, source="publisher"):
        print(f"Failed to write {destination}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
