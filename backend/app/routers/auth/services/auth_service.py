import logging
import time

from fastapi import HTTPException

from backend.app.runner_state import require_idle
from core.settings import Settings
from uma_api.session import Session, SessionManager, get_session_manager
from backend.app import context
import backend.app.domain.account_status as account_status
import backend.app.domain.account_store as account_store
import backend.app.domain.rank_point as rank_point
from backend.app.domain.parent_roster import build_parents


log = logging.getLogger(__name__)


def _new_uma_client(cfg):
    from uma_api.client import UmaClient

    try:
        return UmaClient(
            cfg,
            trace_enabled=(Settings.UMA_TRACE == '1'),
            state_root=context.state_root,
        )
    except TypeError as exc:
        if "state_root" not in str(exc):
            raise
        # Offline test doubles and third-party factories may still expose the
        # pre-state-root constructor. Binding below supplies the runtime root.
        return UmaClient(
            cfg,
            trace_enabled=(Settings.UMA_TRACE == '1'),
        )


class SteamLoginRequiredError(Exception):
    """Raised when this request has no usable Steam credential source."""


def _resolve_steam_ticket(req, staged_cfg, account_name):
    """Pick the Steam session ticket this login attempt will use.

    The branch order is the policy: request ticket, typed credentials, staged
    ticket, then saved refresh token. Returns ``(steam_id, ticket,
    refresh_token)``; the last value is non-empty when Steam minted a replacement
    token that should be persisted.
    """
    from uma_api.client import get_ticket

    refresh_token = ''
    if req.steam_id and req.steam_session_ticket:
        sid = str(req.steam_id)
        tkt = str(req.steam_session_ticket)
        log.info('Using provided Steam ticket')
    elif req.username and req.password:
        sid, tkt, refresh_token = get_ticket(
            req.username, req.password, req.code,
        )
    elif staged_cfg.get('steam_id') and staged_cfg.get('steam_session_ticket'):
        sid = str(staged_cfg['steam_id'])
        tkt = str(staged_cfg['steam_session_ticket'])
        log.info('Using staged Steam ticket')
    else:
        saved = account_store.load_steam_token(account_name) if account_name else None
        if saved and saved.get("refresh_token"):
            try:
                sid, tkt, refresh_token = get_ticket(
                    refresh_token=saved["refresh_token"],
                )
            except Exception as exc:
                if str(exc) == 'TOKEN_INVALID':
                    account_store.clear_steam_token(account_name)
                    raise SteamLoginRequiredError from exc
                raise
        else:
            raise SteamLoginRequiredError
    return sid, tkt, refresh_token


class _LoginAttempts:
    """The game-login ladder for one already-prepared auth config.

    Owns the state the inline recovery block used to mutate across three
    attempts: ``cfg`` (whose ``steam_id`` / ``steam_session_ticket`` each retry
    re-binds IN PLACE, so the caller's persist + 2FA paths see the ticket that
    actually logged in), the account the rotated refresh tokens are saved under,
    and the request whose typed credentials drive the manual fallback.
    """

    def __init__(self, cfg, account_name, req, has_form_creds):
        self.cfg = cfg
        self.account_name = account_name
        self.req = req
        self.has_form_creds = has_form_creds

    def make_client(self):
        return _new_uma_client(self.cfg).bind_api_warehouse(
            context.state_root,
            self.account_name,
        )

    def run(self, initial_client=None):
        """Log in, recovering from a stale ticket. Returns ``(res, gated_client)``.

        Re-raises the original login error when no recovery path applied.
        """
        from uma_api import game_service
        from uma_api.client import get_ticket
        from uma_api.errors import SteamAccountRemoveChainedError
        from career_bot.delay import GateKeeper

        cfg = self.cfg
        req = self.req
        account_name = self.account_name

        c = initial_client or self.make_client()
        gated_client = GateKeeper(c)
        try:
            res = game_service.login_client(gated_client)
            if not res:
                raise Exception("empty login response")
        except SteamAccountRemoveChainedError:
            raise
        except Exception as login_err:
            # The Steam session ticket we logged in with can be stale: a ticket
            # minted at startup may expire before
            # the web UI is opened. Recover silently instead of bouncing back to QR:
            # first mint a fresh ticket from the saved refresh token, then fall back to a
            # manual Steam login when credentials were actually provided.
            recovered = False
            saved_token = account_store.load_steam_token(account_name) if account_name else None
            if saved_token and saved_token.get('refresh_token'):
                try:
                    log.warning(f'Steam ticket login failed ({login_err}); retrying with saved refresh token')
                    sid, tkt, rotated_token = get_ticket(refresh_token=saved_token['refresh_token'])
                    cfg['steam_id'] = sid
                    cfg['steam_session_ticket'] = tkt
                    c = self.make_client()
                    gated_client = GateKeeper(c)
                    res = game_service.login_client(gated_client)
                    recovered = True
                    if account_name and rotated_token:
                        account_store.save_steam_token(account_name, rotated_token, sid)
                except SteamAccountRemoveChainedError:
                    raise
                except Exception as refresh_err:
                    if str(refresh_err) == 'TOKEN_INVALID' and account_name:
                        account_store.clear_steam_token(account_name)
                    log.warning(f'Saved refresh token login failed ({refresh_err})')
            if not recovered and self.has_form_creds:
                log.warning('Falling back to manual Steam login')
                sid, tkt, minted_token = get_ticket(req.username, req.password, req.code)
                cfg['steam_id'] = sid
                cfg['steam_session_ticket'] = tkt
                c = self.make_client()
                gated_client = GateKeeper(c)
                res = game_service.login_client(gated_client)
                recovered = True
                if account_name and minted_token:
                    account_store.save_steam_token(account_name, minted_token, sid)
            if not recovered:
                raise
        return res, gated_client


