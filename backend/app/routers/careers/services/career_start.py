import logging

from typing import TYPE_CHECKING

from backend.app.runner_state import require_idle
from backend.app.services import game_login
import backend.app.domain.account_status as account_status
import backend.app.domain.career_selection as career_selection
import backend.app.domain.master_data_preflight as master_data_preflight
import backend.app.domain.rank_point as rank_point
from uma_api import game_service

from ..schemas.career import StartCareerRequest

if TYPE_CHECKING:
    # Type-only base: declares the CareerService state / sibling-mixin handlers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class CareerStartMixin:` would produce.
    from .service_state import CareerServiceState
    _HostState = CareerServiceState
else:
    _HostState = object


log = logging.getLogger(__name__)

# Signals the TP top-up ladder hands back — exactly the `break` / `continue`
# the inline attempt loop used; ``None`` means "fall through" (back off, retry).
_BREAK = "break"
_NEXT_ATTEMPT = "next-attempt"


def _validate_start_preconditions(client, session, req):
    if not client:
        return {"success": False, "detail": "Not logged in"}

    if session.account and session.account.get("career") and session.account["career"].get("active"):
        return {"success": False, "detail": "Cannot start a new career while another is active"}

    if not req.friend_viewer_id or not req.friend_card_id:
        return {"success": False, "detail": "Friend support card is required"}

    return None


def _configured_running_style_for_start(req, session):
    configured_running_style = 0
    if hasattr(req, "preset_name"):
        runner_preset = getattr(session, "last_preset", None)
        if isinstance(runner_preset, dict):
            configured_running_style = runner_preset.get("running_style", 0)
    return configured_running_style


def _master_data_preflight_failure(session, scenario_id):
    detail = master_data_preflight.career_master_data_error(
        session.base_dir,
        session.state_root,
        scenario_id,
    )
    if detail is None:
        return None
    log.warning(detail)
    return {"success": False, "detail": detail}


def _start_use_tp(req, client):
    """TP the career-start call must pay.

    Start cost follows the active single-mode TP campaign; boost costs 2x that
    amount. ``req.is_boost`` is read at call time so a 2509 boost-downgrade
    retry re-prices the start.
    """
    base = 30
    try:
        from uma_data import tp_cost as career_tp

        # Scenario fallback preserved from the old UmaClient method: an
        # explicit request scenario wins, else the client's active one.
        sid = req.scenario_id
        if sid is None:
            sid = getattr(client, "current_scenario_id", None)
        base = int(career_tp.single_mode_career_start_tp(
            scenario_id=sid,
            server_time=getattr(client, "last_servertime", 0),
        ))
    except Exception:
        base = 30
    if getattr(req, "is_boost", 0):
        return base * 2
    return base


def _tp_bottle_count(session, client):
    value = session.start_state.get(
        'tp_bottle_count',
        (getattr(client, "item_map", {}) or {}).get(account_status.TP_BOTTLE_ITEM_ID, 0),
    )
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _refresh_start_tp_info(session, client, tp_info):
    """Pull a fresh ``read_info`` into the caches and return the live ``tp_info``.

    Raises whatever the transport raises -- every caller already sits inside a
    ``try`` that decides what a failure means there. The caller derives
    ``current_tp`` itself so a malformed payload leaves exactly the same
    partially-updated state as the inline code this replaced.
    """
    res = game_service.read_info(session)
    data = (res or {}).get('data', {})
    game_service.refresh_cached_account_state(session, data)
    account_status.update_start_state(session, data)
    tp_info = session.start_state.get('tp_info') or getattr(client, 'tp_info', {}) or tp_info
    session.start_state['tp_info'] = tp_info
    return tp_info


