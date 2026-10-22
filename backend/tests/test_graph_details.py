"""Record details: properties and natural labels on nodes and entity listings."""

import datetime as dt
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.domain.graph_registry import load_dataset
from src.domain.graph_schema import LabelLookup, NodeTypeDef
from src.main import app
from src.repositories.graph_repository import GraphRepository
from src.repositories.graph_sql import GraphSqlBuilder
from src.utils.serialization import json_value

DATASET = load_dataset("o2c")
SQL = GraphSqlBuilder(DATASET)


def node(key: str) -> NodeTypeDef:
    found = DATASET.get_node_type(key)
    assert found is not None
    return found


# ---------------------------------------------------------------------------
# Registry definitions
# ---------------------------------------------------------------------------


def test_every_o2c_type_exposes_its_display_properties():
    for n in DATASET.node_types:
        assert set(n.display_properties) <= set(n.detail_keys), n.key
        assert len(n.detail_keys) == len(set(n.detail_keys)), n.key


def test_o2c_types_expose_more_than_the_headline_properties():
    for n in DATASET.node_types:
        assert n.property_columns, n.key


def test_names_come_from_the_registry():
    assert node("Customer").label_column == "business_partner_full_name"
    lookup = node("Product").label_lookup
    assert lookup is not None and lookup.label_column == "product_description"
    # The derived key is a property but not a column of the products table.
    assert "product_description" in node("Product").detail_keys
    assert "product_description" not in node("Product").detail_columns


def test_unsafe_detail_identifiers_are_rejected():
    base = dict(key="A", label="A", plural="As", description="A", table="t", id_columns=("id",))
    with pytest.raises(ValidationError):
        NodeTypeDef(**base, property_columns=("x; DROP TABLE t",))
    with pytest.raises(ValidationError):
        NodeTypeDef(**base, label_column="name'--")
    with pytest.raises(ValidationError):
        NodeTypeDef(**base, label_lookup=LabelLookup(table="d", match_column="a b", label_column="n"))
    with pytest.raises(ValidationError):
        NodeTypeDef(
            **base,
            label_lookup=LabelLookup(table="d", match_column="a", label_column="n", filters=(("l; --", "EN"),)),
        )


def test_label_sources_are_exclusive_and_need_a_plain_id():
    lookup = LabelLookup(table="d", match_column="a", label_column="n")
    base = dict(key="A", label="A", plural="As", description="A", table="t")
    with pytest.raises(ValidationError):
        NodeTypeDef(**base, id_columns=("id",), label_column="n", label_lookup=lookup)
    with pytest.raises(ValidationError):
        NodeTypeDef(**base, id_columns=("doc", "item"), label_lookup=lookup)


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------


def test_details_query_for_a_plain_id_is_one_batched_statement():
    sql, params = SQL.details_query(node("SalesOrder"), ["1", "2", "3"])
    assert sql.count("SELECT") == 1
    assert "FROM sales_order_headers t" in sql
    assert "t.sales_order = ANY(CAST(:ids AS text[]))" in sql
    assert params == {"ids": ["1", "2", "3"]}
    for column in node("SalesOrder").detail_columns:
        assert f"t.{column}" in sql


def test_details_query_for_a_composite_id_narrows_on_the_document_first():
    sql, params = SQL.details_query(node("SalesOrderItem"), ["740505-10", "740505-20", "740583-30"])
    assert "t.sales_order = ANY(CAST(:docs AS text[]))" in sql
    assert "REGEXP_REPLACE(t.sales_order_item::text, '^0+', '')" in sql
    assert params["docs"] == ["740505", "740583"]
    assert params["ids"] == ["740505-10", "740505-20", "740583-30"]


def test_details_query_keeps_one_row_per_id():
    sql, _ = SQL.details_query(node("JournalEntry"), ["9400000001"])
    assert sql.startswith("SELECT DISTINCT ON (_gs_id)")
    assert "ORDER BY _gs_id" in sql


def test_details_query_selects_the_label_column():
    sql, _ = SQL.details_query(node("Customer"), ["310000100"])
    assert "t.business_partner_full_name AS _gs_label" in sql


