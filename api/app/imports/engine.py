"""Classification and creation for one batch: loads the current masters once, classifies every row, creates the valid ones."""

from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.imports.classify import (
    Classified,
    classify_parts,
    classify_supplier_parts,
    classify_suppliers,
)
from app.imports.parsing import ParsedRow
from app.imports.spec import DUPLICATE, REJECTED, VALID
from app.masters import service as masters


def classify(
    session: Session,
    tenant_id: UUID,
    entity: str,
    rows: Sequence[ParsedRow],
    mapped: Collection[str],
) -> list[Classified]:
    """Every row against the CURRENT data of the tenant (validate and confirm-time re-validation share this)."""
    if entity == "suppliers":
        return classify_suppliers(rows, masters.suppliers_for_matching(session, tenant_id), mapped)
    if entity == "parts":
        return classify_parts(rows, masters.parts_for_matching(session, tenant_id), mapped)
    if entity == "supplier_parts":
        return classify_supplier_parts(
            rows,
            masters.suppliers_for_matching(session, tenant_id),
            masters.parts_for_matching(session, tenant_id),
            masters.supplier_parts_for_matching(session, tenant_id),
            mapped,
        )
    raise ValueError(f"entity {entity!r} cannot be imported in P02")


def create_valid(
    session: Session,
    tenant_id: UUID,
    user_id: UUID | None,
    entity: str,
    results: Sequence[Classified],
) -> set[UUID]:
    """Insert the `valid` rows in chunks and return the ids that were really created.

    A row that lost a race on a unique key (somebody created the same thing after the re-validation) is not created;
    the caller turns it into a reported row instead of failing the batch."""
    valid = [r for r in results if r.status == VALID and r.new_id is not None]
    if entity == "suppliers":
        return masters.create_suppliers_bulk(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            rows=[
                masters.NewSupplier(
                    id=_id(r),
                    code=r.data["code"],
                    name=r.data["name"],
                    category=r.data["category"],
                    gstin=r.data["gstin"],
                    city=r.data["city"],
                    state=r.data["state"],
                )
                for r in valid
            ],
        )
    if entity == "parts":
        return masters.create_parts_bulk(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            rows=[
                masters.NewPart(
                    id=_id(r),
                    part_no=r.data["part_no"],
                    name=r.data["name"],
                    category=r.data["category"],
                    current_revision=r.data["current_revision"],
                )
                for r in valid
            ],
        )
    return masters.create_supplier_parts_bulk(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        rows=[
            masters.NewSupplierPart(
                id=_id(r),
                supplier_id=r.data["supplier_id"],
                part_id=r.data["part_id"],
                supplier_part_no=r.data["supplier_part_no"],
                ppm_target=r.data["ppm_target"],
            )
            for r in valid
        ],
    )


def _id(result: Classified) -> UUID:
    assert result.new_id is not None
    return result.new_id


def lose_the_race(entity: str, result: Classified) -> None:
    """Re-label a valid row that could not be inserted because the key appeared in the meantime."""
    if entity == "suppliers":
        result.status, result.reason = (
            REJECTED,
            "The code was taken by another supplier while this import ran.",
        )
    else:
        result.status, result.reason = DUPLICATE, "Created by someone else while this import ran."
    result.new_id = None


def preview_rows(results: Sequence[Classified]) -> list[dict[str, Any]]:
    return [
        {
            "row_number": r.row_number,
            "status": r.status,
            "reason": r.reason,
            "source_record_id": r.source_record_id,
            "row_hash": r.row_hash,
            "values": r.values,
        }
        for r in results
    ]
