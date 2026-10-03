"""Durable `Idempotency-Key` handling (API.md 1.6, ADR-003, A-73).

The reservation, the business change, the audit/outbox rows and the stored response all commit in ONE transaction, so a
replay is exactly-once with the change. A key is scoped to `(tenant, actor, key)` and kept 24 h.

  * same key, same request  -> replay the stored status and body (`Idempotency-Replayed: true`)
  * same key, other request -> 422 `idempotency_mismatch`
  * same key while the first request is still running -> 409 `conflict`, immediately: a transaction-scoped
    advisory lock is *tried*, never waited for.
  * a failed attempt rolls back with its reservation, so the key can be used again.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from app.core.errors import Conflict, IdempotencyMismatch
from app.core.ids import new_id

RETENTION = timedelta(hours=24)

_metadata = MetaData()
idempotency_keys = Table(
    "idempotency_keys",
    _metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("created_by", PG_UUID(as_uuid=True)),
    Column("updated_by", PG_UUID(as_uuid=True)),
    Column("actor_id", PG_UUID(as_uuid=True), nullable=False),
    Column("key", Text, nullable=False),
    Column("endpoint", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("response_status", Integer),
    Column("response_body", JSONB(none_as_null=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Reservation:
    row_id: UUID


def request_hash(endpoint: str, body: BaseModel) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{endpoint}\n{canonical}".encode()).hexdigest()


def reserve(
    session: Session,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    key: str,
    endpoint: str,
    request_hash_: str,
) -> Replay | Reservation:
    """Take the key for this transaction, or return the stored response of an earlier identical request."""
    lock_name = f"idem:{tenant_id}:{actor_id}:{key}"
    got = session.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": lock_name}
    ).scalar_one()
    if not got:
        raise Conflict("The first request with this Idempotency-Key is still being processed.")

    now = datetime.now(UTC)
    existing = session.execute(
        select(
            idempotency_keys.c.id,
            idempotency_keys.c.request_hash,
            idempotency_keys.c.response_status,
            idempotency_keys.c.response_body,
            idempotency_keys.c.expires_at,
        ).where(
            idempotency_keys.c.tenant_id == tenant_id,
            idempotency_keys.c.actor_id == actor_id,
            idempotency_keys.c.key == key,
        )
    ).first()
    if existing is not None:
        if existing.expires_at > now:
            if existing.request_hash != request_hash_:
                raise IdempotencyMismatch("This Idempotency-Key was used for a different request.")
            # The reservation and the response commit together, so a visible row always carries its response.
            assert existing.response_status is not None and existing.response_body is not None
            return Replay(int(existing.response_status), dict(existing.response_body))
        session.execute(delete(idempotency_keys).where(idempotency_keys.c.id == existing.id))

    row_id = new_id()
    session.execute(
        insert(idempotency_keys).values(
            id=row_id,
            tenant_id=tenant_id,
            created_by=actor_id,
            updated_by=actor_id,
            actor_id=actor_id,
            key=key,
            endpoint=endpoint,
            request_hash=request_hash_,
            expires_at=now + RETENTION,
        )
    )
    return Reservation(row_id)


def store_response(
    session: Session, reservation: Reservation, status_code: int, body: dict[str, Any]
) -> None:
    session.execute(
        update(idempotency_keys)
        .where(idempotency_keys.c.id == reservation.row_id)
        .values(response_status=status_code, response_body=body)
    )