def test_details_query_binds_lookup_filter_values():
    sql, params = SQL.details_query(node("Product"), ["P1"])
    assert "FROM product_descriptions l" in sql
    assert "l.language = :lf0" in sql
    assert params["lf0"] == "EN"
    assert "'EN'" not in sql


def test_values_never_reach_the_sql_text():
    evil = "x'); DROP TABLE sales_order_headers; --"
    for key in ("SalesOrder", "SalesOrderItem", "Customer", "Product"):
        sql, params = SQL.details_query(node(key), [evil, f"{evil}-10"])
        assert "DROP" not in sql
        assert evil in params["ids"]


# ---------------------------------------------------------------------------
# Value serialisation
# ---------------------------------------------------------------------------


def test_json_value():
    assert json_value(Decimal("1234.5000")) == 1234.5
    assert json_value(Decimal("100.0000")) == 100
    assert isinstance(json_value(Decimal("100.0000")), int)
    assert json_value(dt.date(2025, 4, 3)) == "2025-04-03"
    assert json_value(dt.datetime(2025, 4, 3, 10, 30, tzinfo=dt.timezone.utc)) == "2025-04-03T10:30:00+00:00"
    assert json_value(dt.time(9, 5)) == "09:05:00"
    assert json_value(True) is True
    assert json_value(None) is None
    assert json_value("abc") == "abc"


# ---------------------------------------------------------------------------
# Repository behaviour against a scripted session
# ---------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self):
        return list(self._rows)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class ScriptedSession:
    """Answers statements by looking at their text; records every statement."""

    def __init__(self, edges=(), ids=(), details=None, fail_details=False):
        self.edges = list(edges)
        self.ids = list(ids)
        self.details = details or {}
        self.fail_details = fail_details
        self.statements: list[tuple[str, dict]] = []

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if "_gs_id" in sql:
            if self.fail_details:
                raise RuntimeError("column does not exist")
            table = re.search(r"\nFROM (\w+)", sql).group(1)
            wanted = set(params["ids"])
            return _Rows([r for r in self.details.get(table, []) if r["_gs_id"] in wanted])
        if sql.lstrip().startswith("SELECT DISTINCT") and "LIMIT :limit" in sql:
            return _Rows([(i,) for i in self.ids])
        return _Rows(self.edges)

    def detail_statements(self):
        return [s for s in self.statements if "_gs_id" in s[0]]


SALES_ORDER_ROW = {
    "_gs_id": "740500",
    "sold_to_party": "310000100",
    "creation_date": dt.date(2025, 1, 6),
    "total_net_amount": Decimal("1234.5000"),
    "transaction_currency": "USD",
    "overall_delivery_status": "C",
    "sales_order_type": "OR",
}
CUSTOMER_ROW = {
    "_gs_id": "310000100",
    "business_partner_full_name": "Cardenas, Parker and Avila",
    "business_partner_category": "2",
    "creation_date": dt.date(2023, 12, 3),
    "business_partner_is_blocked": False,
    "_gs_label": "Cardenas, Parker and Avila",
}


def _full(row, key):
    """Rows come back with every selected column; missing ones are NULL."""
    n = node(key)
    out = {c: None for c in n.detail_columns}
    out.update(row)
    out.setdefault("_gs_label", None)
    return out


async def test_subgraph_nodes_carry_properties_and_names_in_one_query_per_type():
    edges = [
        ("310000100", "Customer", f"74050{i}", "SalesOrder", "PLACED") for i in range(5)
    ]
    session = ScriptedSession(
        edges=edges,
        details={
            "business_partners": [_full(CUSTOMER_ROW, "Customer")],
            "sales_order_headers": [_full(SALES_ORDER_ROW, "SalesOrder")],
        },
    )
    graph = await GraphRepository(session).get_subgraph("Customer", "310000100", 1)

    by_id = {n.id: n for n in graph.nodes}
    customer = by_id["Customer:310000100"]
    assert customer.label == "Cardenas, Parker and Avila"
    assert customer.properties["business_partner_is_blocked"] is False
    assert customer.properties["creation_date"] == "2023-12-03"

    order = by_id["SalesOrder:740500"]
    assert order.label == "SalesOrder 740500"  # no natural name: label unchanged
    assert order.properties["total_net_amount"] == 1234.5
    assert order.properties["creation_date"] == "2025-01-06"
    # NULL columns are left out rather than sent as nulls.
    assert "overall_delivery_status" in order.properties
    assert "pricing_date" not in order.properties

    # Records without a row keep an empty property bag.
    assert by_id["SalesOrder:740501"].properties == {}

    # Batched: one details statement per node type, not per node.
    assert len(session.detail_statements()) == 2


