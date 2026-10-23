"""PostgreSQL DDL generated from a dataset package.

The package is the single source of truth for the physical schema: there is no
hand-written DDL and no ORM model per dataset.  Output is deterministic (same
package, same text), and constraint and index names are derived from the table
and column names so they stay stable across runs and across schema renames.
"""

from __future__ import annotations

import hashlib
import re

from src.datasets.models import DatasetPackage, TableSpec

_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PG_IDENT_MAX = 63


def quote_ident(name: str) -> str:
    """A validated identifier in double quotes.  Names come from validated packages."""
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier {name!r}")
    return f'"{name}"'


def check_schema_name(schema: str) -> str:
    if not _SCHEMA.match(schema):
        raise ValueError(f"invalid schema name {schema!r}")
    return schema


def _constraint_name(name: str) -> str:
    """Fit ``name`` into PostgreSQL's identifier limit, keeping it unique and stable."""
    if len(name) <= _PG_IDENT_MAX:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    return f"{name[: _PG_IDENT_MAX - 9]}_{digest}"


def primary_key_name(table: str) -> str:
    return _constraint_name(f"pk_{table}")


def index_name(table: str, columns: tuple[str, ...]) -> str:
    return _constraint_name(f"ix_{table}__{'_'.join(columns)}")


def qualified(schema: str, table: str) -> str:
    return f"{quote_ident(check_schema_name(schema))}.{quote_ident(table)}"


def table_ddl(table: TableSpec, schema: str) -> str:
    """``CREATE TABLE`` for ``table`` in ``schema`` (primary key included, no secondary indexes)."""
    lines = []
    for col in table.stored_columns():
        null = "" if col.nullable else " NOT NULL"
        lines.append(f"    {quote_ident(col.name)} {col.sql_type.ddl}{null}")
    pk = ", ".join(quote_ident(c) for c in table.primary_key)
    lines.append(f"    CONSTRAINT {quote_ident(primary_key_name(table.table))} PRIMARY KEY ({pk})")
    return f"CREATE TABLE {qualified(schema, table.table)} (\n" + ",\n".join(lines) + "\n)"


def table_indexes(pkg: DatasetPackage, table: TableSpec) -> list[tuple[str, ...]]:
    """Secondary indexes of ``table``: the declared ones, then those the graph SQL looks rows up by.

    Graph SQL joins on the source and target columns of every edge and fetches
    node records by their id columns.  Each such column list (a single column,
    or ``(document, item)`` for a composite id) gets an index unless the primary
    key or an index already covers it as a prefix.
    """
    wanted: list[tuple[str, ...]] = [tuple(i) for i in table.indexes]
    lookups: dict[tuple[str, ...], None] = {}
    for edge in pkg.graph.edge_types:
        if edge.table == table.table:
            lookups[tuple(edge.source_columns)] = None
            lookups[tuple(edge.target_columns)] = None
    for node in pkg.graph.node_types:
        if node.table == table.table:
            lookups[tuple(node.id_columns)] = None
    pk = tuple(table.primary_key)
    for columns in lookups:
        covered = pk[: len(columns)] == columns or any(w[: len(columns)] == columns for w in wanted)
        if not covered:
            wanted.append(columns)
    return wanted


def index_ddl(table: TableSpec, columns: tuple[str, ...], schema: str) -> str:
    cols = ", ".join(quote_ident(c) for c in columns)
    return (
        f"CREATE INDEX {quote_ident(index_name(table.table, columns))} "
        f"ON {qualified(schema, table.table)} ({cols})"
    )


def schema_ddl(pkg: DatasetPackage, schema: str) -> list[str]:
    """All statements that create the dataset's schema, tables and indexes, in order.

    The statements carry no data and no grants; the caller runs them (one by
    one) in a transaction and applies privileges.
    """
    statements = [f"CREATE SCHEMA IF NOT EXISTS {quote_ident(check_schema_name(schema))}"]
    for table in pkg.tables:
        statements.append(table_ddl(table, schema))
    for table in pkg.tables:
        for columns in table_indexes(pkg, table):
            statements.append(index_ddl(table, columns, schema))
    return statements
