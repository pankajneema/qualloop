"""Declarative state machines (ADR-003): a table of `(from_state, command) -> to_state`.

Any pair not in the table, including unknown states, is `409 invalid_transition`. Each module owns its tables
(NCR, SCAR, certificate, ...); P01 only provides the engine (and the user lifecycle uses it).
"""

from collections.abc import Mapping

from app.core.errors import InvalidTransition


class StateMachine:
    def __init__(self, name: str, transitions: Mapping[tuple[str, str], str]) -> None:
        self.name = name
        self._transitions = dict(transitions)

    def apply(self, state: str, command: str) -> str:
        """The state after `command` from `state`; raises `InvalidTransition` when it is not allowed."""
        target = self._transitions.get((state, command))
        if target is None:
            allowed = sorted(self.allowed(state))
            options = ", ".join(allowed) if allowed else "nothing"
            raise InvalidTransition(
                f"This {self.name} is {state}. {command} is not allowed from here; allowed: {options}."
            )
        return target

    def allowed(self, state: str) -> set[str]:
        return {command for (source, command) in self._transitions if source == state}


__all__ = ["InvalidTransition", "StateMachine"]
