"""Row factories and DB helpers. All writes go through `qualloop_app` with the tenant GUC set, exactly like
the application (the owner role sees no rows under FORCE RLS and must never be used for data)."""

import json
import secrets
import string
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from tests.factories.env import KNOWN_HASH, PASSWORD


@contextmanager
def tenant_conn(
    engine: Engine,
    tenant_id: UUID | None,
    *,
    actor_type: str | None = "user",
    actor_id: UUID | None = None,
    extra: dict[str, str] | None = None,
) -> Iterator[Connection]:
    """One transaction as the app role with transaction-local GUCs (ADR-004)."""
    with engine.connect() as conn, conn.begin():
        gucs: dict[str, str | None] = {
            "app.tenant_id": str(tenant_id) if tenant_id else None,
            "app.actor_type": actor_type,
            "app.actor_id": str(actor_id) if actor_id else None,
        }
        gucs.update(extra or {})
        for name, value in gucs.items():
            if value is not None:
                conn.execute(text("SELECT set_config(:n, :v, true)"), {"n": name, "v": value})
        yield conn


def _rand(n: int, alphabet: str) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


@dataclass(frozen=True)
class SeededUser:
    id: UUID
    tenant_id: UUID
    email: str
    role: str
    can_approve: bool
    plant_ids: tuple[UUID, ...]
    password: str | None


@dataclass
class SeededTenant:
    id: UUID
    plants: list[UUID] = field(default_factory=list)
    admin: SeededUser | None = None
    quality: SeededUser | None = None
    approver: SeededUser | None = None  # quality + can_approve
    viewer: SeededUser | None = None


def create_tenant(
    engine: Engine, *, name: str | None = None, settings: dict[str, Any] | None = None
) -> UUID:
    tid = uuid4()
    with tenant_conn(engine, tid) as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, tenant_id, name, plan, settings) "
                "VALUES (:id, :id, :name, 'pilot', CAST(:settings AS jsonb))"
            ),
            {
                "id": tid,
                "name": name or f"Tenant {tid.hex[:8]}",
                "settings": json.dumps(settings or {}),
            },
        )
    return tid


def create_plant(
    engine: Engine,
    tenant_id: UUID,
    *,
    code: str | None = None,
    name: str | None = None,
    timezone: str = "Asia/Kolkata",
) -> UUID:
    pid = uuid4()
    with tenant_conn(engine, tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO plants (id, tenant_id, name, code, timezone) "
                "VALUES (:id, :t, :name, :code, :tz)"
            ),
            {
                "id": pid,
                "t": tenant_id,
                "name": name or f"Plant {pid.hex[:6]}",
                "code": code or _rand(6, string.ascii_uppercase + string.digits),
                "tz": timezone,
            },
        )
    return pid


def create_user(
    engine: Engine,
    tenant_id: UUID,
    *,
    role: str = "quality",
    can_approve: bool = False,
    plant_ids: tuple[UUID, ...] = (),
    active: bool = True,
    with_password: bool = True,
    email: str | None = None,
    mobile: str | None = None,
) -> SeededUser:
    uid = uuid4()
    address = email or f"{role}.{uid.hex[:10]}@example.test"
    with tenant_conn(engine, tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, name, mobile, role, can_approve, "
                "plant_ids, active, password_hash) "
                "VALUES (:id, :t, :email, :name, :mobile, :role, :ca, :plants, :active, :ph)"
            ),
            {
                "id": uid,
                "t": tenant_id,
                "email": address,
                "name": f"{role.title()} {uid.hex[:4]}",
                "mobile": mobile,
                "role": role,
                "ca": can_approve,
                "plants": list(plant_ids),
                "active": active,
                "ph": KNOWN_HASH if with_password else None,
            },
        )
    return SeededUser(
        uid, tenant_id, address, role, can_approve, plant_ids, PASSWORD if with_password else None
    )


