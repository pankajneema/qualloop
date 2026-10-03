"""Import read models (API.md 5): batches, preview (from object storage), records, all keyset-paginated. Quality/Admin only."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, InvalidTransition, NotFound
from app.core.pagination import decode_cursor, encode_cursor
from app.core.permissions import Actor
from app.core.tenancy import actor_tx
from app.imports import storage
from app.imports.models import ImportBatch, ImportRecord
from app.imports.readmodels import batch_read, batch_summary
from app.imports.schemas import BatchRead, BatchSummary, Page, PreviewItem, RecordItem
from app.imports.spec import COMPLETED, IMPORTING, VALIDATED

_INVALID_CURSOR = "That page cursor is not valid. Start again from the first page."
SORT_CREATED = "created_at"
SORT_ROW = "row_number"


def get_batch(actor: Actor, batch_id: UUID) -> BatchRead:
    with actor_tx(actor) as db:
        batch = _find(db, actor, batch_id)
        return batch_read(db, batch)


def _find(db: Session, actor: Actor, batch_id: UUID) -> ImportBatch:
    batch = db.execute(
        select(ImportBatch).where(
            ImportBatch.tenant_id == actor.tenant_id, ImportBatch.id == batch_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise NotFound("We could not find that import.")
    return batch


def list_batches(actor: Actor, limit: int, cursor: str | None) -> Page[BatchSummary]:
    """Newest first: `created_at DESC, id DESC` (index `ix_import_batches_created`)."""
    query = select(ImportBatch).where(ImportBatch.tenant_id == actor.tenant_id)
    if cursor is not None:
        keys = decode_cursor(cursor, SORT_CREATED)
        try:
            query = query.where(
                tuple_(ImportBatch.created_at, ImportBatch.id)
                < tuple_(datetime.fromisoformat(str(keys[0])), UUID(str(keys[1])))
            )
        except (IndexError, ValueError, TypeError) as exc:
            raise BadRequest(_INVALID_CURSOR) from exc
    with actor_tx(actor) as db:
        rows = db.scalars(
            query.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).limit(limit + 1)
        ).all()
    page = rows[:limit]
    next_cursor = (
        encode_cursor([page[-1].created_at.isoformat(), str(page[-1].id)], SORT_CREATED)
        if len(rows) > limit and page
        else None
    )
    return Page[BatchSummary](items=[batch_summary(b) for b in page], next_cursor=next_cursor)


def _row_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    keys = decode_cursor(cursor, SORT_ROW)
    try:
        return int(keys[0])
    except (IndexError, ValueError, TypeError) as exc:
        raise BadRequest(_INVALID_CURSOR) from exc


def preview(
    actor: Actor, batch_id: UUID, status: str | None, limit: int, cursor: str | None
) -> Page[PreviewItem]:
    after = _row_cursor(cursor)
    with actor_tx(actor) as db:
        batch = _find(db, actor, batch_id)
        ready = batch.status in (VALIDATED, IMPORTING, COMPLETED)
        tenant_id, bid = batch.tenant_id, batch.id
    if not ready:
        raise InvalidTransition("There is no preview yet. Validate the file first.")
    rows = storage.get_json(storage.preview_key(tenant_id, bid))
    selected = [
        r for r in rows if r["row_number"] > after and (status is None or r["status"] == status)
    ]
    page = selected[:limit]
    return Page[PreviewItem](
        items=[
            PreviewItem(
                row_number=r["row_number"],
                status=r["status"],
                reason=r["reason"],
                source_record_id=r["source_record_id"],
                values=r["values"],
            )
            for r in page
        ],
        next_cursor=encode_cursor([page[-1]["row_number"]], SORT_ROW)
        if len(selected) > limit and page
        else None,
    )


def records(
    actor: Actor, batch_id: UUID, status: str | None, limit: int, cursor: str | None
) -> Page[RecordItem]:
    after = _row_cursor(cursor)
    with actor_tx(actor) as db:
        _find(db, actor, batch_id)
        query = select(ImportRecord).where(
            ImportRecord.tenant_id == actor.tenant_id,
            ImportRecord.batch_id == batch_id,
            ImportRecord.row_number > after,
        )
        if status is not None:
            query = query.where(ImportRecord.status == status)
        rows = db.scalars(query.order_by(ImportRecord.row_number).limit(limit + 1)).all()
    page = rows[:limit]
    return Page[RecordItem](
        items=[
            RecordItem(
                row_number=r.row_number,
                status=r.status,
                reason=r.reason,
                target_id=r.target_id,
                source_record_id=r.source_record_id,
                row_hash=r.row_hash,
            )
            for r in page
        ],
        next_cursor=encode_cursor([page[-1].row_number], SORT_ROW)
        if len(rows) > limit and page
        else None,
    )