class _TpRecovery:
    """The 5-attempt TP top-up ladder for one career start.

    Owns the state the inline loop carried in locals: the live
    ``current_tp``/``tp_info`` pair every step re-reads and re-publishes into
    ``session.start_state``, the ``recovery_error`` the caller reports, and the
    one-shot ``relogged_on_201`` latch. Collaborator imports stay call-time (as
    inline) so the monkeypatch seams keep biting.
    """

    def __init__(self, session, client, required_tp, current_tp, tp_info):
        self.session = session
        self.client = client
        self.required_tp = required_tp
        self.current_tp = current_tp
        self.tp_info = tp_info
        self.recovery_error = ""
        self.relogged_on_201 = False

    def _prime_live_tp(self):
        # Refresh live TP + jewel balance so recovery decisions/payment use fresh
        # numbers (the cached state from login can be stale).
        try:
            self.tp_info = _refresh_start_tp_info(self.session, self.client, self.tp_info)
            self.current_tp = int(self.tp_info.get('current_tp') or 0)
        except Exception:
            pass

    def _spend_tp_bottles(self, needed, bottles):
        """Pay with free bottles and keep the client-side bottle count honest."""
        session = self.session
        use_num = min(needed, bottles)
        log.info(f"[TP] auto-recover: have {self.current_tp}, need {self.required_tp} -> TP bottle x{use_num} ({bottles} owned)")
        game_service.use_recovery_item(session, account_status.TP_BOTTLE_ITEM_ID, use_num)
        client_items = getattr(self.client, "item_map", {}) or {}
        if account_status.TP_BOTTLE_ITEM_ID in client_items:
            try:
                session.start_state['tp_bottle_count'] = max(int(client_items.get(account_status.TP_BOTTLE_ITEM_ID) or 0), 0)
            except (TypeError, ValueError):
                session.start_state['tp_bottle_count'] = max(bottles - use_num, 0)
        else:
            session.start_state['tp_bottle_count'] = max(bottles - use_num, 0)
        account_status.set_cached_user_item_count(session, account_status.TP_BOTTLE_ITEM_ID, session.start_state['tp_bottle_count'])

    def _pay_once(self):
        """One top-up round: bottles when we have them, carats otherwise."""
        needed = ((self.required_tp - self.current_tp) + 29) // 30
        # Prefer free TP bottles (item 32, +30 TP each) before spending
        # carats. Never auto-spend the rare Valentine chocolates that share
        # the +30 TP effect -- only item 32. Carats are the fallback when
        # no bottles are left.
        bottles = _tp_bottle_count(self.session, self.client)
        if bottles >= 1 and hasattr(self.client, "use_recovery_item"):
            self._spend_tp_bottles(needed, bottles)
        else:
            log.info(f"[TP] auto-recover: have {self.current_tp}, need {self.required_tp} -> recovery_tp({needed}) (carat)")
            game_service.recovery_tp(self.session, needed)
        self.tp_info = self.client.tp_info
        self.session.start_state['tp_info'] = self.tp_info
        self.current_tp = int(self.tp_info.get('current_tp') or 0)

    def _relogin_after_201(self):
        """One-shot session refresh; returns the ``break``/``continue`` signal."""
        if self.relogged_on_201 or not hasattr(self.client, "login"):
            return _BREAK
        self.relogged_on_201 = True
        try:
            log.warning("[RECOVER] TP recovery hit 201; relogging in to refresh session")
            game_login.login_with_master_refresh(self.session)
            self.tp_info = _refresh_start_tp_info(self.session, self.client, self.tp_info)
            self.current_tp = int(self.tp_info.get('current_tp') or 0)
            self.recovery_error = ""
            return _NEXT_ATTEMPT
        except Exception as relogin_err:
            self.recovery_error = str(relogin_err)
            return _BREAK

    def _refresh_after_213(self):
        """213 = stale client-side item count; pull the live index back in."""
        try:
            res = game_service.load_index_live(self.session)
            data = res.get("data", {})
            game_service.refresh_cached_account_state(self.session, data)
            account_status.update_start_state(self.session, data)
        except Exception:
            pass

    def _handle_payment_error(self, exc):
        """Classify a failed top-up. Returns a signal, or ``None`` to back off."""
        from uma_api import errors as uma_errors

        self.recovery_error = str(exc)
        # 201 = dead session/expired Steam ticket. Hammering recovery_tp
        # cannot fix it -- relogin once (login() mints a fresh ticket from
        # the saved refresh token), refresh TP, and bail if it persists.
        if uma_errors.api_error_result_code(exc) == 201:
            return self._relogin_after_201()
        if uma_errors.api_error_result_code(exc) == 213:
            self._refresh_after_213()
        return None

    def run(self):
        import career_bot.delay as delay

        if not (self.required_tp and self.current_tp < self.required_tp):
            return self.current_tp, self.tp_info, self.recovery_error

        self._prime_live_tp()
        for attempt in range(5):
            if self.current_tp >= self.required_tp:
                break
            try:
                self._pay_once()
            except Exception as e:
                outcome = self._handle_payment_error(e)
                if outcome == _BREAK:
                    break
                if outcome == _NEXT_ATTEMPT:
                    continue
                delay.backoff_sleep(attempt, base=1.0, cap=6.0)

        return self.current_tp, self.tp_info, self.recovery_error


