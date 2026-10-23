"""Traversal does not fan out through shared reference records."""

from src.domain.graph_registry import load_dataset
from src.domain.graph_schema import GraphDataset, NodeTypeDef
from src.repositories.graph_repository import GraphRepository
from src.repositories.graph_sql import GraphSqlBuilder
from tests.sql_snapshot import RecordingSession


def test_o2c_terminal_types_are_the_party_and_master_records():
    ds = load_dataset("o2c")
    assert sorted(ds.terminal_node_keys) == ["Address", "Customer", "Product"]


def test_traversal_filter_lists_terminal_types_and_always_expands_the_root():
    sql = GraphSqlBuilder(load_dataset("o2c")).traversal_expand_filter()
    assert sql.startswith("AND (t.depth = 0 OR t.type NOT IN (")
    for key in ("Customer", "Product", "Address"):
        assert f"'{key}'" in sql
    assert "'Invoice'" not in sql


def test_datasets_without_terminal_types_get_no_filter():
    node = NodeTypeDef(
        key="Doc", label="Doc", plural="Docs", description="d",
        category="document", table="docs", id_columns=("id",),
    )
    ds = GraphDataset(id="x", name="X", description="x", node_types=(node,), edge_types=())
    assert GraphSqlBuilder(ds).traversal_expand_filter() == ""


async def test_subgraph_query_carries_the_filter():
    session = RecordingSession()
    await GraphRepository(session).get_subgraph("Invoice", "90504201", 4)  # type: ignore[arg-type]
    statement, params = session.statements[0]
    assert "t.depth < :depth AND NOT (be.target_id || ':' || be.target_type = ANY(t.path))" in statement
    assert "AND (t.depth = 0 OR t.type NOT IN ('Product','Customer','Address'))" in statement
    assert params == {"root_id": "90504201", "root_type": "Invoice", "depth": 4}
