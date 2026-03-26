"""Schema ingestion module — dynamically extracts DB schema and relationships.

Replaces hardcoded DDL_SCHEMAS in training.py by introspecting the live
PostgreSQL database via information_schema.

Categories written to rag_embeddings:
  - "schema"        — one embedding per table (reconstructed DDL)
  - "relationships" — one embedding per FK constraint + full O2C chain summary
"""

from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import text

from .embeddings import content_hash, generate_embeddings, upsert_embeddings, clear_category

logger = structlog.get_logger(__name__)

# Tables to exclude from schema introspection
_EXCLUDED_TABLES = frozenset({"rag_embeddings", "_schema_migrations"})


# ---------------------------------------------------------------------------
# Dataclasses (frozen — immutable by convention per project style)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnMeta:
    column_name: str
    data_type: str
    is_nullable: bool
    column_default: Optional[str]


@dataclass(frozen=True)
class TableSchema:
    table_name: str
    columns: tuple[ColumnMeta, ...]


@dataclass(frozen=True)
class ForeignKeyRelationship:
    constraint_name: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def extract_tables(engine) -> list[TableSchema]:
    """Query information_schema.columns for all public user tables.

    Returns one TableSchema per table, sorted by table name, with columns
    ordered by ordinal_position. Excludes rag_embeddings and pg_* tables.
    """
    sql = """
        SELECT
            table_name,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name NOT LIKE 'pg_%'
        ORDER BY table_name, ordinal_position
    """
    tables: dict[str, list[ColumnMeta]] = {}

    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    for table_name, column_name, data_type, is_nullable, column_default in rows:
        if table_name in _EXCLUDED_TABLES:
            continue
        col = ColumnMeta(
            column_name=column_name,
            data_type=data_type,
            is_nullable=(is_nullable == "YES"),
            column_default=column_default,
        )
        tables.setdefault(table_name, []).append(col)

    return [
        TableSchema(table_name=name, columns=tuple(cols))
        for name, cols in sorted(tables.items())
    ]


def extract_primary_keys(engine) -> dict[str, list[str]]:
    """Return {table_name: [pk_col1, pk_col2, ...]} for all public user tables."""
    sql = """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema   = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema    = 'public'
        ORDER BY tc.table_name, kcu.ordinal_position
    """
    pks: dict[str, list[str]] = {}
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    for table_name, column_name in rows:
        pks.setdefault(table_name, []).append(column_name)

    return pks


def extract_foreign_keys(engine) -> list[ForeignKeyRelationship]:
    """Return one ForeignKeyRelationship per FK column in the public schema."""
    sql = """
        SELECT
            rc.constraint_name,
            kcu.table_name       AS source_table,
            kcu.column_name      AS source_column,
            ccu.table_name       AS target_table,
            ccu.column_name      AS target_column
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
          ON rc.constraint_name  = kcu.constraint_name
         AND rc.constraint_schema = kcu.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON rc.unique_constraint_name   = ccu.constraint_name
         AND rc.unique_constraint_schema = ccu.constraint_schema
        WHERE rc.constraint_schema = 'public'
        ORDER BY kcu.table_name, kcu.column_name
    """
    fks: list[ForeignKeyRelationship] = []
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()

    for constraint_name, source_table, source_column, target_table, target_column in rows:
        fks.append(
            ForeignKeyRelationship(
                constraint_name=constraint_name,
                source_table=source_table,
                source_column=source_column,
                target_table=target_table,
                target_column=target_column,
            )
        )

    return fks


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------


def build_ddl_string(table: TableSchema, pks: list[str]) -> str:
    """Reconstruct a CREATE TABLE statement from introspected column metadata."""
    pk_set = set(pks)
    col_lines: list[str] = []

    for col in table.columns:
        # Map information_schema type names to SQL-compatible names
        sql_type = _map_data_type(col.data_type)
        nullable = "" if col.is_nullable else " NOT NULL"
        pk_inline = " PRIMARY KEY" if (len(pks) == 1 and col.column_name in pk_set) else ""
        col_lines.append(f"    {col.column_name} {sql_type}{nullable}{pk_inline}")

    # Composite PK constraint
    if len(pks) > 1:
        pk_cols = ", ".join(pks)
        col_lines.append(f"    PRIMARY KEY ({pk_cols})")

    body = ",\n".join(col_lines)
    return f"CREATE TABLE {table.table_name} (\n{body}\n);"


def build_relationship_string(fk: ForeignKeyRelationship) -> str:
    """Build a human-readable sentence describing a single FK relationship."""
    return (
        f"Table '{fk.source_table}' column '{fk.source_column}' references "
        f"'{fk.target_table}'.'{fk.target_column}' "
        f"(constraint: {fk.constraint_name}). "
        f"JOIN: {fk.source_table}.{fk.source_column} = {fk.target_table}.{fk.target_column}"
    )


