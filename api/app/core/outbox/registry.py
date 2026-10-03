"""Event catalogue (ARCHITECTURE section 7, blueprint 22.3).

`derived=False` events are named in blueprint 22.3; `derived=True` names are ours (A-94), one per command that the
blueprint says must "emit an outbox event" (section 7). `emitters` lists the commands/jobs that write the event (empty
until the phase that builds the emitter); `handlers` lists Dramatiq actors (name and queue) the dispatcher fans the event out to.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Handler:
    """A Dramatiq actor an event is fanned out to: its name and queue, so a process that never declared the actor
    (the dispatcher) can still build the message."""

    actor_name: str
    queue: str


@dataclass(frozen=True)
class EventSpec:
    name: str
    derived: bool
    emitters: tuple[str, ...] = ()
    handlers: tuple[Handler, ...] = ()


_EVENTS: dict[str, EventSpec] = {}


def register(spec: EventSpec) -> EventSpec:
    if spec.name in _EVENTS:
        raise ValueError(f"event {spec.name} is already registered")
    _EVENTS[spec.name] = spec
    return spec


def get(event_type: str) -> EventSpec | None:
    return _EVENTS.get(event_type)


def all_event_types() -> frozenset[str]:
    return frozenset(_EVENTS)


def add_emitter(event_type: str, emitter: str) -> None:
    spec = _EVENTS[event_type]
    if emitter not in spec.emitters:
        _EVENTS[event_type] = replace(spec, emitters=(*spec.emitters, emitter))


def add_handler(event_type: str, actor_name: str, *, queue: str) -> None:
    """Subscribe a Dramatiq actor to an event type (called at import time by the module that owns the handler)."""
    spec = _EVENTS[event_type]
    if all(h.actor_name != actor_name for h in spec.handlers):
        _EVENTS[event_type] = replace(
            spec, handlers=(*spec.handlers, Handler(actor_name=actor_name, queue=queue))
        )


def _register_all(names: Iterable[str], *, derived: bool) -> None:
    for name in names:
        register(EventSpec(name=name, derived=derived))


# Blueprint 22.3, verbatim (19 events). Emitters are added by the phase that builds the command or job.
_register_all(
    (
        "NCR_CREATED",
        "NCR_CONTAINED",
        "SCAR_ISSUED",
        "SCAR_RESPONSE_RECEIVED",
        "SCAR_SENT_BACK",
        "SCAR_ACCEPTED",
        "SCAR_OVERDUE",
        "EFFECTIVENESS_PASSED",
        "EFFECTIVENESS_FAILED",
        "EFFECTIVENESS_EXTENDED",
        "EFFECTIVENESS_CLOSED_NO_DATA",
        "DEFECT_EVENT_ATTRIBUTED",
        "DEBIT_CREATED",
        "DEBIT_RECOVERED",
        "DEBIT_WRITTEN_OFF",
        "CERTIFICATE_VALIDITY_CHANGED",
        "REQUIREMENT_OVERDUE",
        "RISK_CHANGED",
        "SUPPLIER_STATUS_CHANGED",
    ),
    derived=False,
)

# P01 platform events (A-94, derived names; no consumers in R1).
for _name, _emitter in (
    ("USER_CREATED", "users.create"),
    ("USER_UPDATED", "users.update"),
    ("USER_DEACTIVATED", "users.deactivate"),
    ("USER_PASSWORD_RESET", "auth.password_reset_confirm"),
    ("PLANT_CREATED", "plants.create"),
    ("PLANT_UPDATED", "plants.update"),
    ("TENANT_SETTINGS_UPDATED", "tenant_settings.update"),
):
    register(EventSpec(name=_name, derived=True, emitters=(_emitter,)))
