"""Application-side login orchestration (§13.2 B1 first step).

The post-login master.mdb freshness check moved here verbatim from
uma_api/game_service.py:login -- transport no longer orchestrates master-data.
The asymmetry is deliberate and preserved: session logins (session refresh,
career-loop re-run, start-error relogin) go through login_with_master_refresh
and DO check master data; the auth bootstrap path (game_service.login_client)
never did and still does NOT.
"""

import logging

import uma_data as _master_data
from uma_data import master_updater as _master_updater
from backend.app.context import reload_master_json_data
from core.runtime_paths import resolve_state_root
from core.settings import Settings
from uma_api import game_service


log = logging.getLogger(__name__)


def ensure_master_data_current(client) -> None:
    """Best-effort post-login master.mdb freshness check (uma_data.master_updater).

    client.resource_server/client.res_ver are populated by
    UmaClient._refresh_resource_version from tool/start_session's data_headers
    during the login() call, so this is safe to run immediately after.
    ensure_current() itself gates on a res_ver marker, so most logins are a
    cheap local no-op. Wrapped in try/except so a CDN hiccup or a stale/offline
    box can NEVER turn a successful login into a failed one.
    """
    state_root = getattr(client, "state_root", None)
    if state_root is None:
        state_root = resolve_state_root(Settings.BASE_DIR).root

    try:
        updated = _master_updater.ensure_current(
            Settings.BASE_DIR,
            client.resource_server,
            client.res_ver,
            state_root=state_root,
        )
        if updated:
            regen = _master_data.generate(
                Settings.BASE_DIR,
                state_root=state_root,
            )
            if regen.get("success"):
                stale_files = _master_data.stale_master_json_files(
                    Settings.BASE_DIR,
                    state_root,
                )
                if stale_files:
                    log.warning(
                        "master.mdb auto-updated but hot-reload failed: "
                        "generated output remained stale"
                    )
                else:
                    reload_master_json_data(Settings.BASE_DIR, state_root)
                    log.info(
                        "master.mdb auto-updated + hot-reloaded "
                        f"(res_ver={client.res_ver})"
                    )
            else:
                log.warning(
                    "master.mdb auto-updated but hot-reload failed: "
                    f"{regen.get('detail')}"
                )
    except Exception as exc:
        log.warning(f"master.mdb post-login ensure skipped: {exc}")

    try:
        stale_files = _master_data.stale_master_json_files(
            Settings.BASE_DIR,
            state_root,
        )
        if stale_files:
            log.warning(_master_data.stale_master_json_warning(stale_files))
    except Exception as exc:
        log.warning(f"master-derived JSON staleness check skipped: {exc}")


def login_with_master_refresh(session) -> game_service.GameApiResponse:
    """Session login + the master-data freshness check every app flow expects."""
    client = game_service.require_client(session)
    result = game_service.login(session)
    ensure_master_data_current(client)
    return result
