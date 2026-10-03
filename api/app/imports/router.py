"""HTTP routes of the imports module (API.md 3.3, 5): Quality/Admin only, the Viewer is denied everywhere (A-70)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core import ratelimit
from app.core.audit.writer import record_activity
from app.core.auth.deps import require
from app.core.commands.http import execute, idempotency_key_header
from app.core.db import tenant_tx
from app.core.errors import InvalidTransition, NotFound, RateLimited
from app.core.pagination import DEFAULT_LIMIT, CursorParam, LimitParam
from app.core.permissions import ACTOR_USER, QUALITY, Actor
from app.core.routing import api_router
from app.core.tenancy import actor_tx
from app.imports import commands, queries, storage
from app.imports.models import ImportBatch, ImportRecord
from app.imports.report import XLSX_MEDIA_TYPE, build_report
from app.imports.schemas import (
    BatchIdInput,
    BatchRead,
    BatchSummary,
    Confirm,
    ConfirmInput,
    Empty,
    ImportCreate,
    MapBody,
    MapInput,
    Page,
    PreviewItem,
    PreviewStatus,
    RecordItem,
    RecordStatus,
)
from app.imports.spec import COMPLETED

router = api_router("/imports", tags=["imports"])

Writer = Annotated[Actor, Depends(require(QUALITY))]
Reader = Annotated[Actor, Depends(require(QUALITY, command=False))]
IdempotencyKey = Annotated[str | None, Depends(idempotency_key_header)]

EXPORT_LIMIT = 20  # API.md 6: exports, per user per hour
EXPORT_WINDOW_SECONDS = 3600


@router.post("", response_model=BatchRead, status_code=201)
def create_import(
    body: ImportCreate, request: Request, actor: Writer, key: IdempotencyKey
) -> JSONResponse:
    return execute(commands.CREATE_IMPORT, body, request=request, actor=actor, idempotency_key=key)


@router.post("/{id}/map", response_model=BatchRead)
def map_import(
    id: UUID, body: MapBody, request: Request, actor: Writer, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.MAP_IMPORT,
        MapInput(batch_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/{id}/validate", response_model=BatchRead)
def validate_import(
    id: UUID, body: Empty, request: Request, actor: Writer, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.VALIDATE_IMPORT_COMMAND,
        BatchIdInput(batch_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/{id}/cancel", response_model=BatchRead)
def cancel_import(
    id: UUID, body: Empty, request: Request, actor: Writer, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CANCEL_IMPORT,
        BatchIdInput(batch_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/{id}/confirm", response_model=BatchRead)
def confirm_import(
    id: UUID, body: Confirm, request: Request, actor: Writer, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.CONFIRM_IMPORT,
        ConfirmInput(batch_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.get("", response_model=Page[BatchSummary])
def list_imports(
    actor: Reader, limit: LimitParam = DEFAULT_LIMIT, cursor: CursorParam = None
) -> Page[BatchSummary]:
    return queries.list_batches(actor, limit, cursor)


@router.get("/{id}", response_model=BatchRead)
def get_import(id: UUID, actor: Reader) -> BatchRead:
    return queries.get_batch(actor, id)


@router.get("/{id}/preview", response_model=Page[PreviewItem])
def preview_import(
    id: UUID,
    actor: Reader,
    status: PreviewStatus | None = None,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[PreviewItem]:
    return queries.preview(actor, id, status, limit, cursor)


@router.get("/{id}/records", response_model=Page[RecordItem])
def import_records(
    id: UUID,
    actor: Reader,
    status: RecordStatus | None = None,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> Page[RecordItem]:
    return queries.records(actor, id, status, limit, cursor)


@router.get(
    "/{id}/report.xlsx",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}},
)
def download_report(id: UUID, actor: Reader) -> Response:
    """The reconciliation report of a completed batch. An export: Quality/Admin only, 20 per hour per user, logged (INV-SEC-05)."""
    with actor_tx(actor) as db:
        batch = db.execute(
            select(ImportBatch).where(
                ImportBatch.tenant_id == actor.tenant_id, ImportBatch.id == id
            )
        ).scalar_one_or_none()
        if batch is None:
            raise NotFound("We could not find that import.")
        if batch.status != COMPLETED:
            raise InvalidTransition("The report is ready once the import has completed.")
        records = db.scalars(
            select(ImportRecord)
            .where(ImportRecord.tenant_id == actor.tenant_id, ImportRecord.batch_id == id)
            .order_by(ImportRecord.row_number)
        ).all()
        db.expunge_all()
    wait = ratelimit.reserve(
        [f"rl:export:{actor.user_id}"], limit=EXPORT_LIMIT, window_seconds=EXPORT_WINDOW_SECONDS
    )
    if wait:
        raise RateLimited(wait, "Too many exports. Try again later.")
    preview = storage.get_json(storage.preview_key(batch.tenant_id, batch.id))
    content = build_report(batch, records, preview)
    with tenant_tx(actor.tenant_id, ACTOR_USER, actor.user_id) as db:
        record_activity(
            db,
            actor=actor,
            object_type="import_batch",
            object_id=batch.id,
            action="import.export_report",
            after={"format": "xlsx", "rows": len(records)},
        )
    return Response(
        content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="import-report-{batch.id}.xlsx"'},
    )
