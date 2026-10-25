"""Traversal: breadth first over indexed lookups, never fanning out through shared reference records."""

import random

from src.domain.graph_registry import load_dataset
from src.domain.graph_schema import EdgeTypeDef, GraphDataset, NodeTypeDef
from src.repositories.graph_repository import GraphRepository
from src.repositories.graph_sql import GraphSqlBuilder
from tests.sql_snapshot import RecordingSession


def test_o2c_terminal_types_are_the_party_and_master_records():
    ds = load_dataset("o2c")
    assert sorted(ds.terminal_node_keys) == ["Address", "Customer", "Product"]


# ---------------------------------------------------------------------------
# Generated SQL
# ---------------------------------------------------------------------------


def test_a_hop_looks_edges_up_by_the_frontier_ids_in_both_directions():
    ds = load_dataset("o2c")
    sql, params = GraphSqlBuilder(ds).neighbours_query({"Invoice": ["90504201"]})
    param = f"ids_{ds.node_keys.index('Invoice')}"
    # Invoice is the source of HAS_ITEM, BILLED_TO and GENERATES and the target of nothing.
    assert sql.count("UNION ALL") == 2
    assert sql.count(f"bdi.billing_document::text = ANY(CAST(:{param} AS text[]))") == 1
    assert sql.count(f"bdh.billing_document::text = ANY(CAST(:{param} AS text[]))") == 2
    assert params == {param: ["90504201"]}


def test_a_composite_id_is_narrowed_on_its_leading_column():
    ds = load_dataset("o2c")
    sql, params = GraphSqlBuilder(ds).neighbours_query({"SalesOrderItem": ["740506-10"]})
    param = f"ids_{ds.node_keys.index('SalesOrderItem')}"
    assert f"soi.sales_order::text = ANY(CAST(:{param}_lead AS text[])) AND " in sql
    assert "(soi.sales_order::text || '-' || soi.sales_order_item::text)::text" in sql
    assert params == {param: ["740506-10"], f"{param}_lead": ["740506"]}


def test_edges_between_records_match_both_endpoints_and_are_ordered():
    ds = load_dataset("o2c")
    sql, _ = GraphSqlBuilder(ds).edges_between_query({"Customer": ["1"], "SalesOrder": ["2"]})
    assert sql.startswith("SELECT DISTINCT source_id, source_type, target_id, target_type, type")
    assert sql.endswith("ORDER BY source_type, source_id, target_type, target_id, type")
    assert "soh.sold_to_party::text = ANY(" in sql and "soh.sales_order::text = ANY(" in sql
    assert "soh.sold_to_party IS NOT NULL" in sql


def test_types_without_edges_need_no_statement():
    ds = load_dataset("o2c")
    assert GraphSqlBuilder(ds).neighbours_query({"NotAType": ["1"]}) == (None, {})
    assert GraphSqlBuilder(ds).edges_between_query({"Invoice": ["1"]}) == (None, {})


async def test_a_root_without_neighbours_costs_one_statement():
    session = RecordingSession()
    graph = await GraphRepository(session).get_subgraph("Invoice", "90504201", 4)  # type: ignore[arg-type]
    assert len([s for s, _ in session.statements if "_gs_id" not in s]) == 1
    assert [n.id for n in graph.nodes] == ["Invoice:90504201"]


# ---------------------------------------------------------------------------
# Behaviour, against an in-memory edge list
# ---------------------------------------------------------------------------


def _node(key: str, terminal: bool = False) -> NodeTypeDef:
    return NodeTypeDef(
        key=key, label=key, plural=f"{key}s", description=key, category="document",
        table=key.lower(), id_columns=("id",), terminal=terminal,
    )


def _edge(key: str, source: str, target: str) -> EdgeTypeDef:
    return EdgeTypeDef(
        key=key, label=key, source=source, target=target, description=key,
        table=source.lower(), alias="e", source_columns=("id",), target_columns=("ref",),
    )


class GraphSession:
    """Answers the traversal statements from a list of ``(s_id, s_type, t_id, t_type, type)`` edges."""

    def __init__(self, dataset: GraphDataset, edges):
        self.keys = dataset.node_keys
        self.edges = list(dict.fromkeys(edges))
        self.statements = 0

    def _records(self, params) -> set[tuple[str, str]]:
        return {
            (self.keys[int(name[4:])], i)
            for name, ids in params.items()
            if name.startswith("ids_") and not name.endswith("_lead")
            for i in ids
        }

    async def execute(self, statement, params=None):
        if "_gs_id" in str(statement):  # record details: none
            return _Rows()
        self.statements += 1
        records = self._records(params or {})
        if str(statement).startswith("SELECT DISTINCT"):
            rows = [e for e in self.edges if (e[1], e[0]) in records and (e[3], e[2]) in records]
            return _Rows(sorted(rows, key=lambda e: (e[1], e[0], e[3], e[2], e[4])))
        return _Rows([e for e in self.edges if (e[1], e[0]) in records or (e[3], e[2]) in records])

    def begin_nested(self):
        return _Savepoint()


