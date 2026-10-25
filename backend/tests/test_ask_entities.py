"""Entity extraction: result columns map to graph node ids through the dataset definition."""


from src.catalog import CatalogSnapshot
from src.intelligence.entities import EntityExtractor
from src.intelligence.models import ValidatedSql
from src.intelligence.sql.guard import SqlGuard


def projections(package, sql):
    snap = CatalogSnapshot.from_package(package)
    result = SqlGuard().validate(sql, snap, schema_name=package.schema_name)
    assert isinstance(result, ValidatedSql), getattr(result, "message", "")
    return list(result.projections)


def extract(package, sql, *data):
    entities, nodes = EntityExtractor(package).extract(projections(package, sql), data)
    assert [n.id for n in nodes] == [e.id for e in entities]
    return [e.id for e in entities]


def test_a_plain_id_column_maps_to_its_node_type(toy_package):
    ids = extract(toy_package, "SELECT b.isbn, b.title FROM books b", ("111", "A"), ("222", "B"), ("111", "A"))
    assert ids == ["Book:111", "Book:222"]  # in order, without duplicates


def test_aliases_do_not_matter(toy_package):
    assert extract(toy_package, "SELECT b.isbn AS thing, b.title AS other FROM books b", ("9", "x")) == ["Book:9"]


def test_edge_endpoint_columns_are_entities(toy_package):
    ids = extract(toy_package, "SELECT l.loan_id, l.member_id, l.isbn FROM loans l", ("L1", "M1", "I1"))
    assert ids == ["Loan:L1", "Member:M1", "Book:I1"]


def test_a_cast_still_copies_the_column(toy_package):
    assert extract(toy_package, "SELECT l.loan_id::text AS id FROM loans l", ("L9",)) == ["Loan:L9"]


def test_aggregates_and_constants_are_not_entities(toy_package):
    sql = "SELECT COUNT(*) AS book_count, 'book' AS book_kind FROM books b"
    assert extract(toy_package, sql, (3, "book")) == []


def test_a_name_like_an_id_is_not_an_entity(toy_package):
    # b.title looks nothing like an id column, and 'isbn' in an alias alone is not enough for a copied column
    assert extract(toy_package, "SELECT b.title AS isbn FROM books b", ("Dune",)) == []


def test_lineage_works_through_subqueries_and_ctes(toy_package):
    sql = "WITH t AS (SELECT isbn AS k FROM books) SELECT t.k FROM t"
    assert extract(toy_package, sql, ("55",)) == ["Book:55"]
    assert extract(toy_package, "SELECT x.k FROM (SELECT author_id AS k FROM authors) x", ("A1",)) == ["Author:A1"]


def test_computed_expressions_fall_back_to_the_name_hints(toy_package):
    # not a plain copy, not an aggregate: the package's entity_column_hints decide by column name
    sql = "SELECT UPPER(b.isbn) AS isbn_upper, b.title FROM books b"
    assert extract(toy_package, sql, ("ab1", "T")) == ["Book:ab1"]


def test_null_and_blank_values_are_skipped(toy_package):
    assert extract(toy_package, "SELECT b.isbn FROM books b", (None,), ("  ",), ("7",)) == ["Book:7"]


def test_only_the_first_hundred_rows_are_scanned(toy_package):
    data = [(str(i),) for i in range(500)]
    ids = extract(toy_package, "SELECT b.isbn FROM books b", *data)
    assert len(ids) == 100


# ---------------------------------------------------------------------------
# The reference dataset: composite ids, references and the example queries
# ---------------------------------------------------------------------------


def test_composite_ids_use_the_graph_form(o2c_package):
    sql = "SELECT soi.sales_order, soi.sales_order_item, soi.material FROM sales_order_items soi"
    # values as stored: ingestion has already normalised the item numbers
    ids = extract(o2c_package, sql, ("740506", "10", "TG11"), ("740506", "20", "TG12"))
    assert ids == [
        "SalesOrder:740506",
        "Product:TG11",
        "SalesOrderItem:740506-10",
        "Product:TG12",
        "SalesOrderItem:740506-20",
    ]


def test_composite_ids_use_stored_values_verbatim(o2c_package):
    sql = "SELECT soi.sales_order, soi.sales_order_item FROM sales_order_items soi"
    # no query-time rewriting: a value is part of the id exactly as the database returns it
    assert extract(o2c_package, sql, ("740506", "000010")) == ["SalesOrder:740506", "SalesOrderItem:740506-000010"]


def test_composite_needs_both_columns_from_the_same_row_of_the_same_table(o2c_package):
    only_item = extract(o2c_package, "SELECT soi.sales_order_item FROM sales_order_items soi", ("10",))
    assert only_item == []
    sql = (
        "SELECT a.sales_order, b.sales_order_item FROM sales_order_items a "
        "JOIN sales_order_items b ON a.sales_order = b.sales_order"
    )
    # two instances of one table: their halves must not be glued together
    assert [i for i in extract(o2c_package, sql, ("1", "2")) if i.startswith("SalesOrderItem")] == []


def test_references_and_edge_endpoints(o2c_package):
    sql = (
        "SELECT bdi.billing_document, bdi.reference_sd_document AS delivery, bdh.sold_to_party AS buyer "
        "FROM billing_document_items bdi JOIN billing_document_headers bdh ON bdh.billing_document = bdi.billing_document"
    )
    ids = extract(o2c_package, sql, ("900", "800", "3100"))
    assert ids == ["Invoice:900", "Delivery:800", "Customer:3100"]


def test_customer_columns_of_the_partner_table(o2c_package):
    sql = "SELECT bp.customer, bp.business_partner_full_name FROM business_partners bp"
    assert extract(o2c_package, sql, ("3100", "Acme")) == ["Customer:3100"]


def test_every_example_query_yields_entities_only_from_id_columns(o2c_package):
    snap = CatalogSnapshot.from_package(o2c_package)
    extractor = EntityExtractor(o2c_package)
    for example in snap.examples:
        result = SqlGuard().validate(example.sql, snap, schema_name="ds_o2c")
        columns = [p.name for p in result.projections]
        fake_row = tuple(f"v{i}" for i in range(len(columns)))
        entities, _ = extractor.extract(list(result.projections), [fake_row])
        for entity in entities:
            assert entity.type in extractor.node_types
        # counts and sums are never highlighted
        for index, p in enumerate(result.projections):
            if p.aggregate:
                assert f"v{index}" not in [e.value for e in entities], f"{example.id}.{p.name}"

