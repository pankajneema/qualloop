"""Core table definitions for `outbox_events` (DATA_MODEL 1.5). Written without RETURNING; see writer.py."""

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

outbox_events = Table(
    "outbox_events",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("created_by", PG_UUID(as_uuid=True)),
    Column("updated_by", PG_UUID(as_uuid=True)),
    Column("event_id", PG_UUID(as_uuid=True), nullable=False),
    Column("aggregate_type", Text, nullable=False),
    Column("aggregate_id", PG_UUID(as_uuid=True), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("processed_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
)
