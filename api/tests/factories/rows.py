"""Minimal valid row per P01 table, for table-parametrised isolation tests."""

import json
import secrets
import string
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

Inserter = Callable[[Connection, UUID], None]


def _code() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def _tenants(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text("INSERT INTO tenants (id, tenant_id, name, plan) VALUES (:t, :t, 'Probe', 'pilot')"),
        {"t": tenant_id},
    )


def _plants(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text("INSERT INTO plants (tenant_id, name, code) VALUES (:t, 'Probe plant', :c)"),
        {"t": tenant_id, "c": _code()},
    )


def _users(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO users (tenant_id, email, name, role) "
            "VALUES (:t, :e, 'Probe user', 'quality')"
        ),
        {"t": tenant_id, "e": f"probe.{uuid4().hex}@example.test"},
    )


def _activity_log(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO activity_log (tenant_id, object_type, object_id, action, actor_type) "
            "VALUES (:t, 'plant', :o, 'plant.create', 'system')"
        ),
        {"t": tenant_id, "o": uuid4()},
    )


def _outbox(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO outbox_events (tenant_id, event_id, aggregate_type, aggregate_id, "
            "event_type, payload) VALUES (:t, :e, 'plant', :a, 'PLANT_CREATED', '{}'::jsonb)"
        ),
        {"t": tenant_id, "e": uuid4(), "a": uuid4()},
    )


def _idempotency(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO idempotency_keys (tenant_id, actor_id, key, endpoint, request_hash, expires_at) "
            "VALUES (:t, :a, :k, 'POST /plants', 'h', :x)"
        ),
        {
            "t": tenant_id,
            "a": uuid4(),
            "k": str(uuid4()),
            "x": datetime.now(UTC) + timedelta(hours=24),
        },
    )


def _dead_letters(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO job_dead_letters (tenant_id, queue, actor_name, message_id, payload, attempts, "
            "last_error, dead_lettered_at) "
            "VALUES (:t, 'default', 'probe', :m, CAST(:p AS jsonb), 5, 'boom', now())"
        ),
        {"t": tenant_id, "m": str(uuid4()), "p": json.dumps({})},
    )


INSERTERS: dict[str, Inserter] = {
    "tenants": _tenants,
    "plants": _plants,
    "users": _users,
    "activity_log": _activity_log,
    "outbox_events": _outbox,
    "idempotency_keys": _idempotency,
    "job_dead_letters": _dead_letters,
}
TABLES = list(INSERTERS)
# Tables whose rows are created by create_tenant() itself.
TENANT_ROW_TABLE = "tenants"


def insert_row(conn: Connection, table: str, tenant_id: UUID, **_: Any) -> None:
    INSERTERS[table](conn, tenant_id)
