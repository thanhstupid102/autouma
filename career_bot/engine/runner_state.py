"""Type-only contract of the state and helpers CareerRunner's mixins share.

CareerRunner (career_bot/engine/runner.py) is assembled from nine mixins, and
every one of them freely reaches for state that ``CareerRunner.__init__``
creates and for helpers implemented in a *sibling* mixin. From any single
mixin's point of view those names simply come "from the host", which a type
checker cannot infer. This module declares that host contract once so mypy can
check the mixin bodies (§12.6 typing floor).

It is TYPE-ONLY and has no runtime effect whatsoever:

* the class body is bare annotations plus a ``TYPE_CHECKING``-guarded block, so
  it defines no runtime attribute or method;
* the mixins inherit it only under ``TYPE_CHECKING`` (see the ``_HostState``
  alias at the top of each mixin module), so at runtime each mixin's MRO is
  exactly ``(Mixin, object)`` and this module is never even imported.

Adding an attribute or helper to CareerRunner? Declare it here too, otherwise
the mixins that use it will not type-check.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from career_bot.planning.races import RacePlanner
from career_bot.skills import SkillBuyer


class CareerRunnerState:
    # --- class constants (career_bot/engine/runner.py) ---
    _ITEM_USE_RECOVERY_CAP: int
    _CARAT_TP_RECOVERY_COST: int
    _RACE_OUT_INPLACE_RETRIES: int
    _RACE_RELOGIN_RETRIES: int

    # --- collaborators ---
    base_dir: Path
    state_root: Path
    lock: threading.Lock
    thread: threading.Thread | None
    race_planner: RacePlanner
    skill_buyer: SkillBuyer
    # Deliberately Any: the concrete strategy / item manager / report shape is
    # chosen per scenario at runtime, and every mixin treats them structurally.
    strategy: Any
    item_manager: Any
    report: Any
    status: dict[str, Any]
    user_info_cache: dict[str, Any]
    auto_delete_trained: dict[str, Any]

    # --- run flags ---
    stop_requested: bool
    pause_requested: bool
    pause_exit_requested: bool
    burn_clocks: bool
    spark_reroll_enabled: bool
    stop_after_sp_dump: bool
    dev_mode: bool

    # --- bounded-recovery bookkeeping ---
    _race_recover_turn: int | None
    _race_recover_count: int
    _race_reset_turn: int | None
    _race_relogin_turn: int | None
    _race_relogin_count: int
    _item_use_recover_turn: int | None
    _item_use_recover_count: int
    _item_use_blocked_turn: int | None
    _last_race_action_turn: int | None
    _consecutive_race_count: int
    _run_crash_retries: int
    _run_restart_count: int
    _restart_callback: Any

    # --- reporting / notification bookkeeping ---
    _account: str
    _loop_index: int
    _loop_target: int
    _report_path: Any
    _last_flush_ts: float
    _last_flushed_report_revision: int | None
    _live_monitor: Any
    _notify_card_id: str
    _notify_rank: int
    _notify_rank_score: int
    _notify_factor_ids: list[Any]
    _notify_spark_reroll_options: list[list[Any]]
    _notify_spark_reroll_choice: int

    if TYPE_CHECKING:  # noqa: C901 - mccabe scores each type-only stub below as a branch
        # --- helpers a mixin borrows from a sibling mixin or CareerRunner ---
        # The bodies below are unreachable at runtime (TYPE_CHECKING is False);
        # the real implementations live in the module named above each group.
        # runner.py
        def stop(self) -> None:
            raise NotImplementedError

        # actions.py
        def _api_result(self, result: Any) -> dict[str, Any]:
            raise NotImplementedError

        def _sum_cost(self, rows: Any) -> int:
            raise NotImplementedError

        def _shop_attempt_cost(self, attempt: Any, selected: Any) -> int:
            raise NotImplementedError

        # commerce.py
        def _buy_skills(self, client: Any, state: Any, preset: Any, force: Any) -> Any:
            raise NotImplementedError

        # debug.py
        def _debug(self, event: Any, state: Any = None, data: Any = None) -> None:
            raise NotImplementedError

        def _debug_turn(self, state: Any, preset: Any) -> None:
            raise NotImplementedError

        def _log_item_use_text(self, turn: Any, rows: Any, prefix: str = "Items used") -> None:
            raise NotImplementedError

        def _turn_stats(self, chara: Any) -> dict[str, Any]:
            raise NotImplementedError

        def _format_turn_stats(self, stats: Any) -> str:
            raise NotImplementedError

        def _format_action_history_line(self, row: Any) -> str:
            raise NotImplementedError

        # events.py
        def _drain_events(self, client: Any, strategy: Any, state: Any, limit: int = 20, recover_on_state_error: bool = True) -> Any:
            raise NotImplementedError

        # recovery.py
        def _is_state_recovery_error(self, exc: Any) -> bool:
            raise NotImplementedError

        def _fresh_career_state(self, client: Any, strategy: Any = None, relogin_first: bool = False, preserve_item_failures: bool = False) -> Any:
            raise NotImplementedError

        def _recover_state_error(self, client: Any, strategy: Any, turn: Any, action: Any, exc: Any) -> Any:
            raise NotImplementedError

        def _recover_race_out(self, client: Any, strategy: Any, turn: Any, action: Any, exc: Any, program_id: Any = None) -> Any:
            raise NotImplementedError

        def _item_use_recovery_blocked(self, turn: Any) -> bool:
            raise NotImplementedError

        def _allow_item_use_recovery(self, turn: Any) -> bool:
            raise NotImplementedError

        # reporting.py
        def _log(self, action: Any, turn: Any, detail: Any) -> None:
            raise NotImplementedError

        def _log_locked(self, action: Any, turn: Any, detail: Any) -> None:
            raise NotImplementedError

        def _mark(self, **values: Any) -> None:
            raise NotImplementedError

        def _record_final_stats(self, state: Any) -> None:
            raise NotImplementedError

        def _capture_sparks(self, state: Any) -> None:
            raise NotImplementedError

        def _maybe_auto_delete_trained(self, client: Any, state: Any) -> None:
            raise NotImplementedError

        # resources.py
        def _ensure_spark_reroll_tp(self, client: Any, cost: int = 30) -> bool:
            raise NotImplementedError

        def _ensure_alarm_clock(self, client: Any, preset: Any) -> bool:
            raise NotImplementedError

        def _sync_cached_alarm_clock_count(self, client: Any) -> None:
            raise NotImplementedError

        def _record_clock_used(self) -> None:
            raise NotImplementedError