def _recover_tp_for_start(session, client, required_tp, current_tp, tp_info):
    """Top the account's TP up to ``required_tp`` before a career start.

    Prefers free TP bottles over carats, relogs once on a 201 (dead session) and
    refreshes the live index on a 213 (stale client-side item count). Returns
    ``(current_tp, tp_info, recovery_error)``; ``recovery_error`` is the last
    failure message, or ``""`` when nothing failed.
    """
    return _TpRecovery(session, client, required_tp, current_tp, tp_info).run()


def _resolve_rental_for_start(session, req):
    """Pick the friend parent to borrow for this start.

    Returns ``(rental_viewer_id, rental_trained_chara_id)`` -- ``(0, 0)`` when no
    preset rental was requested, the quota is spent, or anything on the way
    (pre_single_mode / load index / decision) fails.
    """
    import career_bot.delay as delay

    rental_viewer_id = 0
    rental_trained_chara_id = 0
    try:
        pre = game_service.pre_single_mode(session, [req.friend_viewer_id] if req.friend_viewer_id else [])
        delay.dna_sleep(0.5, 1.5)
        preset_vid = int(getattr(req, "rental_friend_viewer_id", 0) or 0)
        if preset_vid:
            pre_data = pre.get('data', {}) if isinstance(pre, dict) else {}
            friends, _, _ = career_selection.normalize_friend_cards(pre_data, session=session)
            quota = {"used": 0, "max": career_selection.RENTAL_MAX_DEFAULT, "remaining": career_selection.RENTAL_MAX_DEFAULT}
            try:
                load_res = game_service.load_index_live(session)
                quota = career_selection.read_rental_quota(load_res.get('data', {}))
            except Exception:
                pass
            rental_viewer_id, rental_trained_chara_id = career_selection.decide_rental(preset_vid, friends, quota)
            if rental_viewer_id:
                log.info(f"Borrowing friend parent: viewer={rental_viewer_id} ({quota['used']}/{quota['max']} used)")
            else:
                log.warning(f"Friend-parent rental skipped (fallback): quota {quota['used']}/{quota['max']}")
    except Exception:
        pass
    return rental_viewer_id, rental_trained_chara_id