def seed_tenant(engine: Engine, *, plants: int = 2) -> SeededTenant:
    """Tenant with plants and one user per role (admin, quality, quality+can_approve, viewer)."""
    tid = create_tenant(engine)
    seeded = SeededTenant(id=tid)
    seeded.plants = [create_plant(engine, tid) for _ in range(plants)]
    seeded.admin = create_user(engine, tid, role="admin")
    seeded.quality = create_user(engine, tid, role="quality", plant_ids=tuple(seeded.plants[:1]))
    seeded.approver = create_user(
        engine, tid, role="quality", can_approve=True, plant_ids=tuple(seeded.plants)
    )
    seeded.viewer = create_user(engine, tid, role="viewer", plant_ids=tuple(seeded.plants))
    return seeded


def fetch_all(
    engine: Engine,
    tenant_id: UUID,
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    actor_type: str | None = "user",
) -> list[dict[str, Any]]:
    with tenant_conn(engine, tenant_id, actor_type=actor_type) as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]


def scalar(engine: Engine, tenant_id: UUID, sql: str, params: dict[str, Any] | None = None) -> Any:
    with tenant_conn(engine, tenant_id) as conn:
        return conn.execute(text(sql), params or {}).scalar_one()


def insert_outbox_event(
    engine: Engine,
    tenant_id: UUID,
    *,
    event_type: str = "PLANT_CREATED",
    created_at: datetime | None = None,
    attempts: int = 0,
    payload: dict[str, Any] | None = None,
) -> UUID:
    """Pending outbox row. No RETURNING (supplier SELECT on outbox_events is `false`)."""
    row_id = uuid4()
    with tenant_conn(engine, tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO outbox_events (id, tenant_id, event_id, aggregate_type, aggregate_id, "
                "event_type, payload, attempts, created_at) "
                "VALUES (:id, :t, :eid, 'plant', :agg, :et, CAST(:p AS jsonb), :a, "
                "COALESCE(:created, now()))"
            ),
            {
                "id": row_id,
                "t": tenant_id,
                "eid": uuid4(),
                "agg": uuid4(),
                "et": event_type,
                "p": json.dumps(payload or {}),
                "a": attempts,
                "created": created_at,
            },
        )
    return row_id


def outbox_row(engine: Engine, tenant_id: UUID, row_id: UUID) -> dict[str, Any]:
    rows = fetch_all(engine, tenant_id, "SELECT * FROM outbox_events WHERE id = :i", {"i": row_id})
    assert len(rows) == 1, f"outbox row {row_id} not visible to tenant {tenant_id}"
    return rows[0]


def drain_outbox(engine: Engine) -> None:
    """Mark every pending/dead outbox row of every tenant processed so a test starts from an empty queue.
    Runs per tenant under that tenant's GUC (the only way RLS lets the app role touch rows)."""
    with engine.connect() as conn:
        tenant_ids = [r[0] for r in conn.execute(text("SELECT app_active_tenant_ids()"))]
    for tid in tenant_ids:
        with tenant_conn(engine, tid, actor_type="system") as conn:
            conn.execute(
                text("UPDATE outbox_events SET processed_at = now() WHERE processed_at IS NULL")
            )


def age_outbox_row(
    engine: Engine, owner_engine: Engine, tenant_id: UUID, row_id: UUID, seconds: float
) -> None:
    """Make `updated_at` look `seconds` old, to test backoff windows without sleeping.

    The updated_at trigger is disabled (as owner, in its own autocommit statement) only around the
    UPDATE, and always re-enabled."""
    with owner_engine.connect() as owner:
        owner.execute(
            text("ALTER TABLE outbox_events DISABLE TRIGGER trg_outbox_events_set_updated_at")
        )
        try:
            with tenant_conn(engine, tenant_id, actor_type="system") as conn:
                conn.execute(
                    text(
                        "UPDATE outbox_events SET updated_at = now() - make_interval(secs => :s) "
                        "WHERE id = :i"
                    ),
                    {"s": seconds, "i": row_id},
                )
        finally:
            owner.execute(
                text("ALTER TABLE outbox_events ENABLE TRIGGER trg_outbox_events_set_updated_at")
            )