def _gate_client(client, account_name):
    from career_bot.delay import GateKeeper

    bound = client.bind_api_warehouse(context.state_root, account_name)
    return GateKeeper(bound)


def _steam_link_removed_transition(session, saved_cfg, steam_id, steam_ticket):
    """Stage the account's registered device with the current Steam ticket."""
    staged_cfg = dict(saved_cfg)
    staged_cfg["steam_id"] = steam_id
    staged_cfg["steam_session_ticket"] = steam_ticket
    session.pending_transition_config = staged_cfg
    return {
        "success": False,
        "state": "needs_transition_link",
        "reason": "steam_link_removed",
        "viewer_id": str(saved_cfg["viewer_id"]),
    }


def _persist_client_auth(account_name, cfg, client):
    """Snapshot and durably save an authenticated identity or fail loudly."""
    from uma_api import bootstrap

    snapshotter = getattr(client, "auth_config_snapshot", None)
    if callable(snapshotter):
        cfg.update(snapshotter())
    if not bootstrap.has_game_auth_config(cfg):
        raise RuntimeError("Refusing to persist incomplete game authentication")
    try:
        saved = account_store.save_account_config(account_name, cfg)
    except Exception as exc:
        raise RuntimeError(
            "CRITICAL: game authentication changed but could not be persisted",
        ) from exc
    if saved is False:
        raise RuntimeError(
            "CRITICAL: game authentication changed but could not be persisted",
        )


def _clear_advisory_steam_unbound_marker(account_name, cfg, client):
    """Clear an unbind marker after the game accepts a Steam login."""
    marker_missing = object()
    if cfg.pop("steam_unbound_at", marker_missing) is marker_missing:
        return

    # An in-game rebind can restore a Steam identity, so this cached marker is
    # UI history only and must never decide whether a login is attempted.
    _persist_client_auth(account_name, cfg, client)


def _restore_session_after_login(session, cfg, account_name, gated_client):
    """Bind the logged-in client and re-hydrate this account's persisted state."""
    session.client = gated_client
    # Bind this account's saved pacing (turn delay / No-CD) onto its freshly-bound
    # TimingDNA so the run loop uses per-account values, not the module defaults.
    session.apply_delay_to_dna()
    # Restore the remembered team selection (deck/trainee/friend/parents/event).
    # reset_runtime() above cleared it to defaults; the UI hydrates from /api/auth/session.
    saved_selection = account_store.load_selection(account_name)
    if isinstance(saved_selection, dict) and saved_selection:
        session.selection = saved_selection
    account_store.apply_auto_delete_config(session)


def _load_career_data_after_login(session, d):
    """Fetch the in-progress career, if the login payload says one exists."""
    from uma_api import game_service

    career_data = None
    if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
        try:
            career_res = game_service.load_career(session)
            career_data = career_res.get('data')
        except Exception:
            pass
    return career_data


