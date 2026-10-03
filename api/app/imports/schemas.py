"""Request and read models of the imports module."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, StrictBool, StringConstraints

from app.core.platform.schemas import Page, Strict

__all__ = ["Page"]

Entity = Literal["suppliers", "parts", "supplier_parts"]
PreviewStatus = Literal["valid", "duplicate", "rejected", "unmapped", "review"]
RecordStatus = Literal["imported", "duplicate", "rejected", "unmapped", "review"]


class ImportCreate(Strict):
    entity: Entity
    key: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    file_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class MapBody(Strict):
    mapping: dict[str, str]


class Confirm(Strict):
    accept_partial: StrictBool = False


class Empty(Strict):
    pass


class MapInput(BaseModel):
    batch_id: UUID
    body: MapBody


class ConfirmInput(BaseModel):
    batch_id: UUID
    body: Confirm


class BatchIdInput(BaseModel):
    """Pipeline input of a command that takes only the path id (validate, cancel)."""

    batch_id: UUID
    body: Empty


class TargetFieldRead(BaseModel):
    name: str
    required: bool


class BatchRead(BaseModel):
    id: UUID
    entity: str
    file_name: str
    file_hash: str
    status: str
    mapping: dict[str, str]
    suggested_mapping: dict[str, str]
    columns: list[str]
    target_fields: list[TargetFieldRead]
    rows_received: int
    rows_valid: int
    rows_imported: int
    rows_duplicate: int
    rows_rejected: int
    rows_unmapped: int
    rows_review: int
    started_by: UUID
    confirmed_at: datetime | None
    file_hash_seen_before: bool
    previous_batch_ids: list[UUID]
    created_at: datetime


class BatchSummary(BaseModel):
    """A line of the batch list (no file is read for it)."""

    id: UUID
    entity: str
    file_name: str
    file_hash: str
    status: str
    rows_received: int
    rows_valid: int
    rows_imported: int
    rows_duplicate: int
    rows_rejected: int
    rows_unmapped: int
    rows_review: int
    started_by: UUID
    confirmed_at: datetime | None
    created_at: datetime


class PreviewItem(BaseModel):
    row_number: int
    status: str
    reason: str | None
    source_record_id: str | None
    values: dict[str, Any]


class RecordItem(BaseModel):
    row_number: int
    status: str
    reason: str | None
    target_id: UUID | None
    source_record_id: str | None
    row_hash: str
