"""Capture the SQL emitted by ``GraphRepository`` without a database.

``snapshot()`` drives every public repository method against a recording
session and returns the statements in canonical form (comments stripped,
whitespace collapsed).  ``tests/fixtures/graph_sql_baseline.json`` holds the
snapshot taken from the original hand-written repository; the equivalence test
asserts that the registry-driven repository still emits the same statements.

Regenerate the baseline (only when the graph model intentionally changes)::

    python -m tests.sql_snapshot tests/fixtures/graph_sql_baseline.json
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

# The repository imports modules that read DATABASE_DSN at import time.
os.environ.setdefault("DATABASE_DSN", "postgresql+asyncpg://u:p@localhost:5432/unused")

from src.repositories.graph_repository import GraphRepository  # noqa: E402

FLOW_IDS = [
    "sales",
    "fulfillment",
    "billing",
    "financial",
    "customer_master",
    "full_o2c",
]
NODE_TYPES = [
    "SalesOrder",
    "SalesOrderItem",
    "Delivery",
    "DeliveryItem",
    "Invoice",
    "InvoiceItem",
    "JournalEntry",
    "Payment",
    "Product",
    "Customer",
    "Address",
    "NotAType",
]

_COMMENT = re.compile(r"--[^\n]*")
_WS = re.compile(r"\s+")
_PAREN_OPEN = re.compile(r"\(\s+")
_PAREN_CLOSE = re.compile(r"\s+\)")
_COMMA = re.compile(r"\s*,\s*")
# Sub-select aliases in the sampled full-graph query are derived from the edge
# identifier (``AS _HAS_ITEM_SO``); the name has no effect on the result.
_SUBQUERY_ALIAS = re.compile(r"\) AS _\w+")


def canon(sql: str) -> str:
    """Strip comments and normalise whitespace so formatting differences vanish."""
    sql = _COMMENT.sub("", sql)
    sql = _WS.sub(" ", sql).strip()
    sql = _PAREN_OPEN.sub("(", sql)
    sql = _PAREN_CLOSE.sub(")", sql)
    sql = _COMMA.sub(",", sql)
    return _SUBQUERY_ALIAS.sub(") AS _alias", sql)


class _EmptyResult:
    def __iter__(self):
        return iter(())

    def fetchall(self) -> list:
        return []

    def scalar(self) -> int:
        return 0


class RecordingSession:
    """Stands in for ``AsyncSession``: records SQL, returns empty results."""

    def __init__(self) -> None:
        self.statements: list[list[Any]] = []

    async def execute(self, statement: Any, params: dict | None = None) -> _EmptyResult:
        self.statements.append([canon(str(statement)), dict(params or {})])
        return _EmptyResult()


async def _record(label: str, call, out: dict[str, Any]) -> None:
    session = RecordingSession()
    repo = GraphRepository(session)  # type: ignore[arg-type]
    await call(repo)
    out[label] = session.statements


async def snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {}
    await _record("summary", lambda r: r.get_summary(), out)
    await _record("subgraph", lambda r: r.get_subgraph("Invoice", "90000001", 3), out)
    for flow_id in FLOW_IDS:
        await _record(f"flow:{flow_id}", lambda r, f=flow_id: r.get_flow(f, 25), out)
    await _record("flow:unknown", lambda r: r.get_flow("nope", 25), out)
    await _record("full:default", lambda r: r.get_full_graph(20, None), out)
    await _record(
        "full:filtered",
        lambda r: r.get_full_graph(7, ["Invoice", "Customer", "JournalEntry"]),
        out,
    )
    for node_type in NODE_TYPES:
        await _record(f"entities:{node_type}", lambda r, t=node_type: r.get_entities(t, 10), out)

    repo = GraphRepository(RecordingSession())  # type: ignore[arg-type]
    out["union_query"] = canon(repo._get_edges_union_query())
    # Registry edges are keyed by a unique edge id rather than the old ad-hoc
    # query keys, so compare the list of statements in definition order.
    out["edge_queries"] = [canon(sql) for sql in repo._get_individual_edge_queries().values()]
    return out


if __name__ == "__main__":
    # The application logger writes to stdout, so the target is a file argument.
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(asyncio.run(snapshot()), fh, indent=1, sort_keys=True)
        fh.write("\n")
