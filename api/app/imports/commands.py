"""Import batch commands (API.md 3.3): create, map, validate, cancel, confirm.

`validate` and `confirm` change the batch and hand the work to the `imports` queue after the commit; the jobs
(`app.imports.jobs`) do the parsing and the inserts. A batch moves only through these commands (state table below)."""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.commands.base import (
    IDEMPOTENCY_REQUIRED,
    Command,
    CommandContext,
    Outcome,
    register,
)
from app.core.commands.state_machine import StateMachine
from app.core.errors import (
    NotFound,
    ValidationFailed,
    field_error,
)
from app.core.files import in_quarantine
from app.core.files import storage as file_storage
from app.core.files.job_refs import SCAN_FILE
from app.core.ids import new_id
from app.core.jobs import enqueue
from app.core.permissions import QUALITY
from app.core.redis_client import get_redis
from app.imports import storage
from app.imports.job_refs import RUN_IMPORT, VALIDATE_IMPORT
from app.imports.models import ImportBatch
from app.imports.parsing import ImportFileError, read_header
from app.imports.readmodels import batch_audit, batch_read, load_meta
from app.imports.schemas import (
    BatchIdInput,
    BatchRead,
    ConfirmInput,
    ImportCreate,
    MapInput,
)
from app.imports.spec import (
    CANCELLED,
    IMPORTING,
    MAPPED,
    TARGET_FIELDS,
    UPLOADED,
    VALIDATED,
)

# (state, command) -> state. `validate` and `confirm` are listed for the guard; their targets are set by the commands
# (`validate` keeps the batch `mapped` until the job moves it to `validated`).
BATCH_STATES = StateMachine(
    "import batch",
    {
        (UPLOADED, "map"): MAPPED,
        (MAPPED, "map"): MAPPED,
        (VALIDATED, "map"): MAPPED,
        (MAPPED, "validate"): MAPPED,
        (VALIDATED, "confirm"): IMPORTING,
        (UPLOADED, "cancel"): CANCELLED,
        (MAPPED, "cancel"): CANCELLED,
        (VALIDATED, "cancel"): CANCELLED,
    },
)

_EXTENSIONS = ("xlsx", "csv")


def _lock_batch(ctx: CommandContext, batch_id: UUID) -> ImportBatch:
    batch = ctx.session.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == ctx.actor.tenant_id, ImportBatch.id == batch_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise NotFound("We could not find that import.")
    return batch


def _save(session: Session, batch: ImportBatch) -> None:
    session.flush()
    session.refresh(batch)


def _outcome(
    ctx: CommandContext,
    batch: ImportBatch,
    *,
    action: str,
    event: str,
    before: dict[str, Any] | None,
    status_code: int = 200,
    after_extra: dict[str, Any] | None = None,
    after_commit: tuple[Any, ...] = (),
) -> Outcome[BatchRead]:
    return Outcome(
        response=batch_read(ctx.session, batch),
        object_type="import_batch",
        object_id=batch.id,
        action=action,
        event_type=event,
        before=before,
        after=batch_audit(batch, **(after_extra or {})),
        payload={"batch_id": str(batch.id)},
        status_code=status_code,
        after_commit=after_commit,
    )


# ------------------------------------------------------------------------------------------------ create
def _request_scan_if_quarantined(tenant_id: UUID, key: str) -> None:
    """The browser PUT the file into quarantine and nothing else triggers the scan, so the first `POST /imports` for a key
    that is still there enqueues `files.scan` (at most once per 30 s per key). The answer stays 404: the batch is created
    only after the scan has promoted the file, and the client retries."""
    if not in_quarantine(key):
        return  # not uploaded at all: nothing to scan
    if get_redis().set(f"idem:scan:{key}", "1", nx=True, ex=30):
        enqueue(SCAN_FILE, tenant_id=str(tenant_id), key=key)


