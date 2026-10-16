"""Career-event check/drain methods for CareerRunner, extracted verbatim from actions.py.

`_event` submits ONE `check_event` (translating the strategy's 0-based choice
position into the wire's 1-based `choice_number`), `_drain_events` loops it until the
server stops handing back `unchecked_event_array`. Both delegate their 201 /
StateRecoveryError handling back to the recovery mixin, so no recovery policy lives
here.
"""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    # Type-only base: declares the CareerRunner state / sibling-mixin helpers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class RunnerEventMixin:` would produce.
    from career_bot.engine.runner_state import CareerRunnerState
    _HostState = CareerRunnerState
else:
    _HostState = object


class RunnerEventMixin(_HostState):
    def _event(self, client, strategy, payload, recover_on_state_error=True):
        data = dict(payload)
        event = data.pop("_event", None)
        current_turn = data.pop("_current_turn", 0)
        try:
            if event:
                choice = strategy.choose_from_event(event, current_turn)
                choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
                # Game wire convention (verified by sniffing the real client,
                # 2026-06-26): check_event choice_number is 1-BASED for
                # multi-choice events (top option = 1, second = 2, ...) and 0 for
                # single-choice/confirm events. choose() returns a 0-based
                # POSITION, so add 1 only when there is a real (>=2) choice.
                choice_number = (choice + 1) if (choice is not None and len(choices) >= 2) else 0
                name, effect = "", ""
                describe = getattr(strategy, "describe_event_choice", None)
                if callable(describe):
                    try:
                        name, effect = describe(event, choice)
                    except Exception:
                        name, effect = "", ""
                detail = f"{data.get('event_id')} '{name}' pos={choice} -> cn={choice_number}"
                if effect:
                    detail += f" [{effect}]"
                self._log("event_choice", current_turn, detail)
                # Persist the pick into the career report (bot_logs/*.json) so it
                # can be cross-checked against the in-game event afterwards.
                self._debug("event_choice", data={
                    "turn": current_turn,
                    "event_id": data.get("event_id"),
                    "story_id": event.get("story_id"),
                    "name": name,
                    "position": choice,
                    "choice_number": choice_number,
                    "effect": effect,
                })
                return client.check_event(
                    event_id=data["event_id"],
                    chara_id=event.get("chara_id", 0),
                    choice_number=choice_number,
                    current_turn=current_turn
                )
            if "event_id" not in data:
                self._log("recover", current_turn, "event requested without event_id, forcing state refresh")
                return self._fresh_career_state(client, strategy)
            return client.check_event(**data)
        except Exception as exc:
            if recover_on_state_error and self._is_state_recovery_error(exc):
                return self._recover_state_error(client, strategy, current_turn, "event_recovered", exc)
            raise

    def _drain_events(self, client, strategy, state, limit=20, recover_on_state_error=True):
        current = state
        for _ in range(limit):
            data = current.get("data") or {}
            events = data.get("unchecked_event_array") or []
            if not events:
                return current
            event = events[0] or {}
            choice = strategy._choice(event)
            chara_turn = (data.get("chara_info") or {}).get("turn")
            turn = chara_turn if chara_turn is not None else self.status["turn"]
            payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": turn}
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": turn}
            try:
                current = self._event(client, strategy, payload, recover_on_state_error=recover_on_state_error)
            except Exception as exc:
                if recover_on_state_error and self._is_state_recovery_error(exc):
                    return self._recover_state_error(client, strategy, turn, "events_recovered", exc)
                raise
        return current
