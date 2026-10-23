"""CatalogSnapshot.from_package: the catalog contract that other workstreams build against."""

import dataclasses

import pytest

from src.catalog import CatalogSnapshot, ColumnInfo, TableInfo, ValueCount

FROZEN_TYPES = (CatalogSnapshot, TableInfo, ColumnInfo, ValueCount)


def test_snapshot_describes_the_package(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    assert (snap.dataset_id, snap.name, snap.package_version) == ("toy_library", "Lending Library", "1.0.0")
    assert snap.package_hash == toy_package.content_hash
    assert snap.run_id is None and snap.source == "package"
    assert snap.hints == toy_package.semantics.hints
    assert snap.vocabulary.scope_summary == "books, authors, members and loans"


def test_all_contract_types_are_immutable():
    for cls in FROZEN_TYPES:
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen, cls.__name__


def test_snapshot_cannot_be_modified(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.name = "other"  # type: ignore[misc]


def test_tables_and_columns(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    loans = snap.table("loans")
    assert loans.grain == "loan" and loans.primary_key == ("loan_id",) and loans.node_type == "Loan"
    status = loans.column("status")
    assert (status.role, status.data_type, status.value_set, status.label_confidence) == ("status", "text", "loan_status", "high")
    assert status.value_labels == {"O": "Open", "R": "Returned", "L": "Late"}
    assert loans.column("loan_id").is_pk and not loans.column("loan_id").nullable
    assert loans.column("loaned_on").nullable is False  # required
    assert loans.column("copy_number").normalize == ("strip_leading_zeros",)
    assert [c.ordinal for c in loans.columns] == list(range(1, len(loans.columns) + 1))
    assert snap.table("books").column("price").currency_column == "price_currency"
    assert snap.table("members").column("email").sensitive is True


def test_profile_statistics_are_empty_without_a_database(toy_package):
    for table in CatalogSnapshot.from_package(toy_package).tables:
        assert table.row_count is None
        for col in table.columns:
            assert (col.null_rate, col.distinct_count, col.min_value, col.max_value) == (None, None, None, None)
            assert col.top_values == () and col.sample_values == ()


def test_relationships_combine_declared_refs_and_graph_edges(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    by_expr = {r.expression: r for r in snap.relationships}
    assert by_expr["loans.isbn = books.isbn"].kind == "declared"
    assert by_expr["loans.isbn = books.isbn"].cardinality == "many_to_one"
    assert "books.author_id = authors.author_id" in by_expr
    assert "loans.member_id = members.member_id" in by_expr
    # a join declared several ways appears once
    assert len([r for r in snap.relationships if r.expression == "loans.isbn = books.isbn"]) == 1


def test_graph_edges_add_joins_nobody_declared(package_copy):
    from src.datasets import load_package

    # drop the refs that declare the joins; the edges still imply them
    path = package_copy(edits={
        "tables/books.yaml": ("refs: authors.author_id, ", ""),
        "semantics/relationships.yaml": ("loans", "loans"),
    })
    snap = CatalogSnapshot.from_package(load_package(path))
    derived = [r for r in snap.relationships if r.kind == "graph_edge"]
    assert any(r.expression == "books.author_id = authors.author_id" for r in derived)
    assert all(r.cardinality == "many_to_one" for r in derived)


def test_glossary_gets_a_generated_sentence_for_every_normalised_column(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    entry = next(g for g in snap.glossary if g.id == "normalisation_loans")
    assert "loans.copy_number is stored without leading zeros." in entry.text
    assert "generated" in entry.tags
    assert {g.id for g in snap.glossary} >= {"lending_process", "reference_books"}


def test_golden_examples_are_kept_apart_from_few_shot_examples(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    assert {e.id for e in snap.few_shot_examples()} == {"most_borrowed_books", "books_by_author"}
    assert {e.id for e in snap.golden_examples()} == {"open_loans", "late_loans", "norwegian_books", "gold_members", "total_late_fees"}


def test_sql_schema_is_what_sql_tooling_needs(toy_package):
    schema = CatalogSnapshot.from_package(toy_package).sql_schema()
    assert schema["authors"] == {"author_id": "text", "full_name": "text", "home_country": "text", "birth_date": "date"}
    assert schema["loans"]["late_fee"] == "decimal(8,2)"


def test_hidden_raw_twin_columns_are_part_of_the_catalog(package_copy):
    from src.datasets import load_package

    path = package_copy(edits={"tables/loans.yaml": ("normalize: [strip_leading_zeros],", "normalize: [strip_leading_zeros], keep_raw: true,")})
    snap = CatalogSnapshot.from_package(load_package(path))
    raw = snap.table("loans").column("copy_number_raw")
    assert raw.hidden is True and raw.data_type == "text"


