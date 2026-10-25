"""Consistency of dataset definitions and the /api/graph/schema contract."""

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.datasets import get_package, load_package
from src.domain.graph_registry import (
    UnknownDatasetError,
    get_dataset,
    load_dataset,
)
from src.domain.graph_schema import EdgeTypeDef, GraphDataset, NodeTypeDef
from src.main import app
from tests.conftest import TOY_DIR

CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ACCENTS = {
    "red", "orange", "yellow", "green", "mint", "teal", "cyan",
    "blue", "indigo", "purple", "pink", "brown", "gray",
}


@pytest.fixture(params=["o2c", "toy_library"])
def dataset(request) -> GraphDataset:
    """Every definition is checked for the shipped package and for the unrelated toy package."""
    if request.param == "toy_library":
        return load_package(TOY_DIR).graph_dataset()
    return load_dataset(request.param)


# ---------------------------------------------------------------------------
# Definition consistency (every dataset)
# ---------------------------------------------------------------------------


def test_every_edge_endpoint_is_a_registered_node_type(dataset):
    known = set(dataset.node_keys)
    for e in dataset.edge_types:
        assert e.source in known, e
        assert e.target in known, e


def test_every_flow_references_registered_types(dataset):
    nodes = set(dataset.node_keys)
    edge_keys = {e.key for e in dataset.edge_types}
    assert dataset.flows
    for flow in dataset.flows:
        assert flow.node_types and flow.edge_types
        assert set(flow.node_types) <= nodes, flow.id
        assert set(flow.edge_types) <= edge_keys, flow.id


def test_flow_edges_connect_flow_nodes(dataset):
    """Each flow edge type has at least one definition inside the flow's nodes."""
    for flow in dataset.flows:
        nodes = set(flow.node_types)
        for key in flow.edge_types:
            assert any(
                e.source in nodes and e.target in nodes for e in dataset.edge_types_for(key)
            ), (flow.id, key)


def test_entity_hints_target_registered_types(dataset):
    known = set(dataset.node_keys)
    assert all(node in known for _, node in dataset.entity_column_hints)


def test_presentation_metadata_is_well_formed(dataset):
    for n in dataset.node_types:
        assert n.label and n.plural and n.description
        assert CATEGORY.match(n.category), n.key
        assert n.accent is None or n.accent in ACCENTS
        assert 2 <= len(n.display_properties) <= 5, n.key
    assert any(n.is_primary for n in dataset.node_types)


def test_main_documents_have_distinct_accents(dataset):
    accents = [n.accent for n in dataset.node_types if n.accent]
    assert len(accents) == len(set(accents))


# ---------------------------------------------------------------------------
# Definitions line up with the package's tables (every dataset)
# ---------------------------------------------------------------------------


def _package_columns(dataset: GraphDataset, table: str) -> set:
    package = load_package(TOY_DIR) if dataset.id == "toy_library" else get_package(dataset.id)
    assert package.has_table(table), f"unknown table {table}"
    return set(package.table(table).column_names)


def test_node_columns_exist_in_the_package_tables(dataset):
    for n in dataset.node_types:
        cols = _package_columns(dataset, n.table)
        assert set(n.id_columns) <= cols, n.key
        assert set(n.detail_columns) <= cols, n.key
        assert set(n.display_properties) <= set(n.detail_keys), n.key
        if n.label_column:
            assert n.label_column in cols, n.key
        if n.label_lookup:
            lk = n.label_lookup
            lookup_cols = _package_columns(dataset, lk.table)
            assert {lk.match_column, lk.label_column} <= lookup_cols, n.key
            assert {c for c, _ in lk.filters} <= lookup_cols, n.key


def test_edge_columns_exist_in_the_package_tables(dataset):
    for e in dataset.edge_types:
        cols = _package_columns(dataset, e.table)
        used = set(e.source_columns) | set(e.target_columns) | set(e.not_null)
        assert used <= cols, (e.key, e.source, e.target)


def test_entity_refs_point_at_package_columns(dataset):
    for ref in dataset.entity_refs:
        assert ref.column in _package_columns(dataset, ref.table), ref


# ---------------------------------------------------------------------------
# Registry loading and validation
# ---------------------------------------------------------------------------


def test_default_dataset_is_o2c():
    assert get_dataset().id == "o2c"


def test_unknown_dataset_is_rejected():
    with pytest.raises(UnknownDatasetError):
        load_dataset("nope")
    with pytest.raises(UnknownDatasetError):
        load_dataset("../etc")


def _node(key: str, **kw) -> NodeTypeDef:
    return NodeTypeDef(
        key=key, label=key, plural=key + "s", description=key,
        table="t_" + key.lower(), **{"id_columns": ("id",), **kw},
    )


def _edge(key: str, source: str, target: str) -> EdgeTypeDef:
    return EdgeTypeDef(
        key=key, label=key.lower(), source=source, target=target, description=key,
        table="t_edges", alias="e", source_columns=("a",), target_columns=("b",),
    )


def test_dataset_rejects_edge_with_unregistered_endpoint():
    with pytest.raises(ValidationError):
        GraphDataset(
            id="x", name="X", description="x",
            node_types=(_node("A"),), edge_types=(_edge("LINKS", "A", "Missing"),),
        )


