from backend.app.services import game_login
import backend.app.domain.account_status as account_status
from uma_api import game_service
from uma_api.session import Session


class SessionService:
    def __init__(self, session: Session):
        self.session = session

    def status(self):
        session = self.session
        if not session.client or not session.dashboard_data:
            return {"success": False}

        data = dict(session.dashboard_data)
        if session.account:
            data["account"] = session.account
        data["selection"] = session.selection
        data["success"] = True
        return data

    def refresh(self):
        session = self.session
        # Re-pull live state from the game so changes made directly in the game
        # (e.g. a career started in-game) show up without a full logout/login.
        if not session.client:
            return {"success": False, "detail": "Not logged in"}
        if session.runner.snapshot().get("running") or session.loop_active():
            return {"success": False, "detail": "Career runner active; stop it before refreshing"}

        try:
            # Re-establish the session (start_session + load/index + read_info, with
            # built-in retries) rather than a bare load/index, which can 201 on a
            # stale session.
            res = game_login.login_with_master_refresh(session)
            d = (res or {}).get('data', {})
            game_service.refresh_cached_account_state(session, d)
            account_status.update_start_state(session, d)
            career_data = None
            if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
                try:
                    career_res = game_service.load_career(session)
                    career_data = career_res.get('data')
                except Exception:
                    pass
            account = account_status.get_account_status(session, d, career_data)
            session.account = account
            if session.dashboard_data:
                session.dashboard_data["account"] = account
            return {"success": True, "account": account}
        except Exception as e:
            return {"success": False, "detail": str(e)}
