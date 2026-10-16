import logging
import os

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api_auth import install_api_auth, resolve_api_token_or_exit
from backend.app.exception_handlers import register_exception_handlers
from backend.app.routers import NormalRouter

from core.settings import Settings
from core.runtime_paths import resolve_state_root, state_paths_for
from uma_api import client_version
import uma_data

from .context import create_context
from .logging_setup import configure_console_logging


log = logging.getLogger(__name__)


def _publish_startup_app_ver(state_root):
    """Publish a local build when present and make source disagreement visible."""
    local_app_ver = None
    try:
        local_app_ver = client_version.read_app_ver_from_game()
        if local_app_ver:
            client_version.set_app_ver(
                state_root,
                local_app_ver,
                source="auto-startup",
            )
            log.info(
                f"app_ver auto-published from game install: {local_app_ver}"
            )
    except Exception as exc:
        log.warning(f"app_ver auto-publish skipped: {exc}")

    try:
        from uma_api import appstore_version as appstore

        if local_app_ver:
            store_app_ver = appstore.fetch_app_ver_from_store()
            if store_app_ver and store_app_ver != local_app_ver:
                log.warning(
                    "APP-VER mismatch: local game build %s differs from "
                    "App Store version %s; continuing with the local game build",
                    local_app_ver,
                    store_app_ver,
                )
        else:
            store_app_ver = appstore.ensure_app_ver_headless(state_root)
            if store_app_ver:
                log.info(f"app_ver from App Store (headless): {store_app_ver}")
    except Exception as exc:
        if local_app_ver:
            log.warning(f"App Store APP-VER comparison skipped: {exc}")
        else:
            log.warning(f"headless app_ver refresh skipped: {exc}")


def _run_startup_side_effects(base_dir, state_root):
    """Best-effort boot tasks that act on the REAL game install / master.mdb.

    Runs only for the production base_dir (see create_app) — a throwaway
    tmp runtime (tests) must never trigger the network master.mdb refresh or a
    data/ regeneration.
    """
    # main.py builds the app at import time (`app = create_app(...)`) and only
    # calls backend.app.cli.run() afterwards, so this production-only block runs
    # BEFORE the CLI boundary configures logging. Configure here too (idempotent)
    # or the operator loses every boot line below. Tests never reach this — they
    # always build with a tmp base_dir, which skips the whole function.
    configure_console_logging()

    # Best-effort APP-VER auto-publish (game-machine only). On a box with the game
    # installed, read the current bundleVersion straight from globalgamemanagers so
    # state-root/client_version.json stays current without running the manual
    # scripts/publish_client_version.py CLI by hand after every game update. On a
    # headless bot box (no Steam install) client_version.read_app_ver_from_game
    # returns None and this is a silent no-op -- it must never block or crash boot.
    _publish_startup_app_ver(state_root)

    # Best-effort headless master.mdb refresh. A guest pre-download request supplies
    # the current CDN base and resource version without requiring an account, auth,
    # login, or a local game install; any network/update failure must not block boot.
    try:
        from uma_data import master_updater as _mu
        if _mu.ensure_current_headless(base_dir, state_root=state_root):
            log.info("master.mdb refreshed headlessly (pre-download resource version)")
    except Exception as _hz_exc:
        log.warning(f"headless master.mdb refresh skipped: {_hz_exc}")

    master_data_startup_status = uma_data.status(base_dir, state_root)
    if master_data_startup_status.get("exists"):
        stale_files = uma_data.stale_master_json_files(base_dir, state_root)
        if stale_files and not os.environ.get("SWEEPY_SKIP_STARTUP_GEN"):
            master_data_startup_result = uma_data.generate(
                base_dir,
                state_root=state_root,
            )
            if master_data_startup_result.get("success"):
                log.info(
                    "master.mdb data generated: "
                    f"{master_data_startup_status.get('master_mdb_path')}"
                )
            else:
                log.warning(
                    "master.mdb data generation failed: "
                    f"{master_data_startup_result.get('detail')}"
                )
            stale_files = uma_data.stale_master_json_files(
                base_dir, state_root,
            )
        if stale_files:
            log.warning(uma_data.stale_master_json_warning(stale_files))
    elif master_data_startup_status.get("requires_user_action"):
        log.warning(
            "master.mdb requires user action: "
            f"{master_data_startup_status.get('master_mdb_path')}"
        )


def create_app(
    base_dir: str | Path | None = None,
    default_account: str | None = None,
    state_root: str | Path | None = None,
) -> FastAPI:
    """Assemble the FastAPI app from backend.app routers + the runtime context.

    This factory runs production-only startup side-effects, configures the runtime context,
    then build FastAPI + register every domain router, mount the built SPA assets,
    and register the SPA catch-all LAST so explicit routes + /static win.
    """
    api_token = resolve_api_token_or_exit()
    resolved_dir = str(Path(base_dir).absolute()) if base_dir is not None else str(Settings.BASE_DIR)
    paths = (
        state_paths_for(resolved_dir, state_root)
        if state_root is not None
        else resolve_state_root(resolved_dir)
    )
    # The startup side-effects target the real install; only the production runtime
    # (main.py) triggers them, never a tmp test runtime.
    if resolved_dir == str(Settings.BASE_DIR):
        _run_startup_side_effects(Path(resolved_dir), paths.root)

    ctx = create_context(base_dir, default_account, paths.root)

    app = FastAPI(
        docs_url=Settings.DOC_URL,
        redoc_url=Settings.REDOC_URL,
    )
    install_api_auth(app, api_token)
    app.router.add_event_handler("shutdown", ctx.session_manager.shutdown)
    # Typed domain exceptions → the HTTP envelope, once (§12.6). Registered
    # before the routers so every route it covers is covered from the first
    # request; see backend/app/exception_handlers.py for the mapped types.
    register_exception_handlers(app)
    router = NormalRouter(app)

    # Mount Vite-built assets when dist is present; restart required after first build.
    if (ctx.frontend_dist / "static").exists():
        app.mount("/static", StaticFiles(directory=ctx.frontend_dist / "static"), name="frontend-static")

    # SPA history fallback ("/" and "/{full_path:path}", backend/app/routers/others/):
    # client-side routes (/account/:name, /setup, /library, ...) have no server route,
    # so a direct load or refresh would 404 without this. Registered last (after the
    # /static mount above and every other router), so every explicit route and the
    # /static mount take precedence over the catch-all.
    router.include_catchall()

    app.state.ctx = ctx
    return app