def _reset_lineage_caches(session):
    """Clear the per-login start/parent caches the dashboard build refills."""
    session.start_state = {}
    session.parent_cards = {}
    session.parent_rank_points = {}
    session.parent_g1_wins = {}
    session.parent_g1_sources = {}
    session.rental_parent_cards = {}
    session.rental_parent_g1_wins = {}
    session.rental_parent_g1_sources = {}


def _build_umas(d):
    """Dashboard trainee list from the login payload's ``card_list``."""
    umas = []
    card_list = d.get('card_list', [])
    for card in card_list:
        cid = str(card.get('card_id', card.get('id', '')))
        umas.append({
            'id': cid,
            'name': rank_point.chara_map.get(cid, f"Unknown ({cid})")
        })
    return umas


def _build_supports(d):
    """Dashboard support list from the login payload's ``support_card_list``."""
    supports = []
    support_card_list = d.get('support_card_list', [])
    for s in support_card_list:
        sid = str(s.get('support_card_id', s.get('id', '')))
        info = rank_point.support_map.get(sid)
        if info:
            supports.append({
                'id': sid,
                'name': info['name'],
                'type': rank_point.display_support_type(info['type']),
                'rarity': info['rarity']
            })
        else:
            supports.append({
                'id': sid,
                'name': f"Unknown ({sid})",
                'type': 'Unknown',
                'rarity': '?'
            })
    return supports


def _build_decks(d):
    """Dashboard deck list from the login payload's ``support_card_deck_array``."""
    decks = []
    deck_array = d.get('support_card_deck_array', [])
    for deck in deck_array:
        cards = []
        for cid in deck.get('support_card_id_array', []):
            sid = str(cid)
            info = rank_point.support_map.get(sid)
            if info:
                cards.append({
                    'id': sid,
                    'name': info['name'],
                    'rarity': info['rarity'],
                    'type': rank_point.display_support_type(info['type'])
                })
            else:
                cards.append({'id': sid, 'name': f'Unknown ({sid})', 'rarity': '?', 'type': '?'})

        decks.append({
            'id': deck.get('deck_id'),
            'name': deck.get('name', f'Deck {deck.get("deck_id")}'),
            'cards': cards
        })
    return decks


_ACCOUNT_LINK_DETAILS = {
    516: "This transition code can no longer be used from the current account.",
    517: (
        "The transition may already have completed. The staged device was kept; "
        "do not retry blindly because the account may now be bound."
    ),
    523: "The Trainer ID or link password is invalid.",
    524: "The requested account was not found.",
    526: "The transition account does not exist.",
    700: "The link password is invalid.",
    701: "The Trainer ID is invalid.",
    703: (
        "The account may already be bound to this staged device. The staged "
        "device was kept; do not retry blindly."
    ),
    704: "This Steam account has reached the PC account link limit.",
    705: "No platform user ID is linked to this account.",
    708: "No chained user ID is available for this account.",
    709: "This Steam account is still chained to another account.",
    900: "Account signup is temporarily unavailable for maintenance.",
    902: "Account data linking is temporarily unavailable for maintenance.",
    903: "Account chaining is temporarily unavailable for maintenance.",
}


def _account_link_failure(exc):
    from uma_api.account_link import ACCOUNT_LINK_ERROR_CODES

    raw_result_code = getattr(exc, "result_code", None)
    if raw_result_code is None:
        result_code = None
    else:
        try:
            result_code = int(raw_result_code)
        except (TypeError, ValueError):
            result_code = None
    error_code = (
        ACCOUNT_LINK_ERROR_CODES.get(result_code)
        if result_code is not None
        else None
    )
    if error_code is None:
        # A malformed success payload is a local protocol failure. Use the
        # closest client-binary constant instead of exposing an invented code.
        error_code = "INVALID_PARAMETER_ERROR"
    return {
        "success": False,
        "state": "failed",
        "error_code": error_code,
        "detail": (
            _ACCOUNT_LINK_DETAILS.get(
                result_code,
                "The account-link response was incomplete; staged data was preserved.",
            )
            if result_code is not None
            else "The account-link response was incomplete; staged data was preserved."
        ),
    }


