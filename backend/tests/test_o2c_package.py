"""The reference (order-to-cash) package: completeness, fidelity and semantics."""

import json

import pytest
from fastapi.testclient import TestClient

from src.catalog import CatalogSnapshot
from src.datasets import get_package, validate_package
from src.datasets.relationships import package_relationships
from src.domain.graph_registry import get_dataset
from src.main import app
from tests.conftest import FIXTURES

TABLES = [
    "billing_document_cancellations", "billing_document_headers", "billing_document_items",
    "business_partner_addresses", "business_partners", "customer_company_assignments",
    "customer_sales_area_assignments", "journal_entry_items_accounts_receivable",
    "outbound_delivery_headers", "outbound_delivery_items", "payments_accounts_receivable",
    "plants", "product_descriptions", "product_plants", "product_storage_locations", "products",
    "sales_order_headers", "sales_order_items", "sales_order_schedule_lines",
]


def test_the_package_has_all_19_tables_and_lints_clean(o2c_package):
    assert sorted(t.table for t in o2c_package.tables) == TABLES
    report = validate_package(o2c_package)
    assert report.errors == ()


def test_every_table_and_column_is_described(o2c_package):
    c = validate_package(o2c_package).coverage
    assert c.tables == c.tables_with_description == c.tables_with_grain == 19
    assert c.columns == c.columns_with_description


def test_most_coded_columns_have_labels(o2c_package):
    c = validate_package(o2c_package).coverage
    assert c.labelled_columns / c.coded_columns >= 0.7


def test_the_semantic_content_is_complete(o2c_package):
    c = validate_package(o2c_package).coverage
    assert c.examples == 15  # the original question/SQL pairs
    assert c.golden_examples >= 5
    assert c.glossary_entries >= 7  # the original documentation, extended
    assert c.hints >= 5
    assert c.suggested_questions >= 8
    assert c.node_types == 11 and c.edge_types == 11 and c.flows == 6
    kinds = {c.expect for c in o2c_package.vocabulary.guardrail_cases}
    assert kinds == {"allow", "reject"}


def test_the_fifteen_original_questions_are_kept(o2c_package):
    questions = {e.question for e in o2c_package.semantics.examples if e.role == "example"}
    for original in (
        "Which products are associated with the highest number of billing documents?",
        "Trace the full flow of a billing document",
        "Find sales orders that have been delivered but not billed",
        "What is the total revenue by customer?",
        "Show the complete O2C flow for a specific sales order",
        "How many sales orders, deliveries, invoices, and payments are there?",
        "What are the top selling products by quantity?",
        "Show invoices that have not been paid yet",
        "Which customers have the most sales orders?",
        "Show customer addresses",
        "What is the average order value?",
        "Show the monthly sales trend",
        "List all products with their descriptions",
        "Find incomplete O2C flows where delivery exists but no invoice",
    ):
        assert original in questions


def test_example_queries_do_not_pad_or_strip_item_numbers(o2c_package):
    for example in o2c_package.semantics.examples:
        assert "REGEXP_REPLACE" not in example.sql.upper(), example.id


def test_golden_questions_are_not_retrievable_few_shot_examples(o2c_package):
    from src.catalog import CatalogSnapshot

    snapshot = CatalogSnapshot.from_package(o2c_package)
    assert {e.role for e in snapshot.few_shot_examples()} == {"example"}
    assert all(e.role == "golden" for e in snapshot.golden_examples())
    assert not {e.id for e in snapshot.few_shot_examples()} & {e.id for e in snapshot.golden_examples()}


def test_item_numbers_are_normalised_in_every_table(o2c_package):
    normalised = sorted(
        f"{t.table}.{c.name}" for t in o2c_package.tables for c in t.columns if c.normalize == ("strip_leading_zeros",)
    )
    assert normalised == [
        "billing_document_items.billing_document_item",
        "billing_document_items.reference_sd_document_item",
        "journal_entry_items_accounts_receivable.accounting_document_item",
        "outbound_delivery_items.delivery_document_item",
        "outbound_delivery_items.reference_sd_document_item",
        "payments_accounts_receivable.accounting_document_item",
        "sales_order_items.sales_order_item",
        "sales_order_schedule_lines.sales_order_item",
        "sales_order_schedule_lines.schedule_line",
    ]
    for t in o2c_package.tables:
        for c in t.columns:
            if c.role == "item_number":
                assert c.normalize, (t.table, c.name)


def test_fields_that_are_empty_in_every_record_are_declared_ignored(o2c_package):
    assert "poBox" in o2c_package.table("business_partner_addresses").ignore
    assert "cancelledBillingDocument" in o2c_package.table("billing_document_cancellations").ignore
    assert "invoiceReference" in o2c_package.table("payments_accounts_receivable").ignore


def test_status_and_type_codes_have_labels(o2c_package):
    labels = o2c_package.value_labels()
    assert labels["sales_order_headers"]["overall_delivery_status"] == {
        "A": "Not yet delivered", "B": "Partially delivered", "C": "Completely delivered",
    }
    assert labels["billing_document_headers"]["billing_document_type"] == {"F2": "Invoice", "S1": "Cancellation"}
    assert labels["outbound_delivery_headers"]["overall_picking_status"]["C"] == "Completed"
    assert labels["business_partners"]["business_partner_category"]["2"] == "Organization"