def test_dataset_rejects_flow_with_unregistered_types():
    from src.domain.graph_models import FlowDefinition

    base = {
        "id": "x", "name": "X", "description": "x",
        "node_types": (_node("A"), _node("B")), "edge_types": (_edge("LINKS", "A", "B"),),
    }
    GraphDataset(**base, flows=(FlowDefinition(id="f", label="f", description="f",
                                               node_types=["A", "B"], edge_types=["LINKS"]),))
    with pytest.raises(ValidationError):
        GraphDataset(**base, flows=(FlowDefinition(id="f", label="f", description="f",
                                                   node_types=["A", "Z"], edge_types=["LINKS"]),))
    with pytest.raises(ValidationError):
        GraphDataset(**base, flows=(FlowDefinition(id="f", label="f", description="f",
                                                   node_types=["A"], edge_types=["NOPE"]),))


def test_definitions_reject_unsafe_identifiers():
    with pytest.raises(ValidationError):
        NodeTypeDef(key="A", label="A", plural="As", description="A",
                    table="t; DROP TABLE x", id_columns=("id",))
    with pytest.raises(ValidationError):
        NodeTypeDef(key="A'", label="A", plural="As", description="A",
                    table="t", id_columns=("id",))
    with pytest.raises(ValidationError):
        NodeTypeDef(key="A", label="A", plural="As", description="A",
                    table="t", id_columns=("id", "id"))
    with pytest.raises(ValidationError):
        NodeTypeDef(key="A", label="A", plural="As", description="A",
                    table="t", id_columns=())
    with pytest.raises(ValidationError):
        _node("A", category="Not A Label")


def test_ids_may_have_any_number_of_columns():
    line = _node("Line", id_columns=("order_no", "item_no", "line_no"))
    assert line.id_columns == ("order_no", "item_no", "line_no")


def test_an_edge_endpoint_must_have_as_many_columns_as_the_id_it_refers_to():
    nodes = (_node("Order"), _node("Line", id_columns=("order_no", "line_no")))

    def edge(target_columns: tuple[str, ...]) -> EdgeTypeDef:
        return EdgeTypeDef(
            key="HAS_LINE", label="has line", source="Order", target="Line", description="x",
            table="t_line", alias="l", source_columns=("order_no",), target_columns=target_columns,
        )

    GraphDataset(id="x", name="X", description="x", node_types=nodes, edge_types=(edge(("order_no", "line_no")),))
    with pytest.raises(ValidationError, match="target_columns has 1 column"):
        GraphDataset(id="x", name="X", description="x", node_types=nodes, edge_types=(edge(("line_no",)),))


def test_traversal_stops_at_types_marked_terminal_whatever_their_category():
    nodes = (
        _node("Doc", category="party"),  # a category alone changes nothing
        _node("Ref", category="lookup_data", terminal=True),
    )
    dataset = GraphDataset(id="x", name="X", description="x", node_types=nodes, edge_types=(_edge("USES", "Doc", "Ref"),))
    assert dataset.terminal_node_keys == ["Ref"]


# ---------------------------------------------------------------------------
# GET /api/graph/schema
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_schema_endpoint_matches_contract(client):
    res = client.get("/api/graph/schema")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"domain", "node_types", "edge_types", "flows"}
    # Additive contract: everything the original payload had, plus new fields.
    assert {
        "id": "o2c",
        "name": "Order to Cash",
        "description": "Sales orders through delivery, billing and payment.",
    }.items() <= body["domain"].items()
    assert {"version", "is_default"} <= set(body["domain"])
    assert body["domain"]["is_default"] is False

    node_fields = {
        "key", "label", "plural", "description", "category",
        "accent", "icon", "is_primary", "display_properties",
    }
    assert body["node_types"]
    for n in body["node_types"]:
        assert node_fields <= set(n)
        assert set(n) - node_fields <= {"value_labels"}
        assert CATEGORY.match(n["category"])
        assert n["accent"] is None or n["accent"] in ACCENTS
        assert isinstance(n["is_primary"], bool)
        assert isinstance(n["display_properties"], list)

    edge_fields = {"key", "label", "source", "target", "description"}
    for e in body["edge_types"]:
        assert set(e) == edge_fields

    for f in body["flows"]:
        assert set(f) == {"id", "label", "description", "node_types", "edge_types"}


def test_schema_covers_every_type_other_endpoints_can_emit(client):
    body = client.get("/api/graph/schema").json()
    node_keys = {n["key"] for n in body["node_types"]}
    edge_keys = {e["key"] for e in body["edge_types"]}
    ds = get_dataset()
    assert node_keys == set(ds.node_keys)
    assert edge_keys == {e.key for e in ds.edge_types}
    for e in body["edge_types"]:
        assert e["source"] in node_keys and e["target"] in node_keys


def test_schema_example_payloads(client):
    body = client.get("/api/graph/schema").json()
    sales_order = next(n for n in body["node_types"] if n["key"] == "SalesOrder")
    assert sales_order["label"] == "Sales order"
    assert sales_order["plural"] == "Sales orders"
    assert sales_order["is_primary"] is True
    placed = next(e for e in body["edge_types"] if e["key"] == "PLACED")
    assert (placed["source"], placed["target"], placed["label"]) == (
        "Customer", "SalesOrder", "placed",
    )


def test_flows_endpoint_still_matches_schema_flows(client):
    flows = client.get("/api/graph/flows").json()["flows"]
    assert flows == client.get("/api/graph/schema").json()["flows"]
    assert {f["id"] for f in flows} == {
        "sales", "fulfillment", "billing", "financial", "customer_master", "full_o2c",
    }


def test_unknown_flow_is_404(client):
    assert client.get("/api/graph/flow", params={"flow_id": "nope"}).status_code == 404


def test_app_title():
    assert app.title == "GraphSense"
