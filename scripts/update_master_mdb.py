"""Download and validate the current master.mdb without launching the game."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.settings import Settings  # noqa: E402
from uma_api import client_version  # noqa: E402
from core.runtime_paths import resolve_state_root  # noqa: E402
from uma_data import master_updater  # noqa: E402
from uma_data.master_updater import (  # noqa: E402
    MasterUpdateError,
    connection_info_from_start_session,
    fetch_master_mdb,
)


STATE_ROOT = resolve_state_root(ROOT).root
DEFAULT_WAREHOUSE = STATE_ROOT / "api_warehouse"


def _load_start_session(path: Path) -> tuple[str, str]:
    try:
        with path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, ValueError) as exc:
        raise MasterUpdateError(f"could not read start_session response {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MasterUpdateError(f"start_session response must be a JSON object: {path}")
    return connection_info_from_start_session(payload)


def _latest_warehouse_response() -> Path | None:
    candidates = list(DEFAULT_WAREHOUSE.glob("*/tool__start_session.json"))
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch, LZ4-decompress, and integrity-check master.mdb.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Resolve the resource server/version with an unauthenticated guest "
            "client and refresh the configured master.mdb."
        ),
    )
    parser.add_argument(
        "--base",
        help="Resource server base from data_headers.server_list.resource_server.",
    )
    parser.add_argument("--res-ver", help="Resource version from data.resource_version.")
    parser.add_argument(
        "--start-session-response",
        "--start-session",
        dest="start_session_response",
        type=Path,
        help=(
            "Saved tool/start_session JSON. Used for any missing --base/--res-ver; "
            "the newest api_warehouse response is used automatically when omitted."
        ),
    )
    parser.add_argument(
        "--root-url",
        default=os.environ.get("UMA_ROOT_MANIFEST_URL"),
        help=(
            "Optional direct root-manifest URL override or template containing "
            "{base}/{res_ver}/{timestamp}. Can also be set with "
            "UMA_ROOT_MANIFEST_URL."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and validate everything without replacing master.mdb.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries after the first request (default: 3).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.headless:
        refreshed = master_updater.ensure_current_headless(Settings.BASE_DIR)
        resource_server = client_version.get_resource_server(STATE_ROOT)
        resource_version = client_version.get_res_ver(STATE_ROOT)
        print(f"resource version: {resource_version or 'unavailable'}")
        print(f"resource server: {resource_server or 'unavailable'}")
        print(f"headless refresh result: {refreshed}")
        return 0 if resource_server and resource_version else 1

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.retries < 0:
        parser.error("--retries must not be negative")

    response_path = args.start_session_response
    if response_path is None and (not args.base or not args.res_ver):
        response_path = _latest_warehouse_response()

    base = args.base
    resource_version = args.res_ver
    try:
        if response_path is not None and (not base or not resource_version):
            response_base, response_version = _load_start_session(response_path)
            base = base or response_base
            resource_version = resource_version or response_version
        if not base:
            raise MasterUpdateError(
                "resource server base is unavailable; pass --base or --start-session-response"
            )
        if not resource_version:
            raise MasterUpdateError(
                "resource version is unavailable; pass --res-ver or --start-session-response"
            )
        result = fetch_master_mdb(
            base,
            resource_version,
            Settings.MASTER_MDB_PATH,
            root_url=args.root_url,
            dry_run=args.dry_run,
            timeout=args.timeout,
            retries=args.retries,
        )
    except MasterUpdateError as exc:
        print(f"master update failed: {exc}", file=sys.stderr)
        return 1

    old_size = "missing" if result.old_size is None else str(result.old_size)
    action = "validated (dry run; destination unchanged)" if args.dry_run else "replaced"
    print(f"resource version: {result.resource_version}")
    print(f"manifest chain: {result.windows_manifest_hname} -> {result.master_manifest_hname}")
    print(f"master object: {result.master_hname} ({result.compressed_size} compressed bytes)")
    print(f"{result.destination}: {old_size} -> {result.new_size} bytes ({action})")
    print(f"integrity_check: {result.integrity_result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