def test_unconfirmed_labels_are_marked_and_not_served(o2c_package):
    sets = o2c_package.semantics.value_sets
    for set_id in ("product_type", "product_group", "rejection_reason"):
        assert sets[set_id].confidence == "low"
        assert sets[set_id].notes
    served = o2c_package.value_labels()
    assert "product_type" not in served["products"]
    assert "sales_document_rjcn_reason" not in served["sales_order_items"]


def test_sensitive_columns_are_marked(o2c_package):
    sensitive = sorted(f"{t.table}.{c.name}" for t in o2c_package.tables for c in t.columns if c.sensitive)
    assert "business_partner_addresses.street_name" in sensitive
    assert all(name.endswith(("created_by_user", "street_name")) for name in sensitive)


def test_relationships_agree_with_the_documented_joins(o2c_package):
    joins = {j.expression for j in package_relationships(o2c_package)}
    assert "sales_order_headers.sold_to_party = business_partners.customer" in joins
    assert "billing_document_headers.sold_to_party = business_partners.customer" in joins
    assert "billing_document_headers.accounting_document = journal_entry_items_accounts_receivable.accounting_document" in joins
    # a cleared line is the same line as in the journal entries (composite key)
    assert any(
        "payments_accounts_receivable.accounting_document = journal_entry_items_accounts_receivable.accounting_document" in j
        for j in joins
    )
    # the graph would join the customer through business_partner; the declared join wins
    assert "sales_order_headers.sold_to_party = business_partners.business_partner" not in joins


def test_the_graph_is_the_stage_one_definition(o2c_package):
    graph = o2c_package.graph_dataset()
    assert graph.node_keys == [
        "SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Invoice", "InvoiceItem",
        "JournalEntry", "Payment", "Product", "Customer", "Address",
    ]
    assert [(e.key, e.source, e.target) for e in graph.edge_types][:3] == [
        ("PLACED", "Customer", "SalesOrder"), ("HAS_ITEM", "SalesOrder", "SalesOrderItem"), ("INCLUDES", "SalesOrderItem", "Product"),
    ]
    assert [f.id for f in graph.flows] == ["sales", "fulfillment", "billing", "financial", "customer_master", "full_o2c"]
    assert graph.terminal_node_keys == ["Product", "Customer", "Address"]
    assert graph.get_node_type("Customer").label_column == "business_partner_full_name"
    assert graph.get_node_type("Product").label_lookup.filters == (("language", "EN"),)
    assert graph.get_node_type("JournalEntry").count_distinct is True
    assert any(r.table == "billing_document_items" and r.column == "reference_sd_document" and r.node_type == "Delivery" for r in graph.entity_refs)


def test_the_registry_serves_the_package(o2c_package):
    assert get_package("o2c") is get_package("o2c")
    assert get_dataset() is get_package("o2c").graph_dataset()
    assert get_dataset("o2c").version == "2.0.0"


# ---------------------------------------------------------------------------
# GET /api/graph/schema
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema():
    return TestClient(app).get("/api/graph/schema").json()


def test_schema_serves_labels_for_the_status_columns(schema):
    sales_order = next(n for n in schema["node_types"] if n["key"] == "SalesOrder")
    assert sales_order["value_labels"]["overall_delivery_status"]["C"] == "Completely delivered"
    delivery = next(n for n in schema["node_types"] if n["key"] == "Delivery")
    assert set(delivery["value_labels"]) == {"overall_goods_movement_status", "overall_picking_status", "hdr_general_incompletion_status"}
    invoice = next(n for n in schema["node_types"] if n["key"] == "Invoice")
    assert invoice["value_labels"]["billing_document_type"] == {"F2": "Invoice", "S1": "Cancellation"}


def test_schema_labels_only_cover_properties_the_type_carries(schema):
    graph = get_dataset("o2c")
    for node in schema["node_types"]:
        keys = set(graph.get_node_type(node["key"]).detail_keys)
        assert set(node["value_labels"]) <= keys, node["key"]


def test_schema_domain_has_a_version_and_is_not_the_placeholder(schema):
    assert schema["domain"]["version"] == "2.0.0"
    assert schema["domain"]["is_default"] is False


def test_schema_is_a_strict_superset_of_the_stage_one_payload(schema):
    old_node = {"key", "label", "plural", "description", "category", "accent", "icon", "is_primary", "display_properties"}
    old_edge = {"key", "label", "source", "target", "description"}
    assert {"domain", "node_types", "edge_types", "flows"} <= set(schema)
    assert {"id", "name", "description"} <= set(schema["domain"])
    assert all(old_node <= set(n) for n in schema["node_types"])
    assert all(set(e) == old_edge for e in schema["edge_types"])
    assert schema["domain"]["id"] == "o2c" and schema["domain"]["name"] == "Order to Cash"


def test_real_source_keys_are_all_accounted_for():
    """Every field of the real sample records is either stored or deliberately ignored."""
    records = json.loads((FIXTURES / "o2c_real_records.json").read_text(encoding="utf-8"))
    package = get_package("o2c")
    for table in package.tables:
        for record in records[table.source.path]:
            assert set(record) <= table.source_fields


def test_o2c_snapshot_exposes_labelled_codes(o2c_package):
    snap = CatalogSnapshot.from_package(o2c_package)
    status = snap.table("sales_order_headers").column("overall_delivery_status")
    assert status.value_labels["C"] == "Completely delivered"
    low = snap.table("products").column("product_type")
    assert low.label_confidence == "low"  # the snapshot keeps guesses, marked as such
    assert len(snap.tables) == 19 and len(snap.few_shot_examples()) == 15

