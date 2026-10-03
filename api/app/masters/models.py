"""ORM mapping of the masters tables (DATA_MODEL section 2). Only this module's commands, queries and service touch it."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base
from app.core.models import _Std as Std


class Supplier(Std, Base):
    __tablename__ = "suppliers"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_changed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupplierContact(Std, Base):
    __tablename__ = "supplier_contacts"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    supplier_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    mobile: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    is_quality_contact: Mapped[bool] = mapped_column(server_default=text("false"))
    verified_mobile_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    replaced_by_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class ContactConsent(Std, Base):
    __tablename__ = "contact_consents"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    contact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Customer(Std, Base):
    __tablename__ = "customers"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Part(Std, Base):
    __tablename__ = "parts"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    part_no: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    current_revision: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerPart(Std, Base):
    __tablename__ = "customer_parts"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    customer_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    part_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    customer_part_no: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupplierPart(Std, Base):
    __tablename__ = "supplier_parts"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    supplier_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    part_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    supplier_part_no: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    ppm_target: Mapped[int | None] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
