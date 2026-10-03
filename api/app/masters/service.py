"""The masters interface for other modules (ARCHITECTURE 3.1): snapshots to match against and bulk creation for imports.

Bulk creation is set-based (chunked multi-row INSERT ... ON CONFLICT DO NOTHING): the import budget of 5,000 rows in
under 60 seconds leaves no room for per-row queries. A row that loses a race on a unique key is simply not returned in
the inserted ids, so the caller can report it instead of failing the whole batch.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.audit.models import activity_log
from app.core.ids import new_id
from app.masters.models import Part, Supplier, SupplierPart

CHUNK = 500
INITIAL_IMPORT_REASON = "initial import"  # A-06


@dataclass(frozen=True)
class SupplierSnapshot:
    id: UUID
    code: str
    name: str
    gstin: str | None
    city: str | None
    state: str | None
    category: str
    archived: bool


@dataclass(frozen=True)
class PartSnapshot:
    id: UUID
    part_no: str
    name: str
    category: str | None
    current_revision: str | None
    archived: bool


@dataclass(frozen=True)
class SupplierPartSnapshot:
    id: UUID
    supplier_id: UUID
    part_id: UUID
    supplier_part_no: str | None
    ppm_target: int | None
    archived: bool


@dataclass(frozen=True)
class NewSupplier:
    id: UUID
    code: str
    name: str
    category: str
    gstin: str | None = None
    city: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class NewPart:
    id: UUID
    part_no: str
    name: str
    category: str | None = None
    current_revision: str | None = None


@dataclass(frozen=True)
class NewSupplierPart:
    id: UUID
    supplier_id: UUID
    part_id: UUID
    supplier_part_no: str | None = None
    ppm_target: int | None = None


def suppliers_for_matching(session: Session, tenant_id: UUID) -> list[SupplierSnapshot]:
    rows = session.execute(
        select(
            Supplier.id,
            Supplier.code,
            Supplier.name,
            Supplier.gstin,
            Supplier.city,
            Supplier.state,
            Supplier.category,
            Supplier.archived_at,
        )
        .where(Supplier.tenant_id == tenant_id)
        .order_by(Supplier.id)
    ).all()
    return [
        SupplierSnapshot(
            r.id, r.code, r.name, r.gstin, r.city, r.state, r.category, r.archived_at is not None
        )
        for r in rows
    ]


def parts_for_matching(session: Session, tenant_id: UUID) -> list[PartSnapshot]:
    rows = session.execute(
        select(
            Part.id, Part.part_no, Part.name, Part.category, Part.current_revision, Part.archived_at
        )
        .where(Part.tenant_id == tenant_id)
        .order_by(Part.id)
    ).all()
    return [
        PartSnapshot(
            r.id, r.part_no, r.name, r.category, r.current_revision, r.archived_at is not None
        )
        for r in rows
    ]


def supplier_parts_for_matching(session: Session, tenant_id: UUID) -> list[SupplierPartSnapshot]:
    rows = session.execute(
        select(
            SupplierPart.id,
            SupplierPart.supplier_id,
            SupplierPart.part_id,
            SupplierPart.supplier_part_no,
            SupplierPart.ppm_target,
            SupplierPart.archived_at,
        )
        .where(SupplierPart.tenant_id == tenant_id)
        .order_by(SupplierPart.id)
    ).all()
    return [
        SupplierPartSnapshot(
            r.id,
            r.supplier_id,
            r.part_id,
            r.supplier_part_no,
            r.ppm_target,
            r.archived_at is not None,
        )
        for r in rows
    ]


def _chunks[T](items: Sequence[T], size: int = CHUNK) -> Iterator[list[T]]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _audit(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    object_type: str,
    rows: Sequence[tuple[UUID, dict[str, Any]]],
    reason: str | None,
) -> None:
    """One `activity_log` row per created object, written by the system actor on behalf of the confirming user."""
    for chunk in _chunks(rows):
        session.execute(
            insert(activity_log),
            [
                {
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "created_by": user_id,
                    "updated_by": user_id,
                    "object_type": object_type,
                    "object_id": object_id,
                    "action": f"{object_type}.create",
                    "before": None,
                    "after": after,
                    "reason": reason,
                    "actor_type": "system",
                    "actor_id": None,
                    "session_id": None,
                    "ip": None,
                }
                for object_id, after in chunk
            ],
        )


def create_suppliers_bulk(
    session: Session, *, tenant_id: UUID, user_id: UUID | None, rows: Sequence[NewSupplier]
) -> set[UUID]:
    """Insert suppliers as `approved` with reason "initial import" (A-06) and log each. Returns the ids inserted."""
    now = datetime.now(UTC)
    inserted: set[UUID] = set()
    for chunk in _chunks(rows):
        stmt = (
            pg_insert(Supplier)
            .values(
                [
                    {
                        "id": r.id,
                        "tenant_id": tenant_id,
                        "code": r.code,
                        "name": r.name,
                        "gstin": r.gstin,
                        "city": r.city,
                        "state": r.state,
                        "category": r.category,
                        "status": "approved",
                        "status_reason": INITIAL_IMPORT_REASON,
                        "status_changed_by": user_id,
                        "status_changed_at": now,
                        "created_by": user_id,
                        "updated_by": user_id,
                    }
                    for r in chunk
                ]
            )
            .on_conflict_do_nothing()
            .returning(Supplier.id)
        )
        inserted.update(session.execute(stmt).scalars())
    _audit(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        object_type="supplier",
        reason=INITIAL_IMPORT_REASON,
        rows=[
            (
                r.id,
                {
                    "id": str(r.id),
                    "code": r.code,
                    "name": r.name,
                    "gstin": r.gstin,
                    "city": r.city,
                    "state": r.state,
                    "category": r.category,
                    "status": "approved",
                    "status_reason": INITIAL_IMPORT_REASON,
                    "status_changed_by": str(user_id) if user_id else None,
                    "status_changed_at": now.isoformat(),
                    "archived_at": None,
                },
            )
            for r in rows
            if r.id in inserted
        ],
    )
    return inserted


def create_parts_bulk(
    session: Session, *, tenant_id: UUID, user_id: UUID | None, rows: Sequence[NewPart]
) -> set[UUID]:
    inserted: set[UUID] = set()
    for chunk in _chunks(rows):
        stmt = (
            pg_insert(Part)
            .values(
                [
                    {
                        "id": r.id,
                        "tenant_id": tenant_id,
                        "part_no": r.part_no,
                        "name": r.name,
                        "category": r.category,
                        "current_revision": r.current_revision,
                        "created_by": user_id,
                        "updated_by": user_id,
                    }
                    for r in chunk
                ]
            )
            .on_conflict_do_nothing()
            .returning(Part.id)
        )
        inserted.update(session.execute(stmt).scalars())
    _audit(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        object_type="part",
        reason="import",
        rows=[
            (
                r.id,
                {
                    "id": str(r.id),
                    "part_no": r.part_no,
                    "name": r.name,
                    "category": r.category,
                    "current_revision": r.current_revision,
                    "archived_at": None,
                },
            )
            for r in rows
            if r.id in inserted
        ],
    )
    return inserted


def create_supplier_parts_bulk(
    session: Session, *, tenant_id: UUID, user_id: UUID | None, rows: Sequence[NewSupplierPart]
) -> set[UUID]:
    """Links are created `active` (A-117)."""
    inserted: set[UUID] = set()
    for chunk in _chunks(rows):
        stmt = (
            pg_insert(SupplierPart)
            .values(
                [
                    {
                        "id": r.id,
                        "tenant_id": tenant_id,
                        "supplier_id": r.supplier_id,
                        "part_id": r.part_id,
                        "supplier_part_no": r.supplier_part_no,
                        "status": "active",
                        "ppm_target": r.ppm_target,
                        "created_by": user_id,
                        "updated_by": user_id,
                    }
                    for r in chunk
                ]
            )
            .on_conflict_do_nothing()
            .returning(SupplierPart.id)
        )
        inserted.update(session.execute(stmt).scalars())
    _audit(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        object_type="supplier_part",
        reason="import",
        rows=[
            (
                r.id,
                {
                    "id": str(r.id),
                    "supplier_id": str(r.supplier_id),
                    "part_id": str(r.part_id),
                    "supplier_part_no": r.supplier_part_no,
                    "status": "active",
                    "ppm_target": r.ppm_target,
                    "archived_at": None,
                },
            )
            for r in rows
            if r.id in inserted
        ],
    )
    return inserted
