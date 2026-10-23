"""TEMPORARY parity guard: the O2C package must describe exactly what the ORM models store.

The package replaced the hand-written ORM models and ingestion schemas as the
source of truth for the 19 tables.  Until those models are deleted (workstream B
removes this file together with them), this test makes sure the conversion lost
nothing: same tables, same columns in the same order, same types, same keys, and
the same raw field names as the old ingestion aliases.
"""

import sqlalchemy as sa

from src.db import models  # noqa: F401  (registers the tables on Base.metadata)
from src.db.base import Base
from src.ingestion import schemas
from src.ingestion.jsonl_loader import ENTITY_MAP


def _package_type(column: sa.Column) -> str:
    t = column.type
    if isinstance(t, sa.Numeric):
        return f"decimal({t.precision},{t.scale})"
    if isinstance(t, sa.Boolean):
        return "boolean"
    if isinstance(t, sa.Date):
        return "date"
    if isinstance(t, sa.Time):
        return "time"
    if isinstance(t, sa.DateTime) or t.__class__.__name__ == "TIMESTAMP":
        return "timestamp"
    if isinstance(t, sa.String):
        return "text"
    raise AssertionError(f"unmapped ORM type {t!r}")


def test_same_tables(o2c_package):
    orm_tables = {t for t in Base.metadata.tables if t != "rag_embeddings"}
    assert {t.table for t in o2c_package.tables} == orm_tables


def test_same_columns_types_and_keys(o2c_package):
    for table in o2c_package.tables:
        orm = Base.metadata.tables[table.table]
        assert list(table.column_names) == [c.name for c in orm.columns], table.table
        assert [str(c.sql_type) for c in table.columns] == [_package_type(c) for c in orm.columns], table.table
        assert list(table.primary_key) == [c.name for c in orm.primary_key.columns], table.table


def test_same_raw_field_names_as_the_ingestion_aliases(o2c_package):
    for directory, (model, schema) in ENTITY_MAP.items():
        table = o2c_package.table(model.__tablename__)
        assert table.source.path == directory
        aliases = {name: field.alias for name, field in schema.model_fields.items()}
        assert {c.name: c.source for c in table.columns} == aliases, table.table


def test_old_schema_classes_are_still_importable_for_the_comparison():
    assert schemas.BillingDocumentHeaderSchema is not None
