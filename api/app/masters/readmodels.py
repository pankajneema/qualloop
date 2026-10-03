"""Read models built from ORM rows, and the audit snapshots derived from them (contact PII is masked, ADR-019)."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import mask_email, mask_mobile
from app.masters.models import (
    ContactConsent,
    Customer,
    CustomerPart,
    Part,
    Supplier,
    SupplierContact,
    SupplierPart,
)
from app.masters.schemas import (
    ConsentRead,
    ContactRead,
    CustomerPartRead,
    CustomerRead,
    PartRead,
    SupplierPartRead,
    SupplierRead,
)

REVERIFY_AFTER = timedelta(
    days=180
)  # blueprint 8 C2: a mobile verified more than 180 days ago needs verifying again


def supplier_read(s: Supplier) -> SupplierRead:
    return SupplierRead(
        id=s.id,
        code=s.code,
        name=s.name,
        gstin=s.gstin,
        city=s.city,
        state=s.state,
        category=s.category,
        status=s.status,
        status_reason=s.status_reason,
        status_changed_by=s.status_changed_by,
        status_changed_at=s.status_changed_at,
        archived_at=s.archived_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def needs_reverification(c: SupplierContact, now: datetime | None = None) -> bool:
    """Computed, never stored (blueprint 8 C2, A-111): active and (mobile never verified or verified > 180 days ago)."""
    if not c.active:
        return False
    if c.verified_mobile_at is None:
        return True
    return c.verified_mobile_at < (now or datetime.now(UTC)) - REVERIFY_AFTER


def consent_read(k: ContactConsent) -> ConsentRead:
    return ConsentRead(
        id=k.id,
        channel=k.channel,
        status=k.status,
        source=k.source,
        consent_at=k.consent_at,
        revoked_at=k.revoked_at,
    )


def contact_read(c: SupplierContact, consents: Sequence[ContactConsent]) -> ContactRead:
    return ContactRead(
        id=c.id,
        supplier_id=c.supplier_id,
        name=c.name,
        role=c.role,
        mobile=c.mobile,
        email=c.email,
        is_quality_contact=c.is_quality_contact,
        verified_mobile_at=c.verified_mobile_at,
        verified_email_at=c.verified_email_at,
        active=c.active,
        disabled_at=c.disabled_at,
        disabled_reason=c.disabled_reason,
        replaced_by_contact_id=c.replaced_by_contact_id,
        needs_reverification=needs_reverification(c),
        consents=[consent_read(k) for k in consents],
    )


def consents_of(
    session: Session, tenant_id: UUID, contact_ids: Iterable[UUID]
) -> dict[UUID, list[ContactConsent]]:
    """Consents of many contacts in ONE query (no N+1), oldest first."""
    ids = list(contact_ids)
    grouped: dict[UUID, list[ContactConsent]] = {i: [] for i in ids}
    if not ids:
        return grouped
    rows = session.scalars(
        select(ContactConsent)
        .where(ContactConsent.tenant_id == tenant_id, ContactConsent.contact_id.in_(ids))
        .order_by(ContactConsent.consent_at, ContactConsent.id)
    )
    for row in rows:
        grouped[row.contact_id].append(row)
    return grouped


def contact_audit(read: ContactRead) -> dict[str, Any]:
    """Audit snapshot of a contact: mobile and email are masked, never raw."""
    snapshot = read.model_dump(mode="json")
    if snapshot["mobile"]:
        snapshot["mobile"] = mask_mobile(snapshot["mobile"])
    if snapshot["email"]:
        snapshot["email"] = mask_email(snapshot["email"])
    return snapshot


def customer_read(c: Customer) -> CustomerRead:
    return CustomerRead(
        id=c.id,
        name=c.name,
        code=c.code,
        archived_at=c.archived_at,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def part_read(p: Part) -> PartRead:
    return PartRead(
        id=p.id,
        part_no=p.part_no,
        name=p.name,
        category=p.category,
        current_revision=p.current_revision,
        archived_at=p.archived_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def customer_part_read(link: CustomerPart) -> CustomerPartRead:
    return CustomerPartRead(
        id=link.id,
        customer_id=link.customer_id,
        part_id=link.part_id,
        customer_part_no=link.customer_part_no,
        archived_at=link.archived_at,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def supplier_part_read(link: SupplierPart) -> SupplierPartRead:
    return SupplierPartRead(
        id=link.id,
        supplier_id=link.supplier_id,
        part_id=link.part_id,
        supplier_part_no=link.supplier_part_no,
        status=link.status,
        ppm_target=link.ppm_target,
        archived_at=link.archived_at,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )
