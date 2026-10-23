"""Capture the SQL emitted by ``GraphRepository`` without a database.

``snapshot()`` drives every public repository method against a recording
session and returns the statements in canonical form (comments stripped,
whitespace collapsed).  ``tests/fixtures/graph_sql_baseline.json`` holds the
snapshot taken from the original hand-written repository; the equivalence test
asserts that the registry-driven repository still emits the same statements.

Regenerate a baseline (only when the graph model intentionally changes)::

    python -m tests.sql_snapshot tests/fixtures/graph_sql_baseline.json
    python -m tests.sql_snapshot tests/fixtures/graph_sql_baseline_toy_library.json \
        tests/fixtures/packages/toy_library

The second argument is a registered dataset id or a package directory.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from src.datasets import load_package
from src.domain.graph_registry import get_dataset
from src.domain.graph_schema import GraphDataset
from src.repositories.graph_repository import GraphRepository

# Fixed probe values for datasets whose baseline predates the generic choice below.
PROBES = {
    "o2c": {
        "root": ("Invoice", "90000001", 3),
        "filter": ["Invoice", "Customer", "JournalEntry"],
    },
}


def probe_for(dataset: GraphDataset) -> dict:
    if dataset.id in PROBES:
        return PROBES[dataset.id]
    keys = dataset.node_keys
    return {"root": (keys[0], "1", 3), "filter": keys[:3]}


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

    def mappings(self) -> _EmptyResult:
        return self

    def all(self) -> list:
        return []


class _Savepoint:
    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class RecordingSession:
    """Stands in for ``AsyncSession``: records SQL, returns empty results."""

    def __init__(self) -> None:
        self.statements: list[list[Any]] = []

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()

    async def execute(self, statement: Any, params: dict | None = None) -> _EmptyResult:
        self.statements.append([canon(str(statement)), dict(params or {})])
        return _EmptyResult()


async def _record(dataset: GraphDataset, label: str, call, out: dict[str, Any]) -> None:
    session = RecordingSession()
    repo = GraphRepository(session, dataset)  # type: ignore[arg-type]
    await call(repo)
    out[label] = session.statements


async def snapshot(dataset: GraphDataset | None = None) -> dict[str, Any]:
    """The statements the repository emits for ``dataset`` (default: the default dataset)."""
    dataset = dataset or get_dataset()
    probe = probe_for(dataset)
    root_type, root_id, depth = probe["root"]
    out: dict[str, Any] = {}
    await _record(dataset, "summary", lambda r: r.get_summary(), out)
    await _record(dataset, "subgraph", lambda r: r.get_subgraph(root_type, root_id, depth), out)
    for flow in dataset.flows:
        await _record(dataset, f"flow:{flow.id}", lambda r, f=flow.id: r.get_flow(f, 25), out)
    await _record(dataset, "flow:unknown", lambda r: r.get_flow("nope", 25), out)
    await _record(dataset, "full:default", lambda r: r.get_full_graph(20, None), out)
    await _record(dataset, "full:filtered", lambda r: r.get_full_graph(7, probe["filter"]), out)
    for node_type in [*dataset.node_keys, "NotAType"]:
        await _record(dataset, f"entities:{node_type}", lambda r, t=node_type: r.get_entities(t, 10), out)

    repo = GraphRepository(RecordingSession(), dataset)  # type: ignore[arg-type]
    out["union_query"] = canon(repo._get_edges_union_query())
    # Registry edges are keyed by a unique edge id rather than the old ad-hoc
    # query keys, so compare the list of statements in definition order.
    out["edge_queries"] = [canon(sql) for sql in repo._get_individual_edge_queries().values()]
    return out


def _dataset_from_argument(arg: str | None) -> GraphDataset:
    if arg is None:
        return get_dataset()
    path = Path(arg)
    if path.is_dir():
        return load_package(path).graph_dataset()
    return get_dataset(arg)


if __name__ == "__main__":
    # The application logger writes to stdout, so the target is a file argument.
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(
            asyncio.run(snapshot(_dataset_from_argument(sys.argv[2] if len(sys.argv) > 2 else None))),
            fh, indent=1, sort_keys=True,
        )
        fh.write("\n")
