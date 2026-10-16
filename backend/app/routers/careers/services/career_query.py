from typing import TYPE_CHECKING

from backend.app.runner_state import require_idle
from uma_api import game_service
from backend.app import context
import backend.app.domain.account_status as account_status
import backend.app.domain.career_selection as career_selection


if TYPE_CHECKING:
    # Type-only base: declares the CareerService state / sibling-mixin handlers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class CareerQueryMixin:` would produce.
    from .service_state import CareerServiceState
    _HostState = CareerServiceState
else:
    _HostState = object


class CareerQueryMixin(_HostState):
    def event_info(self):
        session = self.session
        if not session.client:
            return {"success": False, "detail": "Not logged in"}
        # A career run owns the live game session. A mid-run load/index here returns API
        # error 201 AND desyncs the runner's SID (corrupting the running career) -- which is
        # exactly what happened when opening an account that was already running. While the
        # runner is active, skip load/index and serve the last cached event-info instead.
        if session.runner.snapshot().get("running") or session.loop_active():
            if session.event_info_cache:
                return dict(session.event_info_cache)
            record = game_service.load_index_cached(
                context.state_root,
                session.name,
            )
            data = (record or {}).get("data")
            if isinstance(data, dict):
                info = {"success": True, **career_selection.detect_event_difficulty(
                    data,
                    ((record.get("data_headers") or {}) if isinstance(record, dict) else {}).get("servertime"),
                )}
                session.event_info_cache = dict(info)
                return info
            return {"success": True, "available": False, "difficulty_id": 0, "max_level": 0}
        try:
            res = game_service.load_index_live(session)
            info = {"success": True, **career_selection.detect_event_difficulty(
                res.get('data', {}),
                (res.get('data_headers') or {}).get('servertime'),
            )}
            session.event_info_cache = dict(info)
            return info
        except Exception as e:
            return {"success": False, "detail": str(e),
                    "available": False, "difficulty_id": 0, "max_level": 0}

    def friends(self, exclude_viewer_ids):
        session = self.session
        if not session.client:
            return {"success": False, "detail": "Not logged in"}

        if session.runner.snapshot().get("running") or session.loop_active():
            if not exclude_viewer_ids and session.dashboard_data is not None and "friends" in session.dashboard_data:
                return {
                    "success": True,
                    "friends": session.dashboard_data["friends"],
                    "exclude_viewer_ids": session.dashboard_data.get("friend_exclude_ids", []),
                    "source": "cache",
                    "rental_quota": session.dashboard_data.get("rental_quota", {"used": 0, "max": career_selection.RENTAL_MAX_DEFAULT, "remaining": career_selection.RENTAL_MAX_DEFAULT})
                }
            return {
                "success": True,
                "friends": [],
                "exclude_viewer_ids": [],
                "source": "Active Career (Skip)",
                "rental_quota": {"used": 0, "max": career_selection.RENTAL_MAX_DEFAULT, "remaining": career_selection.RENTAL_MAX_DEFAULT}
            }

        if not exclude_viewer_ids and session.dashboard_data is not None and "friends" in session.dashboard_data:
            return {
                "success": True,
                "friends": session.dashboard_data["friends"],
                "exclude_viewer_ids": session.dashboard_data.get("friend_exclude_ids", []),
                "source": "cache",
                "rental_quota": session.dashboard_data.get("rental_quota", {"used": 0, "max": career_selection.RENTAL_MAX_DEFAULT, "remaining": career_selection.RENTAL_MAX_DEFAULT})
            }

        try:
            result = game_service.pre_single_mode(session, exclude_viewer_ids)
            data = result.get('data', {})
            account_status.update_start_state(session, data)
            friends, exclude_viewer_ids, source = career_selection.normalize_friend_cards(data, session=session)

            rental_quota = {"used": 0, "max": career_selection.RENTAL_MAX_DEFAULT, "remaining": career_selection.RENTAL_MAX_DEFAULT}
            try:
                load_res = game_service.load_index_live(session)
                rental_quota = career_selection.read_rental_quota(load_res.get('data', {}))
            except Exception:
                pass

            if session.dashboard_data is not None:
                session.dashboard_data["friends"] = friends
                session.dashboard_data["friend_exclude_ids"] = exclude_viewer_ids
                session.dashboard_data["friends_loaded"] = True
                session.dashboard_data["rental_quota"] = rental_quota

            return {
                "success": True,
                "friends": friends,
                "exclude_viewer_ids": exclude_viewer_ids,
                "source": source,
                "rental_quota": rental_quota,
            }
        except Exception as e:
            return {"success": False, "detail": str(e)}

    def action(self, command_type, command_id, current_turn, current_vital, command_group_id=0, select_id=0):
        session = self.session
        busy = require_idle(session)
        if busy:
            return busy
        if not session.client:
            return {"success": False, "detail": "Not logged in"}

        try:
            result = game_service.exec_command(
                session,
                command_type=command_type,
                command_id=command_id,
                current_turn=current_turn,
                current_vital=current_vital,
                command_group_id=command_group_id,
                select_id=select_id
            )

            data = result.get('data', {})
            return {
                "success": True,
                "chara_info": data.get('chara_info', {}),
                "command_result": data.get('command_result', {})
            }
        except Exception as e:
            return {"success": False, "detail": str(e)}

    def delete_career(self, current_turn=0):
        session = self.session
        if not session.client:
            return {"success": False, "detail": "Not logged in"}
        if session.runner.snapshot().get("running") or session.loop_active():
            return {"success": False, "detail": "Cannot delete career while runner is active"}

        try:
            account = session.account or {}
            career = account.get("career") or {}
            game_service.force_delete_career(
                session,
                requested_turn=current_turn,
                cached_career=career,
            )
            account["career"] = None
            session.account = account
            if session.dashboard_data:
                session.dashboard_data["account"] = account
            return {"success": True, "account": account}
        except Exception as e:
            return {"success": False, "detail": str(e)}