class _StartAttempts:
    """The career-start attempt ladder for one already-prepared request.

    Owns the state the nested closures used to capture: the request object
    (whose ``is_boost`` a 2509 downgrade clears in place), the resolved
    TP/money/running-style payload, and ``last_start_attempt`` -- the record of
    the most recent ``start_career`` call, which the 102 rank-point probe
    replays with candidate values.
    """

    def __init__(self, session, client, req, tp_info, current_money, configured_running_style):
        self.session = session
        self.client = client
        self.req = req
        self.tp_info = tp_info
        self.current_money = current_money
        self.configured_running_style = configured_running_style
        self.last_start_attempt = {}

    def rank_point_components(self, rvid, rtcid):
        rental_parent_2 = (rvid, rtcid) if rvid else None
        return rank_point.selected_succession_rank_point_components(
            self.session, self.req, rental_parent_2=rental_parent_2
        )

    def do_start(self, rvid, rtcid, succession_rank_point=None, components=None):
        # Option 1: a borrowed friend parent REPLACES the user's Parent 2 slot.
        # When renting, send parent_id_2=0; on fallback/retry (rvid=0) the user's
        # own Parent 2 is sent as normal.
        req = self.req
        if components is None:
            components = self.rank_point_components(rvid, rtcid)
        computed = int(components["computed"])
        sent_rank_point = (
            computed if succession_rank_point is None else int(succession_rank_point)
        )
        self.last_start_attempt.clear()
        self.last_start_attempt.update({
            "rental_viewer_id": int(rvid or 0),
            "rental_trained_chara_id": int(rtcid or 0),
            "components": components,
            "computed": computed,
            "sent": sent_rank_point,
        })
        p2 = 0 if rvid else req.parent_id_2
        return game_service.start_career(
            self.session,
            card_id=req.card_id,
            support_card_ids=req.support_card_ids,
            friend_viewer_id=req.friend_viewer_id,
            friend_card_id=req.friend_card_id,
            parent_id_1=req.parent_id_1,
            parent_id_2=p2,
            scenario_id=req.scenario_id,
            deck_id=req.deck_id,
            use_tp=_start_use_tp(req, self.client),
            tp_info=self.tp_info,
            current_money=self.current_money,
            succession_rank_point=sent_rank_point,
            rental_viewer_id=rvid,
            rental_trained_chara_id=rtcid,
            difficulty_id=req.difficulty_id,
            difficulty=req.difficulty,
            is_boost=req.is_boost,
            boost_story_event_id=req.boost_story_event_id,
            running_style=self.configured_running_style
        )

    def refresh_session_after_start_error(self, reason):
        if not hasattr(self.client, "login"):
            return False
        try:
            log.warning(f"[RECOVER] refreshing session after start error ({reason})")
            res = game_login.login_with_master_refresh(self.session)
            data = (res or {}).get("data", {})
            game_service.refresh_cached_account_state(self.session, data)
            account_status.update_start_state(self.session, data)
            return True
        except Exception as refresh_err:
            log.warning(f"[RECOVER] session refresh failed: {refresh_err}")
            return False

    def load_existing_career_after_102(self, observed_codes="102"):
        from uma_api import errors as uma_errors

        # 102 can mean an existing career, but only load if fallback start paths fail too.
        # observed_codes is report-only: the rental ladder also lands here on
        # 501/201-only runs (see run()), and the operator-facing diagnosis must
        # name the codes that actually happened, not claim 102.
        log.warning(f"[RECOVER] start hit {observed_codes}; checking for an existing career to resume")
        self.refresh_session_after_start_error("career-load")
        resumed = None
        confirmed_no_career = False
        try:
            res = game_service.load_career(self.session)
            if (res.get("data") or {}).get("chara_info"):
                resumed = res
        except Exception as load_err:
            log.warning(f"[RECOVER] load_career failed: {load_err}")
            confirmed_no_career = uma_errors.api_error_result_code(load_err) == 102
        if resumed is None:
            return None, confirmed_no_career
        log.info("[RECOVER] resumed existing career")
        return resumed, False

    def recover_existing_or_probe(self, probe_attempt, observed_codes="102"):
        resumed, confirmed_no_career = self.load_existing_career_after_102(observed_codes)
        if resumed is not None:
            return resumed
        if not confirmed_no_career or not probe_attempt:
            return None
        components = probe_attempt["components"]
        rvid = probe_attempt["rental_viewer_id"]
        rtcid = probe_attempt["rental_trained_chara_id"]
        return rank_point.probe_succession_rank_point(
            self.session,
            self.req,
            components,
            lambda candidate: self.do_start(
                rvid,
                rtcid,
                succession_rank_point=candidate,
                components=components,
            ),
        )

    def disable_event_boost(self):
        self.req.is_boost = 0
        event_selection = (self.session.selection or {}).get("event")
        if isinstance(event_selection, dict):
            event_selection["boost"] = False

    def _observed_codes(self, start_err, fallback_err):
        """The codes that actually happened, in order, deduped.

        Report the codes that actually happened: the rental branch is also
        reachable on a 501/201-only run (fallback_err == 201), where the old
        hardcoded "error 102" diagnosis lied to the operator.
        """
        from uma_api import errors as uma_errors

        return "/".join(
            str(code) for code in dict.fromkeys((
                uma_errors.api_error_result_code(start_err),
                uma_errors.api_error_result_code(fallback_err),
            )) if code
        ) or "102"

    def _recover_plain_102(self):
        """Non-rental 102: resume the existing career, else probe the rank point."""
        probe_attempt = dict(self.last_start_attempt)
        result = self.recover_existing_or_probe(probe_attempt)
        if result is None:
            return {"success": False, "detail":
                    "Career start blocked (error 102) and no resumable career was found. "
                    "In the game, return to the main menu, then use the dashboard Stop/Logout "
                    "and start again."}
        return {"success": True, "result": result}

    def _recover_no_rental_fallback(self, start_err, fallback_err):
        """The no-rental fallback's own ladder: 2509 downgrade, 201 refresh, then
        career-load / rank-point-probe recovery.

        Returns ``None`` for the code pairs the ladder does not handle, so the
        caller re-raises the live exception exactly where the inline ``raise``
        stood (bare, still inside its own ``except``).
        """
        from uma_api import errors as uma_errors

        if uma_errors.api_error_result_code(fallback_err) == 2509 and getattr(self.req, "is_boost", 0):
            log.warning("[EVENT] boost retry rejected with 2509; retrying same event without boost")
            self.disable_event_boost()
            try:
                result = self.do_start(0, 0)
            except Exception as retry_err:
                fallback_err = retry_err
            else:
                return {"success": True, "result": result}
        if uma_errors.api_error_result_code(fallback_err) == 201:
            self.refresh_session_after_start_error("fallback-201")
            try:
                result = self.do_start(0, 0)
            except Exception as retry_err:
                fallback_err = retry_err
            else:
                return {"success": True, "result": result}
        if uma_errors.api_error_result_code(start_err) != 102 and uma_errors.api_error_result_code(fallback_err) not in (102, 201):
            return None
        probe_attempt = (
            dict(self.last_start_attempt)
            if uma_errors.api_error_result_code(fallback_err) == 102 else None
        )
        observed_codes = self._observed_codes(start_err, fallback_err)
        result = self.recover_existing_or_probe(probe_attempt, observed_codes)
        if result is None:
            return {"success": False, "detail":
                    f"Career start blocked (error {observed_codes}) and no resumable career was found. "
                    "In the game, return to the main menu, then use the dashboard Stop/Logout "
                    "and start again."}
        return {"success": True, "result": result}

    def _recover_rental_start(self, start_err, rental_viewer_id, rental_trained_chara_id):
        """The rental ladder: keep the borrow when the session was merely stale,
        else drop back to the user's own Parent 2 and its fallback ladder."""
        from uma_api import errors as uma_errors

        # In a loop, the new career starts on the SESSION left by the just-finished
        # one. That session goes stale -- a rental start then 501s/201s even though
        # read_info still works -- whereas the first career (fresh login) borrows
        # fine. So refresh the session and retry WITH the rental before giving the
        # borrow up (the whole point of renting). Gated to the stale-session codes.
        if uma_errors.api_error_result_code(start_err) in (501, 201):
            log.warning(f"Start failed with rental ({type(start_err).__name__}); refreshing session and retrying WITH rental")
            if self.refresh_session_after_start_error("rental-retry"):
                try:
                    result = self.do_start(rental_viewer_id, rental_trained_chara_id)
                    log.info("[RECOVER] rental start succeeded after session refresh")
                    return {"success": True, "result": result}
                except Exception as rental_retry_err:
                    log.warning(f"Rental still failing after refresh ({type(rental_retry_err).__name__}); starting without rental")
                    start_err = rental_retry_err
        # Rental-specific failure: retry once without the borrowed parent.
        if uma_errors.api_error_result_code(start_err) == 102:
            log.warning("[RECOVER] start hit 102 with rental; retrying without rental before career-load recovery")
        else:
            log.warning(f"Start failed with rental ({type(start_err).__name__}); retrying without rental")
        if uma_errors.api_error_result_code(start_err) == 102:
            self.refresh_session_after_start_error("rental-102")
        try:
            result = self.do_start(0, 0)
        except Exception as fallback_err:
            recovered = self._recover_no_rental_fallback(start_err, fallback_err)
            if recovered is None:
                raise
            return recovered
        return {"success": True, "result": result}

    def run(self, rental_viewer_id, rental_trained_chara_id, initial_components):
        """Start the career, walking the 2509 / rental / 102 / 201 recovery ladder.

        Returns the same envelopes the caller returns verbatim; re-raises the
        underlying error for codes the ladder does not handle.
        """
        from uma_api import errors as uma_errors

        req = self.req
        try:
            result = self.do_start(
                rental_viewer_id,
                rental_trained_chara_id,
                components=initial_components,
            )
        except Exception as start_err:
            if uma_errors.api_error_result_code(start_err) == 2509 and getattr(req, "is_boost", 0):
                log.warning("[EVENT] boost start rejected with 2509; retrying same event without boost")
                self.disable_event_boost()
                result = self.do_start(rental_viewer_id, rental_trained_chara_id)
            elif rental_viewer_id:
                return self._recover_rental_start(
                    start_err, rental_viewer_id, rental_trained_chara_id
                )
            elif uma_errors.api_error_result_code(start_err) == 102:
                return self._recover_plain_102()
            else:
                raise
        return {"success": True, "result": result}


