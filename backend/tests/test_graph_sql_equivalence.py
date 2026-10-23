"""The registry-driven repository must emit the same SQL as the original one.

The baseline was captured from the hand-written O2C repository (union query,
per-edge queries, and every public method) before the refactor.  Comments and
whitespace are normalised away; nothing else may differ.
"""

import json
from pathlib import Path

import pytest

from tests.sql_snapshot import snapshot

BASELINE = json.loads(
    (Path(__file__).parent / "fixtures" / "graph_sql_baseline.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
async def current():
    return await snapshot()


def test_baseline_covers_every_method():
    assert {"summary", "subgraph", "full:default", "full:filtered", "union_query"} <= set(BASELINE)
    assert len(BASELINE["edge_queries"]) == 11


@pytest.mark.parametrize("key", sorted(BASELINE))
async def test_sql_matches_baseline(key, current):
    assert current[key] == BASELINE[key]


async def test_union_query_is_the_concatenation_of_per_edge_queries(current):
    """Union = per-edge selects joined by UNION ALL (the shared edge set)."""
    union = current["union_query"]
    parts = union.split(" UNION ALL ")
    assert len(parts) == len(current["edge_queries"])
    assert sorted(parts) == sorted(current["edge_queries"])
