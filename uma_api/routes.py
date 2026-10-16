"""Endpoint-family helpers: which route a verb takes, and its payload shape.

Every method here is a thin wrapper that builds one request payload and hands it
to ``self.call``. None of them touch the retry ladder, the SID chain, framing or
auth -- those stay in ``UmaClient`` -- so they are a separable concern even
though they run against the same object.

Career endpoints are namespaced PER SCENARIO (MANT = ``single_mode_free``,
Unity Cup = ``single_mode_team``) with the same verbs and payloads, so the
prefix is resolved at call time from the active scenario.

Mixed into ``UmaClient``, which keeps them on its public surface unchanged.
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from uma_api import update_guard as _update_guard
from uma_api.errors import UnsupportedScenarioError, api_error_result_code


log = logging.getLogger(__name__)


def derive_exchange_get_list_time(show_exchange_response):
    """Format item/show_exchange's server time for item/exchange."""
    headers = (
        show_exchange_response.get("data_headers")
        if isinstance(show_exchange_response, dict)
        else None
    )
    try:
        server_time = int((headers or {})["servertime"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("item/show_exchange returned no valid servertime") from exc
    # item/exchange's get_list_time equals the preceding item/show_exchange
    # servertime rendered as UTC. Verified in
    # uma_runtime/traffic/20260714-220113/raw.jsonl:
    # 1784044193 -> "2026/07/14 15:49:53", 1784044231 -> "2026/07/14 15:50:31",
    # 1784044242 -> "2026/07/14 15:50:42", 1784044360 -> "2026/07/14 15:52:40".
    wall_time = datetime.fromtimestamp(server_time, timezone.utc)
    return wall_time.strftime("%Y/%m/%d %H:%M:%S")


if TYPE_CHECKING:
    # Type-only base: declares the UmaClient state / helpers this mixin borrows.
    # At runtime the base is plain `object`, so the MRO is exactly what
    # `class ApiRoutes:` would produce.
    from uma_api.client_state import UmaClientState
    _HostState = UmaClientState
else:
    _HostState = object


class ApiRoutes(_HostState):

    def _single_mode_prefix(self, scenario_id=None):
        sid = scenario_id if scenario_id is not None else getattr(self, "current_scenario_id", None)
        if sid is None:
            return "single_mode_free"
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            raise UnsupportedScenarioError(sid) from None
        if sid == 0:
            return "single_mode_free"
        from career_bot.scenarios import endpoint_prefix_by_id, is_runnable_scenario
        if not is_runnable_scenario(sid):
            account = (
                getattr(self, "api_warehouse_account", "")
                or getattr(self, "account_name", "")
            )
            _update_guard.alert_unsupported_scenario(self.state_root, account, sid)
            raise UnsupportedScenarioError(sid)
        return endpoint_prefix_by_id()[sid]

    def _single_mode_ep(self, name, scenario_id=None):
        return f"{self._single_mode_prefix(scenario_id)}/{name}"

    def _remember_scenario_from_data(self, data):
        if not isinstance(data, dict):
            return
        for key in ("chara_info", "single_mode_chara_light", "single_mode_chara"):
            chara = data.get(key)
            if isinstance(chara, dict) and chara.get("scenario_id"):
                self.current_scenario_id = int(chara.get("scenario_id") or 0)
                return

    def read_info(self):
        # read_info/index was DROPPED from the client boot sequence in the
        # 1.32.x game update -- the server now rejects it with result_code 102
        # (boot is start_session + load/index only, confirmed via Frida capture
        # 2026-07-01, scripts/capture_boot.py). It never carried tp/money/item
        # state anyway (only story/gallery read-state, which the bot ignores).
        # Repoint to load/index so callers that used this to refresh live account
        # state (start_career TP check, 201 recovery) get real, current data
        # (tp_info/coin_info/user_item) instead of a 102.
        return self.call('load/index', {'adid': ''})

    def show_exchange(self):
        return self.call("item/show_exchange", {})

    def exchange_item(self, exchange_id, count, current_num, get_list_time):
        return self.call("item/exchange", {
            "exchange_id": exchange_id,
            "count": count,
            "current_num": current_num,
            "get_list_time": get_list_time,
        })

    def set_trained_chara_lock(self, trained_chara_ids, locked):
        """Lock (locked=True) or unlock (locked=False) trained characters.

        Captured endpoint (2026-06-25): trained_chara/change_lock_multi takes a
        bulk id array + lock_flag (1=lock, 0=unlock) + icon_type.
        """
        ids = [int(i) for i in trained_chara_ids if i is not None]
        if not ids:
            return None
        return self.call('trained_chara/change_lock_multi', {
            'trained_chara_id_array': ids,
            'lock_flag': 1 if locked else 0,
            'icon_type': 0,
        })

    def remove_trained_chara(self, trained_chara_ids, unlock_ids=None):
        """Delete one or more of the player's OWN trained characters (veterans).

        Captured endpoint (2026-06-25): trained_chara/remove takes a bulk id array.
        Only this field is action-specific; the device/auth envelope is added by
        _call_locked via payload.update(self.common()).

        A locked (memo) chara (is_locked=1) cannot be removed -- the server 102s.
        Pass its id in `unlock_ids` to unlock it (change_lock_multi) before remove.
        """
        ids = [int(i) for i in trained_chara_ids if i is not None]
        if not ids:
            return None
        # The official client opens the trained-chara management screen
        # (trained_chara/load, empty body) immediately before removing. Without
        # this prelude the server rejects trained_chara/remove with result_code
        # 102 (stale screen state). Sync the screen first, then delete.
        self.call('trained_chara/load', {})
        unlock = [int(i) for i in (unlock_ids or []) if i is not None]
        if unlock:
            # Locked charas must be unlocked in the SAME screen session before remove.
            self.set_trained_chara_lock(unlock, False)
        return self.call('trained_chara/remove', {'trained_chara_id_array': ids})

    def factor_select(self, current_turn, skill_id_array=None):
        return self.call(self._single_mode_ep('factor_select'), {
            'current_turn': current_turn,
            'skill_id_array': skill_id_array,
        })

    def factor_lottery(self, lottery_count=1, use_tp=30, tp_info=None):
        return self.call(self._single_mode_ep('factor_lottery'), {
            'lottery_count': lottery_count,
            'tp_info': tp_info if tp_info is not None else self.tp_info,
            'use_tp': use_tp,
        })

    def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=0):
        return self.call(self._single_mode_ep('finish'), {
            'is_force_delete': is_force_delete,
            'current_turn': current_turn,
            # Added in the 1.32.x update (captured from live client 2026-07-01).
            'factor_lottery_id': factor_lottery_id
        })

    def load_career(self, scenario_id=None):
        try:
            return self.call(self._single_mode_ep('load', scenario_id), {})
        except Exception as e:
            if scenario_id is None and getattr(self, "current_scenario_id", None) is None and api_error_result_code(e) in (102, 201):
                self.current_scenario_id = 2
                return self.call(self._single_mode_ep('load', 2), {})
            if api_error_result_code(e) == 205:
                log.warning(f"load_career: persistent 205 -> hard_reset + retry ({e})")
                self.hard_reset()
                return self.call(self._single_mode_ep('load', scenario_id), {})
            raise

    def minigame_end(self, current_turn, result_state=1, result_value=0, result_detail_array=None):
        return self.call(self._single_mode_ep('minigame_end'), {
            'result': {
                'result_state': result_state,
                'result_value': result_value,
                'result_detail_array': result_detail_array,
            },
            'current_turn': current_turn,
        })

    def pre_single_mode(self, exclude_viewer_ids=None):
        payload = {}
        if exclude_viewer_ids:
            payload['exclude_viewer_id_array'] = exclude_viewer_ids
        return self.call('pre_single_mode/index', payload)

    def start_career(self, card_id, support_card_ids, friend_viewer_id, friend_card_id,
                     parent_id_1, parent_id_2, scenario_id, deck_id=1, use_tp=30,
                     tp_info=None, current_money=0, succession_rank_point=0,
                     rental_viewer_id=0, rental_trained_chara_id=0,
                     difficulty_id=0, difficulty=0, is_boost=0,
                     boost_story_event_id=0, running_style=0):
        self.current_scenario_id = int(scenario_id or 4)
        try:
            running_style = int(running_style)
        except (TypeError, ValueError, OverflowError):
            running_style = 2
        if running_style not in (1, 2, 3, 4):
            running_style = 2
        if not tp_info:
            tp_info = {'current_tp': 100, 'max_tp': 100, 'max_recovery_time': 0}
        start_payload = {
            'start_chara': {
                'card_id': card_id,
                'support_card_ids': support_card_ids,
                'friend_support_card_info': {
                    'viewer_id': friend_viewer_id,
                    'support_card_id': friend_card_id
                },
                'succession_trained_chara_id_1': parent_id_1,
                'succession_trained_chara_id_2': parent_id_2,
                'rental_succession_trained_chara': {
                    'viewer_id': rental_viewer_id,
                    'trained_chara_id': rental_trained_chara_id,
                    'is_circle_member': False,
                    'is_event_rental': False
                },
                'scenario_id': scenario_id,
                'selected_difficulty_info': {
                    'difficulty_id': difficulty_id,
                    'difficulty': difficulty,
                    'is_boost': is_boost
                },
                'select_deck_id': deck_id,
                'boost_story_event_id': boost_story_event_id,
                # New start_chara fields added in the 1.32.x update (captured from
                # the live client 2026-07-01); omitting them 102s single_mode_free/start.
                'boost_factor_research_event_id': 0,
                'is_play_training_challenge': False,
                'training_challenge_mode': 0,
                'running_style': running_style
            },
            'tp_info': tp_info,
            'current_money': current_money,
            'use_tp': use_tp,
            'current_succession_rank_point': succession_rank_point
        }
        return self.call(self._single_mode_ep('start', scenario_id), start_payload)

    def exec_command(self, command_type, command_id, current_turn, current_vital, command_group_id=0, select_id=0):
        return self.call(self._single_mode_ep('exec_command'), {
            'command_type': command_type,
            'command_id': command_id,
            'command_group_id': command_group_id,
            'select_id': select_id,
            'current_turn': current_turn,
            'current_vital': current_vital
        })

    def check_event(self, event_id, current_turn, chara_id=0, choice_number=0):
        payload = {
            'event_id': event_id,
            'chara_id': chara_id or 0,
            'choice_number': choice_number if choice_number is not None else 0,
            'current_turn': current_turn
        }
        return self.call(self._single_mode_ep('check_event'), payload)

    def use_items(self, use_item_info_array, current_turn):
        return self.call(self._single_mode_ep('multi_item_use'), {
            'use_item_info_array': use_item_info_array,
            'current_turn': current_turn
        })

    def exchange_items(self, exchange_item_info_array, current_turn):
        return self.call(self._single_mode_ep('multi_item_exchange'), {
            'exchange_item_info_array': exchange_item_info_array,
            'current_turn': current_turn
        })

    def gain_skills(self, gain_skill_info_array, current_turn):
        gain_skill_info_array = [
            {
                "skill_id": item.get("skill_id"),
                "level": item.get("level", item.get("skill_level", 1)),
            }
            for item in gain_skill_info_array
        ]
        # Purchase 205 is deterministic (insufficient SP / state desync), and a failed
        # batch can still have committed; retrying can re-buy owned skills and drain SP.
        return self.call(self._single_mode_ep('gain_skills'), {
            'gain_skill_info_array': gain_skill_info_array,
            'current_turn': current_turn
        }, retry_205=0)

    def race_entry(self, program_id, current_turn, running_style=None, retry_208=6, retry_205=3):
        if running_style is not None:
            payload = {
                'program_id': program_id,
                'running_style': running_style,
                'current_turn': current_turn
            }
            return self.call(self._single_mode_ep('change_running_style'), payload, retry_208=retry_208, retry_205=retry_205)
        else:
            payload = {
                'program_id': program_id,
                'current_turn': current_turn
            }
            return self.call(self._single_mode_ep('race_entry'), payload, retry_208=retry_208, retry_205=retry_205)

    def race_start(self, is_short, current_turn):
        return self.call(self._single_mode_ep('race_start'), {
            'is_short': is_short,
            'current_turn': current_turn
        })

    def race_end(self, current_turn):
        return self.call(self._single_mode_ep('race_end'), {
            'current_turn': current_turn
        })

    def race_out(self, current_turn):
        return self.call(self._single_mode_ep('race_out'), {
            'current_turn': current_turn
        })

    def race_continue(self, current_turn, continue_type):
        return self.call(self._single_mode_ep('continue'), {
            'current_turn': current_turn,
            'continue_type': continue_type
        })

    def team_edit(self, team_data_array, current_turn):
        return self.call(self._single_mode_ep('team_edit', 2), {
            'team_data_array': team_data_array or [],
            'current_turn': current_turn,
        })

    def opponent_list(self, current_turn):
        return self.call(self._single_mode_ep('opponent_list', 2), {
            'current_turn': current_turn,
        })

    def team_race_analyze(self, race_set_id, current_turn):
        return self.call(self._single_mode_ep('team_race_analyze', 2), {
            'race_set_id': race_set_id,
            'current_turn': current_turn,
        })

    def team_race_start(self, team_race_set_id, current_turn):
        return self.call(self._single_mode_ep('team_race_start', 2), {
            'team_race_set_id': team_race_set_id,
            'current_turn': current_turn,
        })

    def team_race_end(self, current_turn):
        return self.call(self._single_mode_ep('team_race_end', 2), {
            'current_turn': current_turn,
        })

    def team_race_out(self, current_turn):
        return self.call(self._single_mode_ep('team_race_out', 2), {
            'current_turn': current_turn,
        })

    def team_race_continue(self, current_turn, continue_type=1):
        return self.call(self._single_mode_ep('team_race_continue', 2), {
            'continue_type': continue_type,
            'current_turn': current_turn,
        })

    # --- Grand Live (scenario 3) only ---
    # These four routes exist solely in the single_mode_live namespace, so they
    # pin scenario 3 the same way the team_* methods pin 2. Request shapes are
    # from the 2026-07-26 capture (uma_runtime/captures/gl_flow_01.jsonl) and
    # match the DTOs in docs/scenarios/grand-live-endpoints.md.

    def master_square(self, square_id, current_turn):
        """Spend performance tokens on a Live Tree square (the Da/Pa/Vo/Vi/Me
        interface). Answers with chara_info, home_info and a fresh live_data_set
        -- but NOT race_condition_array, which matters on a forced-race turn
        (see career_bot/scenarios/grand_live/live_actions._race_is_stranded)."""
        return self.call(self._single_mode_ep('master_square', 3), {
            'square_id': square_id,
            'current_turn': current_turn,
        })

    def reserve_square(self, square_id, current_turn):
        return self.call(self._single_mode_ep('reserve_square', 3), {
            'square_id': square_id,
            'current_turn': current_turn,
        })

    def lottery_square(self, square_id, current_turn):
        return self.call(self._single_mode_ep('lottery_square', 3), {
            'square_id': square_id,
            'current_turn': current_turn,
        })

    def live_start(self, current_turn):
        """Run the scheduled Grand Live performance (turns 24/36/48/60/72 --
        single_mode_live_live_data.turn_num)."""
        return self.call(self._single_mode_ep('live_start', 3), {
            'current_turn': current_turn,
        })

    def reserve_race(self, current_turn, add_race_array=None, cancel_race_array=None):
        return self.call('single_mode_free/reserve_race', {
            'current_turn': current_turn,
            'add_race_array': add_race_array or [],
            'cancel_race_array': cancel_race_array or []
        })
