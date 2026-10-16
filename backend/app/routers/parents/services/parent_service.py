from backend.app.runner_state import require_idle
import backend.app.domain.account_store as account_store
from backend.app.domain.parent_roster import build_parents
from uma_api import game_service
from uma_api.session import Session


class ParentService:
    def __init__(self, session: Session):
        self.session = session

    def refresh(self):
        session = self.session
        if not session.client:
            return {"success": False, "detail": "Not logged in"}

        busy = require_idle(session)
        if busy:
            return busy

        if session.dashboard_data is None:
            return {
                "success": False,
                "detail": "Session data unavailable; re-enter the account",
            }

        try:
            response = game_service.read_info(session)
            data = (response or {}).get("data")
            if not isinstance(data, dict) or not isinstance(
                data.get("trained_chara"), list
            ):
                raise ValueError(
                    "Game response did not include a valid trained-character roster"
                )

            game_service.refresh_cached_account_state(session, data)
            parents = build_parents(session, data)
        except Exception as error:
            return {"success": False, "detail": f"Refresh failed: {error}"}

        session.dashboard_data["parents"] = parents
        removed_veteran_ids = self._reconcile_selection(parents)
        return {
            "success": True,
            "parents": parents,
            "selection": session.selection,
            "removed_veteran_ids": removed_veteran_ids,
        }

    def _reconcile_selection(self, parents: list[dict]) -> list:
        session = self.session
        selection_is_valid = isinstance(session.selection, dict)
        selection = session.selection if selection_is_valid else {}
        raw_veterans = selection.get("veterans")
        veterans = raw_veterans if isinstance(raw_veterans, list) else []
        selection_changed = not selection_is_valid or not isinstance(raw_veterans, list)

        roster_ids = {
            str(parent.get("instance_id"))
            for parent in parents
            if parent.get("instance_id") is not None
        }
        kept = []
        removed = []
        for veteran in veterans:
            instance_id = veteran.get("instance_id") if isinstance(veteran, dict) else None
            if instance_id is not None and str(instance_id) in roster_ids:
                kept.append(veteran)
            else:
                removed.append(instance_id)

        if selection_changed or len(kept) != len(veterans):
            next_selection = dict(selection)
            next_selection["veterans"] = kept
            session.selection = next_selection
            account_store.save_selection(session.name, next_selection)

        return removed

    def delete(self, instance_ids: list, unlock_locked: bool = False):
        session = self.session
        if not session.client:
            return {"success": False, "detail": "Not logged in"}

        busy = require_idle(session)
        if busy:
            return busy

        parents = (session.dashboard_data or {}).get("parents") or []

        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        owned = {
            pid for pid in (as_int(p.get("instance_id")) for p in parents)
            if pid is not None
        }
        locked_map = {
            as_int(p.get("instance_id")): bool(int(p.get("is_locked") or 0))
            for p in parents
            if as_int(p.get("instance_id")) is not None
        }
        requested = {pid for pid in (as_int(i) for i in instance_ids) if pid is not None}
        to_delete = sorted(owned & requested)
        if not to_delete:
            return {"success": False, "detail": "No matching owned veterans to delete"}

        # Locked (memo) veterans cannot be removed. Surface them so the UI can warn,
        # and only unlock when the user explicitly confirmed (unlock_locked).
        locked = [pid for pid in to_delete if locked_map.get(pid)]
        if locked and not unlock_locked:
            return {"success": False, "detail": "locked", "locked": locked}
        unlock_ids = locked if unlock_locked else []

        try:
            game_service.remove_trained_chara(session, to_delete, unlock_ids=unlock_ids)
        except Exception as e:
            return {"success": False, "detail": f"Delete failed: {e}"}

        deleted = set(to_delete)
        if session.dashboard_data is not None:
            session.dashboard_data["parents"] = [
                p for p in parents if as_int(p.get("instance_id")) not in deleted
            ]
        for tcid in deleted:
            session.parent_cards.pop(tcid, None)
            session.parent_rank_points.pop(tcid, None)

        return {
            "success": True,
            "deleted": sorted(deleted),
            "parents": (session.dashboard_data or {}).get("parents") or [],
        }

    def get_auto_delete_config(self):
        return {"success": True, "config": account_store.load_auto_delete_config(self.session.name)}

    def set_auto_delete_config(self, raw_cfg: dict):
        cfg = account_store.normalize_auto_delete_config(raw_cfg)
        account_store.save_auto_delete_config(self.session.name, cfg)
        if self.session.runner:
            self.session.runner.auto_delete_trained = cfg
        return {"success": True, "config": cfg}
