"""Core table definition for `activity_log` (DATA_MODEL 1.4). Append-only; written without RETURNING."""

from sqlalchemy import Column, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

activity_log = Table(
    "activity_log",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("created_by", PG_UUID(as_uuid=True)),
    Column("updated_by", PG_UUID(as_uuid=True)),
    Column("object_type", Text, nullable=False),
    Column("object_id", PG_UUID(as_uuid=True), nullable=False),
    Column("action", Text, nullable=False),
    Column("before", JSONB(none_as_null=True)),
    Column("after", JSONB(none_as_null=True)),
    Column("reason", Text),
    Column("actor_type", Text, nullable=False),
    Column("actor_id", PG_UUID(as_uuid=True)),
    Column("session_id", PG_UUID(as_uuid=True)),
    Column("ip", INET),
)