def _transition_api_failure(exc):
    """Map transition session/auth failures without exposing a traceback."""
    from uma_api.errors import api_error_result_code
    from uma_api.update_guard import Diagnosis

    result_code = api_error_result_code(exc)
    if result_code in (201, 217):
        return {
            "success": False,
            "state": "failed",
            "error_code": Diagnosis.SESSION.value,
            "detail": (
                "The transition session expired or could not be re-established; "
                "account-link state was preserved."
            ),
        }
    if result_code == 203:
        return {
            "success": False,
            "state": "failed",
            "error_code": Diagnosis.AUTH_INVALIDATED.value,
            "detail": (
                "The game rejected the transition authentication; account-link "
                "state was preserved."
            ),
        }
    return None


def _transition_failure(error_code, detail):
    return {
        "success": False,
        "state": "failed",
        "error_code": error_code,
        "detail": detail,
    }


def _restart_transition_session(client):
    """Start one new SID chain without consuming it with load/index."""
    client.regen_sid()
    response = client.call(
        "tool/start_session",
        {"attestation_type": 0, "device_token": None},
    )
    adopter = getattr(client, "_adopt_start_session_response", None)
    if callable(adopter):
        adopter(response)


def _transition_call_with_session_retry(
    client,
    operation,
    on_session_restarted=None,
):
    """Retry one account-link call once after a 201/217 session failure."""
    from uma_api.errors import api_error_result_code

    try:
        return operation()
    except Exception as exc:
        if api_error_result_code(exc) not in (201, 217):
            raise
        _restart_transition_session(client)
        if on_session_restarted is not None:
            on_session_restarted()
        return operation()


def _preserve_pending_transition_auth(session, cfg, client):
    """Keep any staged auth rotation in memory without touching stored auth."""
    snapshotter = getattr(client, "auth_config_snapshot", None)
    if callable(snapshotter):
        cfg.update(snapshotter())
    session.pending_transition_config = dict(cfg)


def _steam_unbind_failure(error_code, detail):
    return {
        "success": False,
        "state": "failed",
        "error_code": error_code,
        "detail": detail,
    }


def _steam_preflight_account_link_failure(exc):
    failure = _account_link_failure(exc)
    failure["detail"] = (
        "The Trainer ID and link-password recovery path could not be proven. "
        f"{failure['detail']}"
    )
    return failure


def _stored_account_names(session):
    manager = get_session_manager()
    if (
        str(manager.base_dir) != str(session.base_dir)
        or manager.state_root != str(session.state_root)
    ):
        manager = SessionManager(
            base_dir=session.base_dir,
            state_root=session.state_root,
        )
    return manager.known_account_names()


def _login_stored_account(account_name, cfg, steam_token):
    """Build one authenticated client from stored auth without login retries."""
    from uma_api import game_service
    from uma_api.client import get_ticket

    sid, ticket, rotated_token = get_ticket(
        refresh_token=steam_token["refresh_token"],
    )
    login_cfg = dict(cfg)
    login_cfg["steam_id"] = sid
    login_cfg["steam_session_ticket"] = ticket
    client = _gate_client(
        _new_uma_client(login_cfg),
        account_name,
    )
    response = game_service.login_client(client)
    if not response:
        raise RuntimeError("Game login returned an empty response")
    if rotated_token:
        account_store.save_steam_token(account_name, rotated_token, sid)
    return client


def _account_link_result_code(response):
    headers = response.get("data_headers")
    if not isinstance(headers, dict):
        return None
    result_code = headers.get("result_code")
    if result_code is None:
        return None
    try:
        return int(result_code)
    except (TypeError, ValueError):
        return None


def _raise_account_link_result(endpoint, result_code):
    from uma_api.account_link import ACCOUNT_LINK_ERROR_TYPES, AccountLinkError

    error_type = ACCOUNT_LINK_ERROR_TYPES.get(result_code, AccountLinkError)
    raise error_type(
        result_code,
        endpoint,
        "account-link request failed",
    )


