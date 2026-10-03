"""ADR-006 / ARCHITECTURE section 7: event catalogue, backoff schedule, message ids."""

from uuid import uuid4

import pytest

from tests.factories.contract import load

# Blueprint 22.3, verbatim, with the phase in which the emitting command/job is built.
EVENTS_22_3 = {
    "NCR_CREATED": "P04",
    "NCR_CONTAINED": "P04",
    "SCAR_ISSUED": "P05",
    "SCAR_RESPONSE_RECEIVED": "P05",
    "SCAR_SENT_BACK": "P05",
    "SCAR_ACCEPTED": "P05",
    "SCAR_OVERDUE": "P05",
    "EFFECTIVENESS_PASSED": "P06",
    "EFFECTIVENESS_FAILED": "P06",
    "EFFECTIVENESS_EXTENDED": "P06",
    "EFFECTIVENESS_CLOSED_NO_DATA": "P06",
    "DEFECT_EVENT_ATTRIBUTED": "P04",
    "DEBIT_CREATED": "P06",
    "DEBIT_RECOVERED": "P06",
    "DEBIT_WRITTEN_OFF": "P06",
    "CERTIFICATE_VALIDITY_CHANGED": "P03",
    "REQUIREMENT_OVERDUE": "P03",
    "RISK_CHANGED": "P07",
    "SUPPLIER_STATUS_CHANGED": "P02",
}
# A-94: derived names for the platform commands built in P01.
PLATFORM_EVENTS = {
    "USER_CREATED",
    "USER_UPDATED",
    "USER_DEACTIVATED",
    "USER_PASSWORD_RESET",
    "PLANT_CREATED",
    "PLANT_UPDATED",
    "TENANT_SETTINGS_UPDATED",
}


def test_blueprint_22_3_lists_nineteen_events() -> None:
    assert len(EVENTS_22_3) == 19


@pytest.mark.parametrize("event", sorted(EVENTS_22_3))
def test_event_catalogue_contains_every_22_3_event_as_non_derived(event: str) -> None:
    spec = load("app.core.outbox.registry", "get")(event)
    assert spec is not None, f"{event} missing from the event registry"
    assert spec.name == event
    assert spec.derived is False


@pytest.mark.parametrize("event", sorted(PLATFORM_EVENTS))
def test_platform_events_are_registered_as_derived_names(event: str) -> None:
    spec = load("app.core.outbox.registry", "get")(event)
    assert spec is not None
    assert spec.derived is True


def test_registry_rejects_unknown_event_types() -> None:
    assert load("app.core.outbox.registry", "get")("NOT_AN_EVENT") is None
    assert "NOT_AN_EVENT" not in load("app.core.outbox.registry", "all_event_types")()


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(
            event,
            marks=pytest.mark.xfail(
                strict=True, reason=f"emitter for {event} is built in {phase}, not in P01"
            ),
        )
        for event, phase in sorted(EVENTS_22_3.items())
    ],
)
def test_event_catalogue_every_22_3_event_has_emitter(event: str) -> None:
    """INV-PLT-15: every 22.3 event has a registered emitting command or job. P01 builds none of them, so each
    parametrisation is xfail(strict) with the phase named; remove the mark in the phase that adds the emitter."""
    spec = load("app.core.outbox.registry", "get")(event)
    assert spec is not None
    assert spec.emitters, f"{event} has no registered emitter"


def test_platform_events_have_their_p01_emitters_registered() -> None:
    get = load("app.core.outbox.registry", "get")
    for event in PLATFORM_EVENTS - {"USER_PASSWORD_RESET"}:
        assert get(event).emitters, f"{event} has no emitter"
    assert get("USER_PASSWORD_RESET").emitters


@pytest.mark.parametrize(("attempts", "seconds"), [(0, 5), (1, 10), (2, 20), (3, 40), (4, 80)])
def test_backoff_is_five_seconds_times_two_to_the_attempts(attempts: int, seconds: int) -> None:
    assert load("app.core.outbox.dispatcher", "backoff_seconds")(attempts) == seconds


def test_max_attempts_is_five() -> None:
    assert load("app.core.outbox.dispatcher", "MAX_ATTEMPTS") == 5


def test_handler_message_id_is_event_id_and_handler_name() -> None:
    event_id = uuid4()
    assert (
        load("app.core.outbox.dispatcher", "message_id_for")(event_id, "risk.recompute")
        == f"{event_id}:risk.recompute"
    )