async def test_failed_details_query_degrades_to_empty_properties():
    session = ScriptedSession(
        edges=[("1", "Customer", "2", "SalesOrder", "PLACED")], fail_details=True
    )
    graph = await GraphRepository(session).get_subgraph("Customer", "1", 1)
    assert len(graph.nodes) == 2
    assert all(n.properties == {} for n in graph.nodes)
    assert graph.nodes[0].label == "Customer 1"


async def test_unknown_node_types_are_left_alone():
    session = ScriptedSession()
    graph = await GraphRepository(session).get_subgraph("NotAType", "1", 1)
    assert [n.id for n in graph.nodes] == ["NotAType:1"]
    assert session.detail_statements() == []


async def test_entities_include_display_properties_and_natural_labels():
    session = ScriptedSession(
        ids=["310000100", "310000199"],
        details={"business_partners": [_full(CUSTOMER_ROW, "Customer")]},
    )
    result = await GraphRepository(session).get_entities("Customer", 50)
    first, second = result.entities

    assert first == {
        "id": "310000100",
        "label": "Cardenas, Parker and Avila",
        "business_partner_full_name": "Cardenas, Parker and Avila",
        "business_partner_category": "2",
        "creation_date": "2023-12-03",
        "business_partner_is_blocked": False,
    }
    # A record with no details still has the same keys, so table columns line up.
    assert second["label"] == "Customer 310000199"
    assert set(second) == set(first)
    assert second["business_partner_full_name"] is None
    assert len(session.detail_statements()) == 1


async def test_entities_without_rows_do_not_query_details():
    session = ScriptedSession(ids=[])
    result = await GraphRepository(session).get_entities("Invoice", 10)
    assert result.entities == []
    assert session.detail_statements() == []


async def test_entities_for_an_unknown_type_are_empty():
    result = await GraphRepository(ScriptedSession()).get_entities("NotAType", 10)
    assert result.type == "NotAType" and result.entities == []


async def test_product_description_is_a_property_and_the_label():
    row = {c: None for c in node("Product").detail_columns}
    row.update({"_gs_id": "P1", "product_type": "FERT", "_gs_label": "Trail running shoes"})
    session = ScriptedSession(ids=["P1"], details={"products": [row]})
    entity = (await GraphRepository(session).get_entities("Product", 5)).entities[0]
    assert entity["label"] == "Trail running shoes"
    assert entity["product_description"] == "Trail running shoes"
    assert entity["product_type"] == "FERT"


def test_entities_endpoint_stays_backward_compatible():
    """`id` and `label` are still strings on every entity; extra keys are additive."""
    from src.db.session import get_db_session

    session = ScriptedSession(
        ids=["740500"], details={"sales_order_headers": [_full(SALES_ORDER_ROW, "SalesOrder")]}
    )

    async def fake_session():
        yield session

    app.dependency_overrides[get_db_session] = fake_session
    try:
        res = TestClient(app).get("/api/graph/entities/SalesOrder", params={"limit": 5})
    finally:
        app.dependency_overrides.pop(get_db_session, None)
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "SalesOrder"
    entity = body["entities"][0]
    assert isinstance(entity["id"], str) and isinstance(entity["label"], str)
    assert entity["total_net_amount"] == 1234.5
    assert entity["creation_date"] == "2025-01-06"
    assert entity["overall_delivery_status"] == "C"
