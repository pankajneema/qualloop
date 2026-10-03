"""Batch read model: the row plus what lives next to it (header in object storage) and what is derived from other batches."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session

from app.imports import storage
from app.imports.models import ImportBatch
from app.imports.schemas import BatchRead, BatchSummary, TargetFieldRead
from app.imports.spec import TARGET_FIELDS


def load_meta(batch: ImportBatch) -> dict[str, Any]:
    meta: dict[str, Any] = storage.get_json(storage.meta_key(batch.tenant_id, batch.id))
    return meta


def previous_batch_ids(session: Session, batch: ImportBatch) -> list[UUID]:
    """Earlier batches of this tenant with the same file hash (INV-IMP-01): the re-upload warning."""
    return list(
        session.scalars(
            select(ImportBatch.id)
            .where(
                ImportBatch.tenant_id == batch.tenant_id,
                ImportBatch.file_hash == batch.file_hash,
                ImportBatch.id != batch.id,
                tuple_(ImportBatch.created_at, ImportBatch.id) < tuple_(batch.created_at, batch.id),
            )
            .order_by(ImportBatch.created_at, ImportBatch.id)
        )
    )


def suggested_mapping(session: Session, batch: ImportBatch, columns: list[str]) -> dict[str, str]:
    """A-113: the tenant's most recent saved mapping for this entity, restricted to columns this file has."""
    previous = session.scalar(
        select(ImportBatch.mapping)
        .where(
            ImportBatch.tenant_id == batch.tenant_id,
            ImportBatch.entity == batch.entity,
            ImportBatch.id != batch.id,
            tuple_(ImportBatch.created_at, ImportBatch.id) < tuple_(batch.created_at, batch.id),
            text("import_batches.mapping <> '{}'::jsonb"),
        )
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    if not previous:
        return {}
    allowed = {f.name for f in TARGET_FIELDS[batch.entity]}
    return {k: v for k, v in previous.items() if k in allowed and v in columns}


def batch_read(session: Session, batch: ImportBatch) -> BatchRead:
    columns = list(load_meta(batch).get("columns", []))
    previous = previous_batch_ids(session, batch)
    return BatchRead(
        id=batch.id,
        entity=batch.entity,
        file_name=batch.file_name,
        file_hash=batch.file_hash,
        status=batch.status,
        mapping=dict(batch.mapping),
        suggested_mapping=suggested_mapping(session, batch, columns),
        columns=columns,
        target_fields=[
            TargetFieldRead(name=f.name, required=f.required) for f in TARGET_FIELDS[batch.entity]
        ],
        rows_received=batch.rows_received,
        rows_valid=batch.rows_valid,
        rows_imported=batch.rows_imported,
        rows_duplicate=batch.rows_duplicate,
        rows_rejected=batch.rows_rejected,
        rows_unmapped=batch.rows_unmapped,
        rows_review=batch.rows_review,
        started_by=batch.started_by,
        confirmed_at=batch.confirmed_at,
        file_hash_seen_before=bool(previous),
        previous_batch_ids=previous,
        created_at=batch.created_at,
    )


def batch_summary(batch: ImportBatch) -> BatchSummary:
    return BatchSummary(
        id=batch.id,
        entity=batch.entity,
        file_name=batch.file_name,
        file_hash=batch.file_hash,
        status=batch.status,
        rows_received=batch.rows_received,
        rows_valid=batch.rows_valid,
        rows_imported=batch.rows_imported,
        rows_duplicate=batch.rows_duplicate,
        rows_rejected=batch.rows_rejected,
        rows_unmapped=batch.rows_unmapped,
        rows_review=batch.rows_review,
        started_by=batch.started_by,
        confirmed_at=batch.confirmed_at,
        created_at=batch.created_at,
    )


def batch_audit(batch: ImportBatch, **extra: Any) -> dict[str, Any]:
    """Audit snapshot: identity, status, mapping and counters (no file content, no row values)."""
    summary: dict[str, Any] = batch_summary(batch).model_dump(mode="json")
    summary["mapping"] = dict(batch.mapping)
    summary.update(extra)
    return summary