def _map_data_type(pg_type: str) -> str:
    """Map information_schema data_type to a concise SQL type name."""
    mapping = {
        "character varying": "VARCHAR(255)",
        "character": "CHAR",
        "text": "TEXT",
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "numeric": "NUMERIC(18,4)",
        "double precision": "FLOAT8",
        "real": "REAL",
        "boolean": "BOOLEAN",
        "date": "DATE",
        "time without time zone": "TIME",
        "time with time zone": "TIMETZ",
        "timestamp without time zone": "TIMESTAMP",
        "timestamp with time zone": "TIMESTAMPTZ",
        "json": "JSON",
        "jsonb": "JSONB",
        "uuid": "UUID",
        "USER-DEFINED": "VECTOR",  # pgvector type shows as USER-DEFINED
    }
    return mapping.get(pg_type, pg_type.upper())


# ---------------------------------------------------------------------------
# Ingestion orchestrator
# ---------------------------------------------------------------------------


def ingest_schema(engine) -> dict[str, int]:
    """Extract schema + relationships from DB, embed, and upsert into pgvector.

    Clears existing 'schema' and 'relationships' rows before writing so
    stale entries from dropped columns are removed.

    Returns {"schema": N, "relationships": M}.
    """
    # Clear stale data
    cleared_schema = clear_category(engine, "schema")
    cleared_rel = clear_category(engine, "relationships")
    logger.info("schema_ingestion.cleared", schema=cleared_schema, relationships=cleared_rel)

    # Extract from DB
    tables = extract_tables(engine)
    pks_map = extract_primary_keys(engine)
    fks = extract_foreign_keys(engine)
    logger.info(
        "schema_ingestion.extracted",
        tables=len(tables),
        fk_constraints=len(fks),
    )

    # --- Build schema embeddings (one per table) ---
    schema_texts: list[str] = []
    schema_metas: list[dict] = []
    for table in tables:
        pks = pks_map.get(table.table_name, [])
        ddl = build_ddl_string(table, pks)
        schema_texts.append(ddl)
        schema_metas.append({"table": table.table_name, "pk": pks})

    schema_count = 0
    if schema_texts:
        schema_embeddings = generate_embeddings(schema_texts)
        schema_items = [
            {
                "category": "schema",
                "content": txt,
                "metadata": meta,
                "embedding": emb,
                "content_hash": content_hash(f"schema:{txt}"),
            }
            for txt, emb, meta in zip(schema_texts, schema_embeddings, schema_metas)
        ]
        schema_count = upsert_embeddings(engine, schema_items)
        logger.info("schema_ingestion.schema_upserted", count=schema_count)

    # --- Build relationship embeddings (one per FK + composite O2C summary) ---
    rel_texts: list[str] = []
    rel_metas: list[dict] = []
    for fk in fks:
        rel_texts.append(build_relationship_string(fk))
        rel_metas.append(
            {
                "source_table": fk.source_table,
                "source_column": fk.source_column,
                "target_table": fk.target_table,
                "target_column": fk.target_column,
            }
        )

    # Add a full O2C chain narrative as a single high-recall relationship doc
    o2c_chain = (
        "Full O2C relationship chain: "
        "business_partners.customer = sales_order_headers.sold_to_party -> "
        "sales_order_headers.sales_order = sales_order_items.sales_order -> "
        "sales_order_items.material = products.product -> "
        "sales_order_headers.sales_order = outbound_delivery_items.reference_sd_document -> "
        "outbound_delivery_items.delivery_document = outbound_delivery_headers.delivery_document -> "
        "outbound_delivery_headers.delivery_document = billing_document_items.reference_sd_document -> "
        "billing_document_items.billing_document = billing_document_headers.billing_document -> "
        "billing_document_headers.accounting_document = "
        "journal_entry_items_accounts_receivable.accounting_document -> "
        "journal_entry_items_accounts_receivable.accounting_document = "
        "payments_accounts_receivable.clearing_accounting_document. "
        "Item number joins require REGEXP_REPLACE(col, '^0+', '') to strip leading zeros."
    )
    rel_texts.append(o2c_chain)
    rel_metas.append({"type": "full_o2c_chain"})

    rel_count = 0
    if rel_texts:
        rel_embeddings = generate_embeddings(rel_texts)
        rel_items = [
            {
                "category": "relationships",
                "content": txt,
                "metadata": meta,
                "embedding": emb,
                "content_hash": content_hash(f"relationships:{txt}"),
            }
            for txt, emb, meta in zip(rel_texts, rel_embeddings, rel_metas)
        ]
        rel_count = upsert_embeddings(engine, rel_items)
        logger.info("schema_ingestion.relationships_upserted", count=rel_count)

    return {"schema": schema_count, "relationships": rel_count}