def _preflight_steam_recovery(session, target_cfg, link_password):
    """Prove Trainer ID recovery from a different locally stored account."""
    from uma_api import account_link, bootstrap

    target_viewer_id = str(target_cfg["viewer_id"])
    for account_name in _stored_account_names(session):
        if account_name == session.name:
            continue
        cfg = account_store.load_account_config(account_name) or {}
        steam_token = account_store.load_steam_token(account_name) or {}
        if (
            not bootstrap.has_game_auth_config(cfg)
            or not steam_token.get("refresh_token")
        ):
            continue
        try:
            client = _login_stored_account(account_name, cfg, steam_token)
        except Exception as exc:
            log.warning(
                "Steam unbind recovery preflight could not use account '%s': %s",
                account_name,
                type(exc).__name__,
            )
            continue

        preview = account_link.get_by_transition_code(
            client,
            password=link_password,
            input_viewer_id=target_viewer_id,
        )
        result_code = _account_link_result_code(preview)
        if result_code != 1:
            _raise_account_link_result(
                account_link.GET_BY_TRANSITION_CODE_ENDPOINT,
                result_code,
            )
        data = preview.get("data")
        if not isinstance(data, dict):
            data = {}
        return {
            "preflight_account": account_name,
            "name": data.get("name", preview.get("name")),
            "request_user_name": data.get(
                "request_user_name",
                preview.get("request_user_name"),
            ),
        }
    return None


def _validate_steam_unbind_target(session, req):
    from uma_api import bootstrap

    busy = require_idle(session)
    if busy:
        return None, {**busy, "state": "failed"}
    if req.confirm_account_name != session.name:
        raise HTTPException(
            status_code=400,
            detail="Account name confirmation does not match",
        )
    cfg = account_store.load_account_config(session.name) or {}
    if not bootstrap.has_game_auth_config(cfg):
        raise HTTPException(
            status_code=400,
            detail="No valid stored game authentication exists for this account",
        )
    return cfg, None


def _target_steam_client(session, cfg):
    if session.client is not None:
        return session.client
    steam_token = account_store.load_steam_token(session.name) or {}
    if not steam_token.get("refresh_token"):
        return None
    try:
        return _login_stored_account(session.name, cfg, steam_token)
    except Exception:
        log.exception(
            "Steam unbind could not authenticate target account '%s'",
            session.name,
        )
        return None


def _complete_login(session, cfg, account_name, gated_client, response):
    """Bind a successful login and build the dashboard response."""
    if not response:
        raise HTTPException(status_code=401, detail="Game login failed")

    _restore_session_after_login(
        session, cfg, account_name, gated_client,
    )
    if getattr(gated_client, "auth_key_rotated", False):
        _persist_client_auth(account_name, cfg, gated_client)
    _clear_advisory_steam_unbound_marker(account_name, cfg, gated_client)

    d = response.get('data', {})
    career_data = _load_career_data_after_login(session, d)

    account = account_status.get_account_status(session, d, career_data)
    session.account = account
    _reset_lineage_caches(session)
    account_status.update_start_state(session, d)

    session.dashboard_data = {
        "success": True,
        "state": "authenticated",
        "account": account,
        "umas": _build_umas(d),
        "supports": _build_supports(d),
        "decks": _build_decks(d),
        "parents": build_parents(session, d),
    }
    return session.dashboard_data


