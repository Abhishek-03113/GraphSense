"""Measuring how well each relationship holds in the data.

For a relationship ``from_table(a, b) -> to_table(x, y)`` the *match rate* is
the share of ``from_table`` rows, among those where every join column is set,
that find at least one row in ``to_table``.  Rows whose join columns are null
do not take part in the join at all and are counted separately (``from_rows``
minus ``keyed_rows``).

*Coverage* is the opposite direction: the share of ``to_table`` rows that at
least one ``from_table`` row points at (for example, the share of orders that
were ever delivered).  Together the two numbers tell a broken link (low match
rate) from an optional one (low coverage).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from src.catalog.model import RelationshipInfo
from src.catalog.profiler import source_query
from src.datasets.ddl import qualified, quote_ident
from src.datasets.models import DatasetPackage


@dataclass(frozen=True)
class RelationshipStat:
    from_rows: int
    keyed_rows: int
    matched_rows: int
    # Reverse direction: rows of the to-table, and how many of them some from-row points at.
    to_rows: int | None = None
    referenced_rows: int | None = None

    @property
    def match_rate(self) -> float | None:
        return self.matched_rows / self.keyed_rows if self.keyed_rows else None

    @property
    def coverage(self) -> float | None:
        if not self.to_rows or self.referenced_rows is None:
            return None
        return self.referenced_rows / self.to_rows


def match_query(schema: str, pkg: DatasetPackage, rel: RelationshipInfo, cap: int) -> str:
    """SQL counting ``from_rows``, ``keyed_rows`` and ``matched_rows`` for ``rel``."""
    from_table = pkg.table(rel.from_table)
    to_ref = qualified(schema, rel.to_table)
    keyed = " AND ".join(f"f.{quote_ident(c)} IS NOT NULL" for c in rel.from_columns)
    on = " AND ".join(
        f"t.{quote_ident(b)} = f.{quote_ident(a)}" for a, b in zip(rel.from_columns, rel.to_columns, strict=True)
    )
    source = source_query(schema, from_table, rel.from_columns, cap)
    return (
        "SELECT count(*) AS from_rows, "
        f"count(*) FILTER (WHERE {keyed}) AS keyed_rows, "
        f"count(*) FILTER (WHERE {keyed} AND EXISTS (SELECT 1 FROM {to_ref} t WHERE {on})) AS matched_rows "
        f"FROM ({source}) AS f"
    )


def coverage_query(schema: str, pkg: DatasetPackage, rel: RelationshipInfo, cap: int) -> str:
    """SQL counting the ``to_table`` rows (``to_rows``) and those referenced by some from-row (``referenced_rows``)."""
    to_table = pkg.table(rel.to_table)
    from_ref = qualified(schema, rel.from_table)
    keyed = " AND ".join(f"t.{quote_ident(c)} IS NOT NULL" for c in rel.to_columns)
    on = " AND ".join(
        f"f.{quote_ident(a)} = t.{quote_ident(b)}" for a, b in zip(rel.from_columns, rel.to_columns, strict=True)
    )
    source = source_query(schema, to_table, rel.to_columns, cap)
    return (
        "SELECT count(*) AS to_rows, "
        f"count(*) FILTER (WHERE {keyed} AND EXISTS (SELECT 1 FROM {from_ref} f WHERE {on})) AS referenced_rows "
        f"FROM ({source}) AS t"
    )


def measure_relationship(
    conn: Connection, schema: str, pkg: DatasetPackage, rel: RelationshipInfo, cap: int, timeout_ms: int
) -> RelationshipStat:
    """Run :func:`match_query`.  Raises ``sqlalchemy.exc.SQLAlchemyError`` when the join cannot be evaluated."""
    conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    row = conn.execute(text(match_query(schema, pkg, rel, cap))).one()
    stat = RelationshipStat(int(row.from_rows), int(row.keyed_rows), int(row.matched_rows))
    try:
        with conn.begin_nested():
            back = conn.execute(text(coverage_query(schema, pkg, rel, cap))).one()
    except SQLAlchemyError:
        return stat  # the forward measurement stands without the reverse one
    return replace(stat, to_rows=int(back.to_rows), referenced_rows=int(back.referenced_rows))
