"""Shared command/result helpers for CareerRunner, extracted verbatim from runner.py.

What is left here after the §13.1/A16 carve-up is the small, pure glue every action
phase leans on: turning a Decision payload into the wire kwargs / the matching
home_info command row, normalizing a buy/use API return into a uniform
{ok, result_code, error} row for the debug log, and summing costs. The phases
themselves now live beside it -- events.py, racing.py, commerce.py, resources.py --
and the career-wide transitions in lifecycle.py.
"""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerActionMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerActionMixin(_HostState):
    def _exec_command_payload(self, payload):
        return {
            key: value
            for key, value in (payload or {}).items()
            if not str(key).startswith("_")
        }

    def _api_result(self, result):
        result = dict(result or {})
        error = str(result.get("error") or "")
        code = None
        for token in error.replace(":", " ").replace(",", " ").split():
            if token.isdigit():
                value = int(token)
                if value in {201, 202, 205, 208, 394, 709}:
                    code = value
                    break
        if result.get("result") == "ok":
            code = 1
        return {
            "ok": result.get("result") == "ok",
            "result_code": code,
            "error": error or None,
        }

    def _sum_cost(self, rows):
        return sum(int((row or {}).get("cost") or 0) for row in rows or [])

    def _shop_attempt_cost(self, attempt, selected):
        costs = {int(row.get("shop_item_id") or 0): int(row.get("cost") or 0) for row in selected or []}
        return sum(costs.get(int(row.get("shop_item_id") or 0), 0) for row in attempt or [])

    def _command_from_decision(self, state, decision):
        payload = decision.payload or {}
        command_type = int(payload["command_type"])
        command_id = int(payload["command_id"])
        command_group_id = int(payload.get("command_group_id", 0))
        for cmd in ((state.get("data") or {}).get("home_info") or {}).get("command_info_array") or []:
            if int(cmd.get("command_type") or 0) != command_type:
                continue
            if command_type == 3 and int(cmd.get("command_id") or 0) == command_group_id:
                return cmd
            if int(cmd.get("command_id") or 0) == command_id:
                return cmd
        return payload
