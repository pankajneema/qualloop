"""ORM mapping of the import tables (DATA_MODEL section 7). `import_records` is append-only."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base
from app.core.models import _Std as Std


class ImportBatch(Std, Base):
    __tablename__ = "import_batches"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    entity: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(Text)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    rows_received: Mapped[int] = mapped_column(server_default=text("0"))
    rows_valid: Mapped[int] = mapped_column(server_default=text("0"))
    rows_imported: Mapped[int] = mapped_column(server_default=text("0"))
    rows_duplicate: Mapped[int] = mapped_column(server_default=text("0"))
    rows_rejected: Mapped[int] = mapped_column(server_default=text("0"))
    rows_unmapped: Mapped[int] = mapped_column(server_default=text("0"))
    rows_review: Mapped[int] = mapped_column(server_default=text("0"))
    started_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRecord(Std, Base):
    __tablename__ = "import_records"

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenants.id"))
    batch_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    row_number: Mapped[int] = mapped_column()
    row_hash: Mapped[str] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
