import logging
import ipaddress
import sys
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI

if TYPE_CHECKING:
    from uma_api.session import SessionManager


log = logging.getLogger(__name__)


def _web_ui_access_location(host: str, port: int) -> str:
    if host == "0.0.0.0":
        return f"http://localhost:{port} (bound on all IPv4 interfaces)"
    if host == "::":
        return f"http://[::1]:{port} (bound on all IPv6 interfaces)"
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        display_host = host
    else:
        display_host = f"[{host}]" if parsed.version == 6 else host
    return f"http://{display_host}:{port}"


def run(app: FastAPI) -> None:
    import uvicorn
    from uma_api.client import get_ticket as _get_ticket
    from uma_api import secret_store

    from backend.app import api_auth
    from backend.app import context
    from backend.app.logging_setup import configure_console_logging
    import backend.app.domain.account_store as account_store
    import integrations.game_process.gameproc as gameproc

    # The console IS the operator's live run log: configure the message-only
    # stdout handler before anything else can emit.
    configure_console_logging()

    port, account, debug, host = gameproc.parse_cli_args(sys.argv[1:])
    api_token = api_auth.resolve_api_token_or_exit()
    app.state.api_token = api_token
    api_auth.require_token_for_bind(host, api_token)
    if debug:
        gameproc.enable_api_trace()
    gameproc.set_console_topmost()
    gameproc.kill_listeners_on_port(port)

    if account:
        context.DEFAULT_ACCOUNT = account
        startup_session = cast("SessionManager", context.session_manager).get(account)
        try:
            saved_cfg = account_store.load_account_config(account)
            token_blob = account_store.load_steam_token(account)
        except secret_store.SecretStoreError as exc:
            raise SystemExit(
                f"Cannot load encrypted auth for account '{account}': {exc}",
            ) from None
        pending_cfg = dict(saved_cfg or {})
        if saved_cfg:
            log.info(f"Loaded saved game credentials for account '{account}'.")

        if token_blob and token_blob.get('refresh_token'):
            try:
                _sid, _tkt, _ = _get_ticket(refresh_token=token_blob['refresh_token'])
                pending_cfg.update({'steam_id': _sid, 'steam_session_ticket': _tkt})
                log.info(f"Steam auto-login ready for '{account}'.")
            except Exception as exc:
                if str(exc) == 'TOKEN_INVALID':
                    account_store.clear_steam_token(account)
                    log.warning(f"Saved Steam token for '{account}' was invalid; cleared. Scan QR in the web UI.")
                else:
                    log.warning(f"Steam auto-login skipped for '{account}': {type(exc).__name__}. Use the web UI.")
        elif not saved_cfg:
            log.info(f"No saved auth for '{account}'; sign in from the web UI.")
        startup_session.pending_game_auth_config = dict(pending_cfg)
    else:
        log.info('No --account given: multi-account mode. Add/select accounts in the web UI.')

    log.info(f"Access the Web UI at: {_web_ui_access_location(host, port)}")
    uvicorn.run(app, host=host, port=port, log_level='error')