class _Rows(list):
    def fetchall(self):
        return list(self)

    def mappings(self):
        return self

    def all(self):
        return list(self)


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


DOCS = GraphDataset(
    id="docs", name="Docs", description="d",
    node_types=(_node("Order"), _node("Item"), _node("Bill"), _node("Party", terminal=True)),
    edge_types=(
        _edge("HAS", "Order", "Item"), _edge("BILLS", "Bill", "Item"), _edge("PAYS", "Party", "Order"),
        _edge("OWES", "Bill", "Party"), _edge("NEXT", "Order", "Order"),
    ),
)


async def _walk(edges, root, depth, dataset=DOCS):
    session = GraphSession(dataset, edges)
    graph = await GraphRepository(session, dataset).get_subgraph(root[0], root[1], depth)  # type: ignore[arg-type]
    return {n.id for n in graph.nodes}, {(e.source, e.target, e.type) for e in graph.edges}, session


async def test_shared_records_are_reached_but_not_expanded():
    edges = [("P", "Party", "O1", "Order", "PAYS"), ("P", "Party", "O2", "Order", "PAYS")]
    nodes, _, _ = await _walk(edges, ("Order", "O1"), 5)
    assert nodes == {"Order:O1", "Party:P"}


async def test_a_shared_record_is_expanded_when_it_is_the_root():
    edges = [("P", "Party", "O1", "Order", "PAYS"), ("P", "Party", "O2", "Order", "PAYS")]
    nodes, _, _ = await _walk(edges, ("Party", "P"), 1)
    assert nodes == {"Party:P", "Order:O1", "Order:O2"}


async def test_edges_between_records_of_the_last_hop_are_returned():
    edges = [("O1", "Order", "I1", "Item", "HAS"), ("B1", "Bill", "I1", "Item", "BILLS"),
             ("O1", "Order", "O2", "Order", "NEXT"), ("O2", "Order", "I1", "Item", "HAS")]
    nodes, found, _ = await _walk(edges, ("Order", "O1"), 1)
    assert nodes == {"Order:O1", "Item:I1", "Order:O2"}
    # O2 -> I1 joins two records found by the same (last) hop.
    assert ("Order:O2", "Item:I1", "HAS") in found


async def test_the_walk_stops_when_nothing_new_is_found():
    edges = [("O1", "Order", "I1", "Item", "HAS")]
    _, _, session = await _walk(edges, ("Order", "O1"), 5)
    assert session.statements == 3  # hop 1, hop 2 (nothing new), the edges between the records


def _reference(edges, root, depth, terminal):
    """The original semantics: every simple path of at most ``depth`` hops, not passing through terminal records."""
    adjacent: dict[tuple, set] = {}
    for s_id, s_type, t_id, t_type, _ in edges:
        adjacent.setdefault((s_type, s_id), set()).add((t_type, t_id))
        adjacent.setdefault((t_type, t_id), set()).add((s_type, s_id))
    reached = {root}

    def visit(node, path, hops):
        if hops == depth or (hops > 0 and node[0] in terminal):
            return
        for nxt in adjacent.get(node, ()):
            if nxt not in path:
                reached.add(nxt)
                visit(nxt, path | {nxt}, hops + 1)

    visit(root, {root}, 0)
    nodes = {f"{t}:{i}" for t, i in reached}
    found = {(f"{e[1]}:{e[0]}", f"{e[3]}:{e[2]}", e[4]) for e in edges if (e[1], e[0]) in reached and (e[3], e[2]) in reached}
    return nodes | {f"{root[0]}:{root[1]}"}, found


async def test_breadth_first_reaches_exactly_what_the_path_walk_reached():
    rng = random.Random(7)
    pairs = [(e.key, e.source, e.target) for e in DOCS.edge_types]
    for _ in range(60):
        ids = {t: [f"{t[0]}{n}" for n in range(rng.randint(1, 5))] for t in DOCS.node_keys}
        edges = []
        for _ in range(rng.randint(0, 25)):
            key, source, target = rng.choice(pairs)
            edges.append((rng.choice(ids[source]), source, rng.choice(ids[target]), target, key))
        root_type = rng.choice(DOCS.node_keys)
        root = (root_type, rng.choice(ids[root_type]))
        depth = rng.randint(1, 5)
        expected = _reference(edges, root, depth, set(DOCS.terminal_node_keys))
        nodes, found, _ = await _walk(edges, root, depth)
        assert (nodes, found) == expected, (edges, root, depth)
