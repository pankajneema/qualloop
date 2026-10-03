"""Minimal valid row per P01 table, for table-parametrised isolation tests."""

import hashlib
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


# --- P02 masters and imports (DATA_MODEL 2, 7). Each inserter adds its own parents and exactly one row to its table.
def _hex() -> str:
    return hashlib.sha256(uuid4().bytes).hexdigest()


def _supplier_id(conn: Connection, tenant_id: UUID) -> UUID:
    return conn.execute(  # type: ignore[no-any-return]
        text(
            "INSERT INTO suppliers (tenant_id, code, name, category, status) "
            "VALUES (:t, :c, 'Probe supplier', 'bought_out', 'approved') RETURNING id"
        ),
        {"t": tenant_id, "c": _code() + _code()},
    ).scalar_one()


def _part_id(conn: Connection, tenant_id: UUID) -> UUID:
    return conn.execute(  # type: ignore[no-any-return]
        text(
            "INSERT INTO parts (tenant_id, part_no, name) VALUES (:t, :p, 'Probe part') RETURNING id"
        ),
        {"t": tenant_id, "p": _code() + _code()},
    ).scalar_one()


def _customer_id(conn: Connection, tenant_id: UUID) -> UUID:
    return conn.execute(  # type: ignore[no-any-return]
        text(
            "INSERT INTO customers (tenant_id, name, code) VALUES (:t, 'Probe OEM', :c) RETURNING id"
        ),
        {"t": tenant_id, "c": _code() + _code()},
    ).scalar_one()


def _contact_id(conn: Connection, tenant_id: UUID) -> UUID:
    supplier = _supplier_id(conn, tenant_id)
    return conn.execute(  # type: ignore[no-any-return]
        text(
            "INSERT INTO supplier_contacts (tenant_id, supplier_id, name, mobile) "
            "VALUES (:t, :s, 'Probe contact', '+919876543210') RETURNING id"
        ),
        {"t": tenant_id, "s": supplier},
    ).scalar_one()


def _batch_id(conn: Connection, tenant_id: UUID) -> UUID:
    starter = conn.execute(
        text(
            "INSERT INTO users (tenant_id, email, name, role) "
            "VALUES (:t, :e, 'Probe starter', 'quality') RETURNING id"
        ),
        {"t": tenant_id, "e": f"probe.{uuid4().hex}@example.test"},
    ).scalar_one()
    return conn.execute(  # type: ignore[no-any-return]
        text(
            "INSERT INTO import_batches (tenant_id, entity, file_name, file_hash, mapping, status, "
            "started_by) VALUES (:t, 'suppliers', 'probe.csv', :h, '{}'::jsonb, 'uploaded', :u) "
            "RETURNING id"
        ),
        {"t": tenant_id, "h": _hex(), "u": starter},
    ).scalar_one()


def _suppliers(conn: Connection, tenant_id: UUID) -> None:
    _supplier_id(conn, tenant_id)


def _supplier_contacts(conn: Connection, tenant_id: UUID) -> None:
    _contact_id(conn, tenant_id)


def _contact_consents(conn: Connection, tenant_id: UUID) -> None:
    contact = _contact_id(conn, tenant_id)
    conn.execute(
        text(
            "INSERT INTO contact_consents (tenant_id, contact_id, channel, status, source, consent_at) "
            "VALUES (:t, :c, 'whatsapp', 'opted_in', 'manual', now())"
        ),
        {"t": tenant_id, "c": contact},
    )


def _customers(conn: Connection, tenant_id: UUID) -> None:
    _customer_id(conn, tenant_id)


def _parts(conn: Connection, tenant_id: UUID) -> None:
    _part_id(conn, tenant_id)


def _customer_parts(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text("INSERT INTO customer_parts (tenant_id, customer_id, part_id) VALUES (:t, :c, :p)"),
        {"t": tenant_id, "c": _customer_id(conn, tenant_id), "p": _part_id(conn, tenant_id)},
    )


def _supplier_parts(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO supplier_parts (tenant_id, supplier_id, part_id, status) "
            "VALUES (:t, :s, :p, 'active')"
        ),
        {"t": tenant_id, "s": _supplier_id(conn, tenant_id), "p": _part_id(conn, tenant_id)},
    )


def _import_batches(conn: Connection, tenant_id: UUID) -> None:
    _batch_id(conn, tenant_id)


def _import_records(conn: Connection, tenant_id: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO import_records (tenant_id, batch_id, row_number, row_hash, status, target_id) "
            "VALUES (:t, :b, 1, :h, 'imported', :x)"
        ),
        {"t": tenant_id, "b": _batch_id(conn, tenant_id), "h": _hex(), "x": uuid4()},
    )


MASTERS_INSERTERS: dict[str, Inserter] = {
    "suppliers": _suppliers,
    "supplier_contacts": _supplier_contacts,
    "contact_consents": _contact_consents,
    "customers": _customers,
    "parts": _parts,
    "customer_parts": _customer_parts,
    "supplier_parts": _supplier_parts,
    "import_batches": _import_batches,
    "import_records": _import_records,
}
MASTERS_TABLES = list(MASTERS_INSERTERS)

INSERTERS: dict[str, Inserter] = {
    "tenants": _tenants,
    "plants": _plants,
    "users": _users,
    "activity_log": _activity_log,
    "outbox_events": _outbox,
    "idempotency_keys": _idempotency,
    "job_dead_letters": _dead_letters,
    **MASTERS_INSERTERS,
}
TABLES = list(INSERTERS)
# Tables whose rows are created by create_tenant() itself.
TENANT_ROW_TABLE = "tenants"


def insert_row(conn: Connection, table: str, tenant_id: UUID, **_: Any) -> None:
    INSERTERS[table](conn, tenant_id)
