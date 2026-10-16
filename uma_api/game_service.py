import logging
from pathlib import Path
from typing import Any

from uma_api import api_warehouse


log = logging.getLogger(__name__)

GameApiResponse = dict[str, Any]
ApiData = dict[str, Any]


def require_client(session) -> Any:
    client = getattr(session, "client", None)
    if client is None:
        raise ValueError("Not logged in")
    return client


def load_index_cached(base_dir: str | Path, account: str, default=None) -> dict | None:
    return api_warehouse.read_latest(base_dir, account, "load/index", default)


def load_index_cached_data(base_dir: str | Path, account: str, default=None) -> Any:
    return api_warehouse.read_latest_data(base_dir, account, "load/index", default)


def clear_account_cache(base_dir: str | Path, account: str) -> bool:
    return api_warehouse.clear_account(base_dir, account)


def load_index_live(session, payload: dict | None = None) -> GameApiResponse:
    return require_client(session).call("load/index", {"adid": ""} if payload is None else payload)


def read_info(session) -> GameApiResponse:
    return require_client(session).read_info()


def login(session) -> GameApiResponse:
    """Pure transport session login (start_session + load/index + read_info).

    The post-login master.mdb freshness check moved to the application layer
    (backend/app/services/game_login.py:login_with_master_refresh, §13.2 B1) --
    application flows that want the refresh call that wrapper instead.
    """
    return require_client(session).login()


def login_client(client) -> GameApiResponse:
    if client is None:
        raise ValueError("Not logged in")
    return client.login()


def load_career(session) -> GameApiResponse:
    return require_client(session).load_career()


def pre_single_mode(session, exclude_viewer_ids=None) -> GameApiResponse:
    return require_client(session).pre_single_mode(exclude_viewer_ids)


def start_career(session, **kwargs) -> GameApiResponse:
    return require_client(session).start_career(**kwargs)


def exec_command(session, **kwargs) -> GameApiResponse:
    return require_client(session).exec_command(**kwargs)


def finish_career(session, current_turn: int, is_force_delete: bool = False) -> GameApiResponse:
    return require_client(session).finish_career(current_turn=current_turn, is_force_delete=is_force_delete)


def _force_delete_error_is_reconciled(error: Exception) -> bool:
    if type(error).__name__ == "StateRecoveryError":
        return True
    for attr in ("result_code", "response_code"):
        try:
            if int(getattr(error, attr, 0) or 0) in {102, 201}:
                return True
        except (TypeError, ValueError):
            pass
    message = str(error)
    return "StateRecoveryError" in message or any(
        f"API error {code}" in message for code in (102, 201)
    )


def _response_data(response: GameApiResponse | None) -> ApiData:
    if not isinstance(response, dict):
        return {}
    data = response.get("data") or {}
    return data if isinstance(data, dict) else {}


def _drain_force_delete_events(client, state: GameApiResponse, current_turn: int) -> GameApiResponse:
    current = state
    for _ in range(50):
        data = _response_data(current)
        events = data.get("unchecked_event_array") or []
        if not events:
            return current
        event = events[0] or {}
        chara_info = data.get("chara_info") or {}
        event_turn = int(chara_info.get("turn") or current_turn)
        try:
            current = client.check_event(
                event_id=event.get("event_id"),
                chara_id=event.get("chara_id", 0),
                choice_number=0,
                current_turn=event_turn,
            )
        except Exception as error:
            if _force_delete_error_is_reconciled(error):
                log.warning(f"[DELETE] pending events reconciled: {error}")
                return current
            raise
    return current


def force_delete_career(
    session,
    requested_turn: int = 0,
    cached_career: dict | None = None,
) -> GameApiResponse | None:
    """Force-delete the live single-mode career, tolerating already-gone state."""
    client = require_client(session)
    try:
        state = load_career(session)
    except Exception as error:
        if _force_delete_error_is_reconciled(error):
            log.warning(f"[DELETE] career load reconciled: {error}")
            return None
        raise

    data = _response_data(state)
    chara_info = data.get("chara_info") or {}
    if not chara_info:
        log.info("[DELETE] career already gone: single-mode load returned no chara_info")
        return None

    # load/index's Gallop.SingleModeCharaLight summary has no plain `turn`
    # (dump.cs ~352672), and the paused runner snapshot can be stale/zero. The
    # fresh single-mode load's chara_info.turn must therefore win over both.
    authoritative_turn = int(chara_info.get("turn") or 0)
    requested_turn = int(requested_turn or 0)
    cached_turn = int((cached_career or {}).get("turn") or 0)
    current_turn = authoritative_turn or requested_turn or cached_turn or 1

    race_start_info = data.get("race_start_info") or chara_info.get("race_start_info")
    if race_start_info:
        try:
            race_state = client.race_out(current_turn=current_turn)
            if isinstance(race_state, dict):
                state = race_state
        except Exception as error:
            if _force_delete_error_is_reconciled(error):
                log.warning(f"[DELETE] active race reconciled: {error}")
            else:
                raise

    state = _drain_force_delete_events(client, state, current_turn)
    try:
        return finish_career(session, current_turn=current_turn, is_force_delete=True)
    except Exception as error:
        if _force_delete_error_is_reconciled(error):
            log.warning(f"[DELETE] finish reconciled: {error}")
            return None
        raise


def remove_trained_chara(session, trained_chara_ids, unlock_ids=None) -> GameApiResponse | None:
    return require_client(session).remove_trained_chara(trained_chara_ids, unlock_ids=unlock_ids)


def recovery_tp(session, count: int = 1) -> Any:
    return require_client(session).recovery_tp(count)


def use_recovery_item(session, item_id: int, item_num: int = 1) -> Any:
    return require_client(session).use_recovery_item(item_id, item_num)


def refresh_cached_account_state(session, data: dict) -> None:
    require_client(session).refresh_cached_account_state(data)


def reset_circuit(session) -> None:
    try:
        reset = getattr(require_client(session), "reset_circuit", None)
        if reset is not None:
            reset()
    except Exception as exc:
        log.warning(f"Circuit reset skipped: {exc}")