class AuthService:
    """Handlers for login, session exit, and account-link routes."""

    def __init__(self, session: Session):
        self.session = session

    async def login(self, req):
        from uma_api import bootstrap, game_service
        from uma_api.account_link import AccountLinkError
        from uma_api.errors import SteamAccountRemoveChainedError

        session = self.session
        busy = require_idle(session)
        if busy:
            return {**busy, "state": "failed"}
        staged_cfg = {}
        cfg = {}
        saved_cfg: dict[str, object] = {}
        sid = ''
        tkt = ''
        try:
            staged_cfg = dict(session.pending_game_auth_config)
            session.pending_game_auth_config = {}
            session.reset_runtime()

            has_form_creds = bool(req.username and req.password)
            account_name = session.name
            sid, tkt, refresh_token = _resolve_steam_ticket(
                req, staged_cfg, account_name,
            )

            if account_name and refresh_token:
                account_store.save_steam_token(
                    account_name, refresh_token, sid,
                )

            saved_cfg = account_store.load_account_config(account_name) or {}
            cfg = dict(
                staged_cfg
                if bootstrap.has_game_auth_config(staged_cfg)
                else saved_cfg
            )
            cfg['steam_id'] = sid
            cfg['steam_session_ticket'] = tkt

            if bootstrap.has_game_auth_config(cfg):
                initial_steam = (
                    cfg.get('steam_id'), cfg.get('steam_session_ticket'),
                )
                response, gated_client = _LoginAttempts(
                    cfg, account_name, req, has_form_creds,
                ).run()
                if initial_steam != (
                    cfg.get('steam_id'), cfg.get('steam_session_ticket'),
                ):
                    _persist_client_auth(
                        account_name, cfg, gated_client,
                    )
            else:
                bootstrap_result = bootstrap.bootstrap_steam_account(
                    steam_id=sid,
                    steam_session_ticket=tkt,
                    trace_enabled=(Settings.UMA_TRACE == '1'),
                    state_root=context.state_root,
                )
                cfg = dict(bootstrap_result.config)
                if (
                    bootstrap_result.state
                    is bootstrap.BootstrapState.NEEDS_TRANSITION_LINK
                ):
                    session.pending_transition_config = cfg
                    return {
                        "success": False,
                        "state": "needs_transition_link",
                    }
                if (
                    bootstrap_result.state
                    is bootstrap.BootstrapState.STEAM_SIGNUP_DISABLED
                ):
                    return {
                        "success": False,
                        "state": "steam_signup_disabled",
                    }

                gated_client = _gate_client(
                    bootstrap_result.client, account_name,
                )
                _persist_client_auth(account_name, cfg, gated_client)
                response = game_service.login_client(gated_client)

            return _complete_login(
                session, cfg, account_name, gated_client, response,
            )
        except SteamAccountRemoveChainedError as exc:
            if bootstrap.has_game_auth_config(saved_cfg):
                return _steam_link_removed_transition(
                    session, saved_cfg, sid, tkt,
                )
            return _account_link_failure(exc)
        except AccountLinkError as exc:
            return _account_link_failure(exc)
        except SteamLoginRequiredError:
            return {
                "success": False,
                "state": "needs_steam_login",
            }
        except Exception as e:
            msg = str(e)
            if "STEAM_GUARD_REQUIRED" in msg:
                session.pending_game_auth_config = dict(cfg or staged_cfg)
                return {
                    "success": False,
                    "state": "needs_steam_guard",
                    "needs_2fa": True,
                }
            return {
                "success": False,
                "state": "failed",
                "detail": str(e),
            }

    async def chain_transition_code(self, req):
        from uma_api import account_link, bootstrap, game_service
        from uma_api.account_link import AccountLinkError, LinkInputValidationError
        from uma_api.errors import ApiError, SteamAccountRemoveChainedError

        session = self.session
        if not session.pending_transition_config:
            raise HTTPException(
                status_code=409,
                detail="No staged Steam transition is available",
            )

        cfg = dict(session.pending_transition_config)
        stored_cfg = account_store.load_account_config(session.name) or {}
        steam_unbound_at = stored_cfg.get("steam_unbound_at")
        if steam_unbound_at is not None:
            cfg["steam_unbound_at"] = steam_unbound_at
        try:
            input_viewer_id = account_link.validate_trainer_id(
                req.input_viewer_id,
            )
            password = account_link.validate_link_password(req.password)

            if not bootstrap.has_game_auth_config(cfg):
                staged_udid = cfg.get("udid")
                if not isinstance(staged_udid, str) or not staged_udid.strip():
                    return _transition_failure(
                        "TRANSITION_STAGE_INVALID",
                        "The staged transition device is missing its UDID; staged data was preserved.",
                    )
                bootstrap_result = bootstrap.bootstrap_steam_account(
                    steam_id=str(cfg.get("steam_id") or ""),
                    steam_session_ticket=str(
                        cfg.get("steam_session_ticket") or "",
                    ),
                    trace_enabled=(Settings.UMA_TRACE == '1'),
                    state_root=context.state_root,
                    udid=staged_udid,
                )
                cfg = dict(bootstrap_result.config)
                if steam_unbound_at is not None:
                    cfg["steam_unbound_at"] = steam_unbound_at

                if (
                    bootstrap_result.state
                    is bootstrap.BootstrapState.STEAM_SIGNUP_DISABLED
                ):
                    return _transition_failure(
                        "STEAM_SIGNUP_DISABLED",
                        "This Steam account's Uma link was removed, so the server "
                        "will not let it register a new game account. Re-link it "
                        "from the game client and then press Re-establish.",
                    )

                if (
                    bootstrap_result.state
                    is bootstrap.BootstrapState.AUTHENTICATED
                ):
                    gated_client = _gate_client(
                        bootstrap_result.client, session.name,
                    )
                    _persist_client_auth(session.name, cfg, gated_client)
                    session.pending_transition_config = {}
                    response = game_service.login_client(gated_client)
                    dashboard = _complete_login(
                        session, cfg, session.name, gated_client, response,
                    )
                    dashboard["detail"] = (
                        "Steam was already linked to a game account, so Trainer "
                        "ID linking was not needed."
                    )
                    return dashboard

                if (
                    bootstrap_result.state
                    is not bootstrap.BootstrapState.NEEDS_TRANSITION_LINK
                ):
                    return _transition_failure(
                        "TRANSITION_BOOTSTRAP_UNAVAILABLE",
                        "The staged device could not be registered for transition linking; staged data was preserved.",
                    )
                if not bootstrap.has_game_auth_config(cfg):
                    return _transition_failure(
                        "TRANSITION_BOOTSTRAP_INCOMPLETE",
                        "The staged device did not receive usable game authentication; staged data was preserved.",
                    )
                client = bootstrap_result.client
            else:
                client = _new_uma_client(cfg)

            gated_client = _gate_client(client, session.name)
            _restart_transition_session(gated_client)
            _preserve_pending_transition_auth(
                session, cfg, gated_client,
            )

            preview = _transition_call_with_session_retry(
                gated_client,
                lambda: account_link.get_by_transition_code(
                    gated_client,
                    password=password,
                    input_viewer_id=input_viewer_id,
                ),
                lambda: _preserve_pending_transition_auth(
                    session, cfg, gated_client,
                ),
            )
            preview_data = preview.get("data")
            if not isinstance(preview_data, dict):
                preview_data = {}

            if getattr(req, "verify_only", False):
                return {
                    "success": True,
                    "state": "verified",
                    "name": preview_data.get("name", preview.get("name")),
                    "request_user_name": preview_data.get(
                        "request_user_name", preview.get("request_user_name"),
                    ),
                }

            chain_result = _transition_call_with_session_retry(
                gated_client,
                lambda: account_link.chain_by_transition_code(
                    gated_client,
                    password=password,
                    input_viewer_id=int(input_viewer_id),
                ),
                lambda: _preserve_pending_transition_auth(
                    session, cfg, gated_client,
                ),
            )
            gated_client.viewer_id = chain_result.chained_viewer_id
            gated_client.auth_key_hex = chain_result.auth_key_hex

            # The chain is irreversible enough that losing this key is the worst
            # possible outcome. Save it before start_session or any dashboard work.
            _persist_client_auth(session.name, cfg, gated_client)

            response = game_service.login_client(gated_client)
            dashboard = _complete_login(
                session, cfg, session.name, gated_client, response,
            )
            session.pending_transition_config = {}
            dashboard.update({
                "name": preview_data.get("name", preview.get("name")),
                "request_user_name": preview_data.get(
                    "request_user_name", preview.get("request_user_name"),
                ),
                "chained_user_name": chain_result.chained_user_name,
            })
            return dashboard
        except LinkInputValidationError:
            raise
        except (AccountLinkError, SteamAccountRemoveChainedError) as exc:
            return _account_link_failure(exc)
        except ApiError as exc:
            failure = _transition_api_failure(exc)
            log.warning(
                "Transition chain API failure for account '%s': %s",
                session.name,
                failure["error_code"] if failure else "TRANSITION_API_FAILED",
            )
            log.debug(
                "Transition chain API failure for account '%s'",
                session.name,
                exc_info=True,
            )
            return failure or _transition_failure(
                "TRANSITION_API_FAILED",
                "The transition API request failed; account-link state was preserved.",
            )
        except RuntimeError as exc:
            log.error(
                "Transition chain persistence/login failure for account '%s'",
                session.name,
            )
            log.debug(
                "Transition chain persistence/login failure for account '%s'",
                session.name,
                exc_info=True,
            )
            return _transition_failure(
                "TRANSITION_LOGIN_FAILED",
                str(exc),
            )
        except Exception:
            log.error(
                "Transition chain failed for account '%s'",
                session.name,
            )
            log.debug(
                "Transition chain failed for account '%s'",
                session.name,
                exc_info=True,
            )
            return _transition_failure(
                "TRANSITION_CHAIN_FAILED",
                "Transition linking failed before login could complete; account-link state was preserved.",
            )

    def leave_session(self):
        session = self.session
        session.reset_runtime()
        session.pending_game_auth_config = {}
        session.pending_transition_config = {}
        return {"success": True}

    def preflight_steam_unbind(self, req):
        """Diagnostic only: prove recovery without changing the Steam link."""
        from uma_api.account_link import AccountLinkError, LinkInputValidationError
        from uma_api.errors import SteamAccountRemoveChainedError

        cfg, failure = _validate_steam_unbind_target(self.session, req)
        if failure:
            return failure
        try:
            preview = _preflight_steam_recovery(
                self.session,
                cfg,
                req.link_password,
            )
            if preview is None:
                return _steam_unbind_failure(
                    "RECOVERY_PREFLIGHT_ACCOUNT_UNAVAILABLE",
                    "No different local account with valid game auth and a usable Steam login was available to prove the recovery path.",
                )
            return {
                "success": True,
                "state": "verified",
                "recovery_verified": "verified",
                **preview,
            }
        except LinkInputValidationError:
            raise
        except (AccountLinkError, SteamAccountRemoveChainedError) as exc:
            return _steam_preflight_account_link_failure(exc)
        except Exception:
            log.exception(
                "Steam unbind recovery preflight failed for account '%s'",
                self.session.name,
            )
            return _steam_unbind_failure(
                "RECOVERY_PREFLIGHT_FAILED",
                "The Trainer ID and link-password recovery path could not be proven.",
            )

    def steam_unbind(self, req):
        from uma_api import account_link
        from uma_api.account_link import AccountLinkError, LinkInputValidationError
        from uma_api.errors import SteamAccountRemoveChainedError

        cfg, failure = _validate_steam_unbind_target(self.session, req)
        if failure:
            return failure

        preview = None
        recovery_verified = "not_checked"
        if req.link_password is not None:
            try:
                preview = _preflight_steam_recovery(
                    self.session,
                    cfg,
                    req.link_password,
                )
                if preview is None:
                    return _steam_unbind_failure(
                        "RECOVERY_PREFLIGHT_ACCOUNT_UNAVAILABLE",
                        "No different local account with valid game auth and a usable Steam login was available to prove the recovery path.",
                    )
            except LinkInputValidationError:
                raise
            except (AccountLinkError, SteamAccountRemoveChainedError) as exc:
                return _steam_preflight_account_link_failure(exc)
            except Exception:
                log.exception(
                    "Steam unbind recovery preflight failed for account '%s'",
                    self.session.name,
                )
                return _steam_unbind_failure(
                    "RECOVERY_PREFLIGHT_FAILED",
                    "The Trainer ID and link-password recovery path could not be proven.",
                )
            recovery_verified = "verified"

        target_client = _target_steam_client(self.session, cfg)
        if target_client is None:
            return _steam_unbind_failure(
                "TARGET_STEAM_SESSION_UNAVAILABLE",
                "The target account could not be authenticated with Steam for the unbind request.",
            )

        try:
            # Intentionally one attempt: account-link failures, including 709,
            # are terminal here and must never enter a retry ladder.
            account_link.steam_chain_disconnect(target_client)
        except (AccountLinkError, SteamAccountRemoveChainedError) as exc:
            return _account_link_failure(exc)
        except Exception:
            log.exception("Steam unbind failed for account '%s'", self.session.name)
            return _steam_unbind_failure(
                "STEAM_UNBIND_FAILED",
                "The Steam link could not be removed.",
            )

        log.warning("Steam link removed for account '%s'", self.session.name)
        steam_unbound_at = int(time.time())
        updated_cfg = dict(cfg)
        # This is advisory history for the UI. A rebind in the game client can
        # restore the Steam identity, so login always verifies the live state.
        updated_cfg["steam_unbound_at"] = steam_unbound_at
        if account_store.save_account_config(self.session.name, updated_cfg) is not True:
            log.error(
                "Steam unbind succeeded but its marker could not be saved for account '%s'",
                self.session.name,
            )
            return _steam_unbind_failure(
                "STEAM_UNBIND_STATE_SAVE_FAILED",
                "The Steam link was removed, but the local unbound timestamp could not be saved.",
            )

        result = {
            "success": True,
            "state": "unbound",
            # This is an optional diagnostic status, not a safety guarantee.
            "recovery_verified": recovery_verified,
            "steam_unbound_at": steam_unbound_at,
        }
        if preview:
            result.update(preview)
        else:
            result["detail"] = (
                "Steam link removed. The Trainer ID and link-password recovery path was not checked."
            )
        return result
