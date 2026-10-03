"""ORM mapping of the platform tables owned by core: tenants, plants, users (DATA_MODEL section 1).

`activity_log`, `outbox_events`, `idempotency_keys` and `job_dead_letters` are written through Core `insert()` in
their own modules (no RETURNING on the first two: a supplier actor cannot SELECT them, DATA_MODEL 0.5).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import new_id


class Base(DeclarativeBase):
    pass


class _Std:
    """Standard columns (DATA_MODEL 0.2) shared by every tenant table."""

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class Tenant(_Std, Base):
    __tablename__ = "tenants"

    # tenant_id == id (CHECK); the ORM fills it from the id when the row is created.
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("id", new_id())
        kw.setdefault("tenant_id", kw["id"])
        super().__init__(**kw)


class Plant(_Std, Base):
    __tablename__ = "plants"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Kolkata")


class User(_Std, Base):
    __tablename__ = "users"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    mobile: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    can_approve: Mapped[bool] = mapped_column(server_default=text("false"))
    plant_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'::uuid[]")
    )
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    password_hash: Mapped[str | None] = mapped_column(Text)
