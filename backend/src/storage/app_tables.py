"""Core definitions of the application-owned tables in the ``app`` schema.

The tables are created by ``migrations/schema/V20261101000001__app_core.sql``;
these definitions only describe them for queries (they are never used to create
anything).  Other workstreams add their own tables to ``app`` in their own
migrations and keep their own definitions.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

APP_SCHEMA = "app"

metadata = MetaData(schema=APP_SCHEMA)

datasets = Table(
    "datasets",
    metadata,
    Column("id", Text, primary_key=True),
    Column("package_id", Text, nullable=False),
    Column("package_version", Text, nullable=False),
    Column("package_hash", Text, nullable=False),
    Column("schema_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("active_run_id", UUID(as_uuid=False)),
    Column("previous_run_id", UUID(as_uuid=False)),
    Column("compat_views", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("dataset_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("phase", Text),
    Column("package_hash", Text),
    Column("source_fingerprint", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("table_counts", JSONB, nullable=False),
    Column("reject_counts", JSONB, nullable=False),
    Column("report", JSONB, nullable=False),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("triggered_by", Text),
)

ingestion_issues = Table(
    "ingestion_issues",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", UUID(as_uuid=False), nullable=False),
    Column("table_name", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("sample", JSONB),
    Column("count", BigInteger, nullable=False),
)

RUN_ACTIVE = ("queued", "running")
RUN_SUCCESS = ("succeeded", "succeeded_with_warnings")
