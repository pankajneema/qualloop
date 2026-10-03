"""The command pipeline (ADR-003, ARCHITECTURE section 5): ONE transaction per command.

    idempotency reservation -> authorise -> lock/validate/mutate (the handler) -> activity_log -> outbox_events
    -> in-transaction hooks -> store the idempotent response -> commit -> after-commit effects

Handlers only change business rows and return an `Outcome`; the pipeline writes the audit row and the outbox event, so a
handler cannot forget either. A failure anywhere rolls everything back, including the idempotency reservation.
There is no generic "update status": a state change is always a named command with its own permission and event.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import hooks, idempotency
from app.core.audit.writer import record_activity
from app.core.db import tenant_tx
from app.core.errors import Forbidden, ValidationFailed, field_error
from app.core.outbox.writer import emit_event
from app.core.permissions import ACTOR_USER, Actor, Permission, check_permission

log = structlog.get_logger("commands")

IDEMPOTENCY_REQUIRED = "required"
IDEMPOTENCY_OPTIONAL = "optional"

_UUID_TEXT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class CommandContext:
    session: Session
    actor: Actor


@dataclass
class Outcome[Out: BaseModel]:
    """What a handler returns: the response read model plus what the pipeline must record."""

    response: Out
    object_type: str
    object_id: UUID
    action: str  # `<object_type>.<verb>`, for example `plant.create`
    event_type: str  # registered in app.core.outbox.registry
    before: Mapping[str, Any] | None = None  # read model before (None for create)
    after: Mapping[str, Any] | None = None  # read model after
    reason: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)  # ids only, never PII
    aggregate_type: str | None = None  # defaults to object_type
    status_code: int = 200
    after_commit: tuple[Callable[[], None], ...] = ()


@dataclass(frozen=True)
class Command[In: BaseModel, Out: BaseModel]:
    name: str  # for example "plants.create"
    path: str  # relative to /api/v1, FastAPI style: "/plants/{id}/update"
    permission: Permission
    handle: Callable[[CommandContext, In], Outcome[Out]]
    idempotency: str = IDEMPOTENCY_OPTIONAL
    method: str = "POST"


@dataclass(frozen=True)
class CommandResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool = False


_COMMANDS: list[Command[Any, Any]] = []


def register[In: BaseModel, Out: BaseModel](command: Command[In, Out]) -> Command[In, Out]:
    if any(
        c.name == command.name or (c.method, c.path) == (command.method, command.path)
        for c in _COMMANDS
    ):
        raise ValueError(f"command {command.name} ({command.path}) is already registered")
    _COMMANDS.append(command)
    return command


def all_commands() -> Sequence[Command[Any, Any]]:
    """The registered commands. Command modules register themselves when imported; `app.api.router` imports them."""
    return tuple(_COMMANDS)


def run_command[In: BaseModel, Out: BaseModel](
    command: Command[In, Out],
    data: In,
    *,
    actor: Actor,
    idempotency_key: str | None,
    endpoint: str,
) -> CommandResult:
    """Execute `command` for `actor` in one transaction (see module docstring)."""
    if actor.type != ACTOR_USER or actor.user_id is None:
        raise Forbidden("You do not have permission to do this.")
    check_permission(command.permission, actor, command=True)
    if command.idempotency == IDEMPOTENCY_REQUIRED and not idempotency_key:
        raise ValidationFailed(
            "This action needs an Idempotency-Key header.",
            errors=[
                field_error("Idempotency-Key", "required", "Send a unique Idempotency-Key header.")
            ],
        )

    if idempotency_key is not None:
        if not _UUID_TEXT.match(idempotency_key):  # API.md 1.6: the key is a client-generated UUID
            raise ValidationFailed(
                "The Idempotency-Key header must be a UUID.",
                errors=[
                    field_error(
                        "Idempotency-Key",
                        "invalid",
                        "Send a UUID, for example from crypto.randomUUID().",
                    )
                ],
            )
        idempotency_key = idempotency_key.lower()

    with tenant_tx(actor.tenant_id, ACTOR_USER, actor.user_id) as session:
        reservation: idempotency.Reservation | None = None
        if idempotency_key:
            taken = idempotency.reserve(
                session,
                tenant_id=actor.tenant_id,
                actor_id=actor.user_id,
                key=idempotency_key,
                endpoint=endpoint,
                request_hash_=idempotency.request_hash(endpoint, data),
            )
            if isinstance(taken, idempotency.Replay):
                return CommandResult(taken.status_code, taken.body, replayed=True)
            reservation = taken

        outcome = command.handle(CommandContext(session=session, actor=actor), data)
        record_activity(
            session,
            actor=actor,
            object_type=outcome.object_type,
            object_id=outcome.object_id,
            action=outcome.action,
            before=outcome.before,
            after=outcome.after,
            reason=outcome.reason,
        )
        emit_event(
            session,
            actor=actor,
            aggregate_type=outcome.aggregate_type or outcome.object_type,
            aggregate_id=outcome.object_id,
            event_type=outcome.event_type,
            payload=outcome.payload,
        )
        hooks.publish(f"command.{command.name}", session, actor, outcome)
        body = outcome.response.model_dump(mode="json")
        if reservation is not None:
            idempotency.store_response(session, reservation, outcome.status_code, body)

    # Committed. Effects that must never happen for a rolled-back command run only now.
    for effect in outcome.after_commit:
        try:
            effect()
        except Exception:
            log.error("after_commit_effect_failed", command=command.name, exc_info=True)
    return CommandResult(outcome.status_code, body)