class CareerStartMixin(_HostState):
    def start_career_from_request(self, req):
        session = self.session
        client = session.client
        precondition_error = _validate_start_preconditions(client, session, req)
        if precondition_error:
            return precondition_error

        selection_error = career_selection.validate_start_selection(session, req)
        if selection_error:
            return {"success": False, "detail": selection_error}

        master_data_error = _master_data_preflight_failure(session, req.scenario_id)
        if master_data_error:
            return master_data_error

        try:
            res = game_service.read_info(session)
            data = res.get('data', {})
            game_service.refresh_cached_account_state(session, data)
            account_status.update_start_state(session, data)
            if session.account:
                session.account = account_status.get_account_status(session, data)
                if session.dashboard_data:
                    session.dashboard_data["account"] = session.account
        except Exception:
            pass

        if not session.start_state.get('tp_info'):
            return {"success": False, "detail": "Missing live TP state; login again before starting career"}
        if 'current_money' not in session.start_state:
            return {"success": False, "detail": "Missing live item state; login again before starting career"}

        # Event difficulty mode: read the runtime selection (session.selection["event"]),
        # map to (difficulty_id, difficulty, is_boost), and set the request fields that
        # _StartAttempts.do_start forwards to start_career. No event -> stays (0, 0, 0)
        # = normal career.
        # Resolved BEFORE TP recovery so a boosted run can target the higher TP cost.
        try:
            ev = (session.selection or {}).get("event") or {}
            if ev.get("enabled"):
                load_res = game_service.load_index_live(session)
                detect = career_selection.detect_event_difficulty(
                    load_res.get('data', {}),
                    (load_res.get('data_headers') or {}).get('servertime'),
                )
                did, diff, boost = career_selection.event_difficulty_payload(
                    True, ev.get("level", 1), ev.get("boost", False), detect)
                req.difficulty_id = did
                req.difficulty = diff
                req.is_boost = boost
                if did:
                    log.info(f"[EVENT] difficulty mode: id={did} difficulty={diff} boost={boost}")
                else:
                    log.info("[EVENT] enabled but no active event detected -> normal career")
        except Exception as exc:
            log.warning(f"[EVENT] detection failed ({type(exc).__name__}); running normal career")

        tp_info = session.start_state['tp_info']
        current_tp = int(tp_info.get('current_tp') or 0)
        required_tp = _start_use_tp(req, client)
        current_tp, tp_info, recovery_error = _recover_tp_for_start(
            session, client, required_tp, current_tp, tp_info
        )

        if required_tp and current_tp < required_tp:
            detail = f"Not enough TP: {current_tp}/{required_tp}"
            if recovery_error:
                detail += f" (auto-recovery failed: {recovery_error})"
            return {"success": False, "detail": detail}
        current_money = session.start_state['current_money']
        rental_viewer_id, rental_trained_chara_id = _resolve_rental_for_start(session, req)

        attempts = _StartAttempts(
            session,
            client,
            req,
            tp_info,
            current_money,
            _configured_running_style_for_start(req, session),
        )

        initial_components = attempts.rank_point_components(
            rental_viewer_id, rental_trained_chara_id
        )
        succession_rank_point = initial_components["computed"]
        log.info(
            f"[START] card={req.card_id} deck={req.deck_id} scenario={req.scenario_id} "
            f"p1={req.parent_id_1} p2={req.parent_id_2} rental={rental_viewer_id}:{rental_trained_chara_id} "
            f"rank_point={succession_rank_point} money={current_money} tp={current_tp}/{required_tp}"
        )

        return attempts.run(
            rental_viewer_id, rental_trained_chara_id, initial_components
        )

    async def start(self, req: StartCareerRequest):
        session = self.session
        busy = require_idle(session)
        if busy:
            return busy
        try:
            started = self.start_career_from_request(req)
            if not started.get("success"):
                return started
            result = account_status.unwrap_single_mode_start_common(started["result"])
            account, chara_info = account_status.apply_career_result(session, result)
            return {"success": True, "account": account, "chara_info": chara_info}
        except Exception as e:
            return {"success": False, "detail": str(e)}
