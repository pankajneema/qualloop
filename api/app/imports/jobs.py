"""Import jobs (queue `imports`, ARCHITECTURE 6.1): `imports.validate` and `imports.run`.

Both run under the tenant of their message (`tenant_id`) and are no-ops, never errors, for a batch that is not visible
to that tenant or not in the expected status: a redelivered, late or misdirected message changes nothing. They open
short transactions of their own so the file download and the parsing never hold a database transaction (ADR-006).
The optional `**event` keyword arguments let the outbox dispatcher (which sends the event envelope) start the same jobs.
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import insert, select

from app.core.audit.writer import record_activity
from app.core.db import tenant_tx
from app.core.ids import new_id
from app.core.jobs import job
from app.core.outbox.writer import emit_event
from app.core.permissions import ACTOR_SYSTEM, Actor
from app.imports import engine, storage
from app.imports.classify import counts
from app.imports.job_refs import RUN_IMPORT, VALIDATE_IMPORT
from app.imports.models import ImportBatch, ImportRecord
from app.imports.parsing import ParsedRow, parse_rows
from app.imports.readmodels import batch_audit
from app.imports.spec import (
    COMPLETED,
    DUPLICATE,
    IMPORTED,
    IMPORTING,
    MAPPED,
    REJECTED,
    REVIEW,
    UNMAPPED,
    VALID,
    VALIDATED,
)

log = structlog.get_logger("imports.jobs")

RECORD_CHUNK = 1000


def _ids(tenant_id: str, batch_id: str | None, event: dict[str, Any]) -> tuple[UUID, UUID] | None:
    raw = batch_id or event.get("aggregate_id")
    try:
        return UUID(tenant_id), UUID(str(raw))
    except (ValueError, TypeError):
        log.warning("import_job_bad_ids")
        return None


def _system_actor(tenant_id: UUID) -> Actor:
    return Actor(
        type=ACTOR_SYSTEM,
        user_id=None,
        tenant_id=tenant_id,
        role="system",
        can_approve=False,
        plant_ids=(),
    )


def _batch(session: Any, tenant_id: UUID, batch_id: UUID, *, lock: bool) -> ImportBatch | None:
    query = select(ImportBatch).where(
        ImportBatch.tenant_id == tenant_id, ImportBatch.id == batch_id
    )
    if lock:
        query = query.with_for_update()
    batch: ImportBatch | None = session.execute(query).scalar_one_or_none()
    return batch


@job(VALIDATE_IMPORT, own_transaction=True)
def validate_import(tenant_id: str, batch_id: str | None = None, **event: Any) -> None:
    """Parse, normalise and classify every row; write the preview to object storage; `mapped` -> `validated`."""
    ids = _ids(tenant_id, batch_id, event)
    if ids is None:
        return
    tid, bid = ids
    with tenant_tx(tid, "system") as session:
        batch = _batch(session, tid, bid, lock=False)
        if batch is None or batch.status != MAPPED:
            log.info("import_validate_skipped", batch_id=str(bid))
            return
        entity, mapping = batch.entity, dict(batch.mapping)
    meta = storage.get_json(storage.meta_key(tid, bid))
    rows = parse_rows(storage.get_object(meta["source_key"]), meta["extension"], mapping)

    with tenant_tx(tid, "system") as session:
        batch = _batch(session, tid, bid, lock=True)
        if batch is None or batch.status != MAPPED or dict(batch.mapping) != mapping:
            log.info("import_validate_skipped", batch_id=str(bid))
            return
        results = engine.classify(session, tid, entity, rows, set(mapping))
        storage.put_json(storage.preview_key(tid, bid), engine.preview_rows(results))
        tally = counts(results)
        batch.rows_received = len(results)
        batch.rows_valid = tally[VALID]
        batch.rows_duplicate = tally[DUPLICATE]
        batch.rows_rejected = tally[REJECTED]
        batch.rows_unmapped = tally[UNMAPPED]
        batch.rows_review = tally[REVIEW]
        batch.rows_imported = 0
        batch.status = VALIDATED
        session.flush()
        record_activity(
            session,
            actor=_system_actor(tid),
            object_type="import_batch",
            object_id=bid,
            action="import.validated",
            after=batch_audit(batch),
        )
    log.info("import_validated", batch_id=str(bid), rows=len(rows))


@job(RUN_IMPORT, own_transaction=True)
def run_import(tenant_id: str, batch_id: str | None = None, **event: Any) -> None:
    """Re-validate against the current data, insert the valid rows in chunks, write every `import_records` row.

    `importing` -> `completed`, all in ONE transaction: a failure leaves nothing half done and the job can retry."""
    ids = _ids(tenant_id, batch_id, event)
    if ids is None:
        return
    tid, bid = ids
    with tenant_tx(tid, "system") as session:
        batch = _batch(session, tid, bid, lock=False)
        if batch is None or batch.status != IMPORTING:
            log.info("import_run_skipped", batch_id=str(bid))
            return
        entity, mapping = batch.entity, dict(batch.mapping)
    rows = [
        ParsedRow(int(r["row_number"]), dict(r["values"]))
        for r in storage.get_json(storage.preview_key(tid, bid))
    ]

    with tenant_tx(tid, "system") as session:
        batch = _batch(session, tid, bid, lock=True)
        if batch is None or batch.status != IMPORTING:
            log.info("import_run_skipped", batch_id=str(bid))
            return
        confirmed_by = batch.updated_by
        results = engine.classify(
            session, tid, entity, rows, set(mapping)
        )  # confirm-time re-validation
        created = engine.create_valid(session, tid, confirmed_by, entity, results)
        for r in results:
            if r.status == VALID and r.new_id not in created:
                engine.lose_the_race(entity, r)

        records = [
            {
                "id": new_id(),
                "tenant_id": tid,
                "created_by": confirmed_by,
                "updated_by": confirmed_by,
                "batch_id": bid,
                "row_number": r.row_number,
                "row_hash": r.row_hash,
                "source_record_id": r.source_record_id,
                "status": IMPORTED if r.status == VALID else r.status,
                "reason": None if r.status == VALID else r.reason,
                "target_id": r.new_id if r.status == VALID else None,
            }
            for r in results
        ]
        for start in range(0, len(records), RECORD_CHUNK):
            session.execute(insert(ImportRecord), records[start : start + RECORD_CHUNK])

        tally = counts(results)
        batch.rows_received = len(results)
        batch.rows_valid = tally[VALID]
        batch.rows_imported = tally[VALID]
        batch.rows_duplicate = tally[DUPLICATE]
        batch.rows_rejected = tally[REJECTED]
        batch.rows_unmapped = tally[UNMAPPED]
        batch.rows_review = tally[REVIEW]
        batch.status = COMPLETED
        session.flush()
        actor = _system_actor(tid)
        record_activity(
            session,
            actor=actor,
            object_type="import_batch",
            object_id=bid,
            action="import.complete",
            after=batch_audit(batch),
        )
        emit_event(
            session,
            actor=actor,
            aggregate_type="import_batch",
            aggregate_id=bid,
            event_type="IMPORT_COMPLETED",
            payload={"batch_id": str(bid)},
        )
    log.info("import_completed", batch_id=str(bid), imported=tally[VALID])