def _create(ctx: CommandContext, data: ImportCreate) -> Outcome[BatchRead]:
    actor = ctx.actor
    name = data.file_name
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in _EXTENSIONS:
        raise ValidationFailed(
            "Upload an .xlsx or .csv file.",
            errors=[
                field_error("file_name", "unsupported", "The file name must end in .xlsx or .csv.")
            ],
        )
    file_storage.assert_key_in_tenant(data.key, actor.tenant_id)  # another tenant's key is a 404
    parsed_key = file_storage.parse_key(data.key)
    if parsed_key is None or parsed_key.group("kind") != "import":
        raise ValidationFailed(
            "That file was not uploaded for an import.",
            errors=[field_error("key", "wrong_kind", "Upload the file again as an import.")],
        )
    if parsed_key.group("ext") != extension:
        raise ValidationFailed(
            "The file name and the uploaded file do not match.",
            errors=[field_error("file_name", "mismatch", "Use the name of the uploaded file.")],
        )
    try:
        content = storage.get_object(data.key)
    except NotFound:
        # Still in quarantine (or failed the scan, or never uploaded): 404. The scan request is sent straight to the
        # broker (not after commit), so it survives the rollback this 404 causes.
        _request_scan_if_quarantined(actor.tenant_id, data.key)
        raise
    try:
        columns = read_header(content, extension)
    except ImportFileError as exc:
        raise ValidationFailed(
            exc.message, errors=[field_error("key", "unreadable", exc.message)]
        ) from exc
    batch_id = new_id()
    storage.put_json(
        storage.meta_key(actor.tenant_id, batch_id),
        {"source_key": data.key, "extension": extension, "columns": columns},
    )
    batch = ImportBatch(
        id=batch_id,
        tenant_id=actor.tenant_id,
        entity=data.entity,
        file_name=name,
        file_hash=hashlib.sha256(content).hexdigest(),
        mapping={},
        status=UPLOADED,
        started_by=actor.user_id,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    ctx.session.add(batch)
    _save(ctx.session, batch)
    return _outcome(
        ctx, batch, action="import.create", event="IMPORT_UPLOADED", before=None, status_code=201
    )


# --------------------------------------------------------------------------------------------------- map
def _map(ctx: CommandContext, data: MapInput) -> Outcome[BatchRead]:
    batch = _lock_batch(ctx, data.batch_id)
    BATCH_STATES.apply(batch.status, "map")
    mapping = {k: v.strip() for k, v in data.body.mapping.items()}
    fields = {f.name: f for f in TARGET_FIELDS[batch.entity]}
    columns = set(load_meta(batch).get("columns", []))
    errors: list[dict[str, str]] = []
    for target, source in mapping.items():
        if target not in fields:
            errors.append(
                field_error(
                    f"mapping.{target}", "unknown_field", f"{target} is not a field of this import."
                )
            )
        elif not source:
            errors.append(
                field_error(f"mapping.{target}", "blank", "Choose a column or leave the field out.")
            )
        elif source not in columns:
            errors.append(
                field_error(
                    f"mapping.{target}", "unknown_column", f"The file has no column {source}."
                )
            )
    errors += [
        field_error(f"mapping.{f.name}", "required", f"Choose the column for {f.name}.")
        for f in fields.values()
        if f.required and f.name not in mapping
    ]
    if errors:
        raise ValidationFailed("The column mapping needs fixing.", errors=errors)
    before = batch_audit(batch)
    batch.mapping = mapping
    batch.status = MAPPED
    for counter in (
        "rows_received",
        "rows_valid",
        "rows_imported",
        "rows_duplicate",
        "rows_rejected",
        "rows_unmapped",
        "rows_review",
    ):
        setattr(batch, counter, 0)  # a new mapping invalidates an earlier validation
    batch.updated_by = ctx.actor.user_id
    _save(ctx.session, batch)
    return _outcome(ctx, batch, action="import.map", event="IMPORT_MAPPED", before=before)


# ----------------------------------------------------------------------------------------------- validate
def _validate(ctx: CommandContext, data: BatchIdInput) -> Outcome[BatchRead]:
    batch = _lock_batch(ctx, data.batch_id)
    BATCH_STATES.apply(batch.status, "validate")
    before = batch_audit(batch)
    batch.updated_by = ctx.actor.user_id
    _save(ctx.session, batch)
    tenant_id, batch_id = str(ctx.actor.tenant_id), str(batch.id)

    def send() -> None:
        enqueue(VALIDATE_IMPORT, tenant_id=tenant_id, batch_id=batch_id)

    return _outcome(
        ctx,
        batch,
        action="import.validate",
        event="IMPORT_VALIDATION_REQUESTED",
        before=before,
        after_commit=(send,),
    )


# ------------------------------------------------------------------------------------------------ cancel
def _cancel(ctx: CommandContext, data: BatchIdInput) -> Outcome[BatchRead]:
    batch = _lock_batch(ctx, data.batch_id)
    target = BATCH_STATES.apply(batch.status, "cancel")
    before = batch_audit(batch)
    batch.status = target
    batch.updated_by = ctx.actor.user_id
    _save(ctx.session, batch)
    return _outcome(ctx, batch, action="import.cancel", event="IMPORT_CANCELLED", before=before)


# ------------------------------------------------------------------------------------------------ confirm
def _confirm(ctx: CommandContext, data: ConfirmInput) -> Outcome[BatchRead]:
    """Explicit confirmation (INV-IMP-06): any row that is not valid needs `accept_partial: true`."""
    batch = _lock_batch(ctx, data.batch_id)
    target = BATCH_STATES.apply(batch.status, "confirm")
    not_valid = batch.rows_received - batch.rows_valid
    if batch.rows_received == 0:
        raise ValidationFailed(
            "The file has no rows to import.",
            errors=[field_error("body", "empty", "Upload a file that has rows.")],
        )
    if not_valid > 0 and not data.body.accept_partial:
        message = (
            f"{not_valid} of {batch.rows_received} rows will not be imported (duplicates, errors, "
            "unmapped or needing review). Confirm the partial import to import the valid rows only."
        )
        raise ValidationFailed(
            message, errors=[field_error("accept_partial", "partial_import", message)]
        )
    before = batch_audit(batch)
    batch.status = target
    batch.confirmed_at = datetime.now(UTC)
    batch.updated_by = ctx.actor.user_id
    _save(ctx.session, batch)
    tenant_id, batch_id = str(ctx.actor.tenant_id), str(batch.id)

    def send() -> None:
        enqueue(RUN_IMPORT, tenant_id=tenant_id, batch_id=batch_id)

    return _outcome(
        ctx,
        batch,
        action="import.confirm",
        event="IMPORT_CONFIRMED",
        before=before,
        after_extra={"accept_partial": data.body.accept_partial},
        after_commit=(send,),
    )


def _cmd(name: str, path: str, handler: Any, **kw: Any) -> Command[Any, Any]:
    return register(Command(name, path, QUALITY, handler, **kw))


CREATE_IMPORT = _cmd("imports.create", "/imports", _create)
MAP_IMPORT = _cmd("imports.map", "/imports/{id}/map", _map)
VALIDATE_IMPORT_COMMAND = _cmd("imports.validate", "/imports/{id}/validate", _validate)
CANCEL_IMPORT = _cmd("imports.cancel", "/imports/{id}/cancel", _cancel)
CONFIRM_IMPORT = _cmd(
    "imports.confirm", "/imports/{id}/confirm", _confirm, idempotency=IDEMPOTENCY_REQUIRED
)
