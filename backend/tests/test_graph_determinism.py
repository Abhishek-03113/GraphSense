"""Sampling queries must return the same rows in the same order on every call."""

import logging

from src.domain.graph_registry import get_dataset
from src.repositories.graph_repository import GraphRepository
from src.repositories.graph_sql import GraphSqlBuilder
from tests.sql_snapshot import RecordingSession

DATASET = get_dataset()


def test_entity_listings_are_ordered():
    sql = GraphSqlBuilder(DATASET)
    for node in DATASET.node_types:
        assert sql.entities_query(node).endswith("ORDER BY 1 LIMIT :limit"), node.key


async def _statements(call) -> list[str]:
    session = RecordingSession()
    await call(GraphRepository(session))  # type: ignore[arg-type]
    return [s for s, _ in session.statements]


async def test_flow_sampling_ranks_and_returns_in_a_total_order():
    (query,) = await _statements(lambda r: r.get_flow("full_o2c", 10))
    assert "PARTITION BY source_type ORDER BY source_id,target_id,type" in query
    assert query.endswith("ORDER BY source_type,source_id,target_id,type")


async def test_full_graph_sampling_orders_every_block_and_the_result():
    (query,) = await _statements(lambda r: r.get_full_graph(5, None))
    blocks = query.count("LIMIT :limit")
    assert blocks == len(DATASET.edge_types)
    assert query.count("ORDER BY source_id,target_id LIMIT :limit") == blocks
    assert query.endswith("ORDER BY type,source_id,target_id")


def test_subgraph_edges_are_ordered():
    query, _ = GraphSqlBuilder(DATASET).edges_between_query({"Invoice": ["1"], "Customer": ["2"]})
    assert query.endswith("ORDER BY source_type, source_id, target_type, target_id, type")


async def test_flow_sorts_at_most_limit_rows_per_edge_definition():
    (query,) = await _statements(lambda r: r.get_flow("full_o2c", 10))
    flow = DATASET.get_flow("full_o2c")
    blocks = sum(len(DATASET.edge_types_for(k)) for k in dict.fromkeys(flow.edge_types))
    assert query.count("ORDER BY source_id,target_id,type LIMIT :limit") == blocks


async def test_flow_runs_a_single_query_at_any_log_level():
    repo_logger = logging.getLogger("src.repositories.graph_repository")
    original = repo_logger.level
    try:
        for level in (logging.INFO, logging.DEBUG):
            repo_logger.setLevel(level)
            assert len(await _statements(lambda r: r.get_flow("sales", 5))) == 1
    finally:
        repo_logger.setLevel(original)
