"""Outbox writer: one `outbox_events` row, in the caller's transaction (blueprint 22.2, ADR-006).

Written with a Core INSERT and no RETURNING: a supplier-session actor may append but never read this table
(DATA_MODEL 0.5), and RETURNING needs SELECT.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.core.outbox import registry
from app.core.outbox.models import outbox_events
from app.core.permissions import Actor


def emit_event(
    session: Session,
    *,
    actor: Actor,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: Mapping[str, Any],
) -> UUID:
    """Insert one pending event and return its `event_id` (the consumers' idempotency key).

    `payload` must contain ids only, never PII (DATA_MODEL 1.5). Unknown event types are a programming error."""
    if registry.get(event_type) is None:
        raise ValueError(
            f"unknown event type {event_type!r}: register it in app.core.outbox.registry"
        )
    event_id = new_id()
    session.execute(
        insert(outbox_events).values(
            id=new_id(),
            tenant_id=actor.tenant_id,
            event_id=event_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=dict(payload),
            attempts=0,
            created_by=actor.user_id if actor.type == "user" else None,
            updated_by=actor.user_id if actor.type == "user" else None,
        )
    )
    return event_id
