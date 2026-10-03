"""ADR-003: declarative (from, command) -> to transition tables; unknown pairs are 409 invalid_transition."""

from itertools import product
from typing import Any

import pytest

from tests.factories.contract import load

# A miniature NCR-like table. Exhaustive allowed AND forbidden pairs are enumerated from it.
TRANSITIONS = {
    ("open", "contain"): "contained",
    ("open", "cancel"): "cancelled",
    ("contained", "decide_scar"): "awaiting_scar",
    ("contained", "cancel"): "cancelled",
    ("awaiting_scar", "cancel"): "cancelled",
    ("closed", "reopen"): "contained",
}
STATES = ["open", "contained", "awaiting_scar", "closed", "cancelled"]
COMMANDS = ["contain", "decide_scar", "cancel", "reopen", "close"]


def _machine() -> Any:
    return load("app.core.commands.state_machine", "StateMachine")("ncr", TRANSITIONS)


@pytest.mark.parametrize(("pair", "target"), list(TRANSITIONS.items()))
def test_every_allowed_transition_returns_its_target_state(
    pair: tuple[str, str], target: str
) -> None:
    machine = _machine()
    assert machine.apply(*pair) == target


@pytest.mark.parametrize(
    ("state", "command"),
    [pair for pair in product(STATES, COMMANDS) if pair not in TRANSITIONS],
)
def test_every_forbidden_transition_raises_invalid_transition_409(state: str, command: str) -> None:
    machine = _machine()
    invalid = load("app.core.commands.state_machine", "InvalidTransition")
    with pytest.raises(invalid) as excinfo:
        machine.apply(state, command)
    assert excinfo.value.status == 409
    assert excinfo.value.code == "invalid_transition"


def test_unknown_state_is_invalid_transition_not_a_key_error() -> None:
    invalid = load("app.core.commands.state_machine", "InvalidTransition")
    with pytest.raises(invalid):
        _machine().apply("exploded", "contain")


def test_terminal_state_has_no_allowed_commands() -> None:
    machine = _machine()
    assert machine.allowed("cancelled") == set()


def test_allowed_lists_the_commands_valid_from_a_state() -> None:
    machine = _machine()
    assert machine.allowed("open") == {"contain", "cancel"}
    assert machine.allowed("closed") == {"reopen"}


def test_invalid_transition_detail_names_the_current_state() -> None:
    machine = _machine()
    invalid = load("app.core.commands.state_machine", "InvalidTransition")
    with pytest.raises(invalid) as excinfo:
        machine.apply("cancelled", "reopen")
    assert "cancelled" in str(excinfo.value.detail)
