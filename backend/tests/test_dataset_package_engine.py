"""The package engine: strict loading, validation, hashing and the registry.

Everything here runs on the toy package, so it also shows the engine does not
depend on any particular dataset.
"""

import re
import shutil
from pathlib import Path

import pytest

from src.datasets import (
    PackageError,
    load_package,
    validate_package,
)
from src.datasets.loader import load_yaml_text
from src.datasets.models import derive_column_name, parse_type
from tests.conftest import TOY_DATA_DIR, TOY_DIR

# ---------------------------------------------------------------------------
# Strict YAML loading
# ---------------------------------------------------------------------------


def test_codes_that_yaml_would_reinterpret_survive_as_strings():
    data = load_yaml_text("{a: Y, b: N, c: NO, d: '05', e: 05, f: 0003, g: on, h: 1.0, i: 0x1F, j: 1e3, k: yes, l: Off}")
    assert data == {
        "a": "Y", "b": "N", "c": "NO", "d": "05", "e": "05", "f": "0003",
        "g": "on", "h": "1.0", "i": "0x1F", "j": "1e3", "k": "yes", "l": "Off",
    }


def test_only_true_false_and_null_are_not_strings():
    data = load_yaml_text("{t: true, f: false, n: null, tilde: ~, empty: }")
    assert data == {"t": True, "f": False, "n": None, "tilde": None, "empty": None}


def test_a_value_set_with_awkward_codes_loads_intact(package_copy):
    path = package_copy(
        edits={"semantics/value_sets.yaml": ("{NO: Norway,", "{NO: Norway, N: North, Y: Yes, '0003': Company,")}
    )
    pkg = load_package(path)
    assert pkg.semantics.value_sets["country_code"].values["NO"] == "Norway"
    assert {"N", "Y", "0003"} <= set(pkg.semantics.value_sets["country_code"].values)


def test_duplicate_keys_are_rejected():
    with pytest.raises(Exception, match="duplicate key"):
        load_yaml_text("a: 1\na: 2\n")


def test_python_object_tags_are_rejected():
    with pytest.raises(Exception, match="could not determine a constructor"):
        load_yaml_text("a: !!python/object/apply:os.system ['echo no']\n")


def test_numbers_in_yaml_are_converted_by_the_declared_field_type(package_copy):
    path = package_copy(edits={"semantics/vocabulary.yaml": ("min_similarity: 0.35", "min_similarity: 0.5")})
    assert load_package(path).vocabulary.min_similarity == 0.5


# ---------------------------------------------------------------------------
# Structural validation (negative tests)
# ---------------------------------------------------------------------------


def _error_text(path: Path) -> str:
    with pytest.raises(PackageError) as info:
        load_package(path)
    return str(info.value)


def test_unknown_key_is_rejected(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("grain: book", "grain: book\nwidth: 3")})
    assert "width" in _error_text(path)


def test_unknown_key_in_a_column_is_rejected(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("role: id, description: International", "role: id, colour: red, description: International")})
    assert "colour" in _error_text(path)


def test_duplicate_column_is_rejected(package_copy):
    path = package_copy(edits={"tables/authors.yaml": ("  - {source: fullName,", "  - {source: authorId, name: author_id2, type: text}\n  - {source: fullName, name: author_id2,")})
    assert "duplicate column" in _error_text(path)


def test_two_columns_from_one_source_field_are_rejected(package_copy):
    path = package_copy(edits={"tables/authors.yaml": ("  - {source: fullName,", "  - {source: authorId, name: other, type: text}\n  - {source: fullName,")})
    assert "more than one column" in _error_text(path)


def test_bad_type_is_rejected(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("source: pageCount, type: integer", "source: pageCount, type: varchar(20)")})
    assert "unknown column type" in _error_text(path)


def test_bad_decimal_precision_is_rejected():
    with pytest.raises(ValueError, match="precision"):
        parse_type("decimal(4,9)")


def test_unsafe_names_are_rejected(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("source: isbn, type: text", 'source: isbn, name: "isbn; DROP TABLE books", type: text')})
    assert "invalid column name" in _error_text(path)


def test_primary_key_must_name_columns(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("primary_key: [isbn]", "primary_key: [isbm]")})
    assert "primary key column 'isbm'" in _error_text(path)


def test_unknown_normaliser_is_rejected(package_copy):
    path = package_copy(edits={"tables/loans.yaml": ("normalize: [strip_leading_zeros]", "normalize: [reverse]")})
    assert "unknown normaliser" in _error_text(path)


def test_normalising_a_non_text_column_is_rejected(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("source: pageCount, type: integer,", "source: pageCount, type: integer, normalize: [trim],")})
    assert "text columns only" in _error_text(path)


def test_absolute_or_parent_paths_are_rejected(package_copy):
    for bad in ("/etc", "../outside", "a/../b"):
        path = package_copy(edits={"tables/books.yaml": ("source: {path: books}", f"source: {{path: {bad}}}")})
        assert "relative path" in _error_text(path)
        shutil.rmtree(path)


def test_absolute_default_subdir_is_rejected(package_copy):
    path = package_copy(edits={"package.yaml": ("default_subdir: toy-library", "default_subdir: /srv/data")})
    assert "relative path" in _error_text(path)


def test_package_id_must_match_the_directory(package_copy):
    path = package_copy(edits={"package.yaml": ("id: toy_library", "id: other")})
    assert "must equal the directory name" in _error_text(path)


def test_table_file_must_be_named_after_its_table(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("table: books", "table: tomes")})
    assert "name the file tomes.yaml" in _error_text(path)


def test_unsupported_format_version_is_rejected(package_copy):
    path = package_copy(edits={"package.yaml": ("package_format: 1", "package_format: 2")})
    assert "unsupported package_format" in _error_text(path)


def test_tables_do_not_belong_in_the_manifest(package_copy):
    path = package_copy(edits={"package.yaml": ("includes:", "tables: []\nincludes:")})
    assert "belongs in its own file" in _error_text(path)


def test_includes_cannot_escape_the_package(package_copy, tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text("table: x\n")
    path = package_copy(edits={"package.yaml": ("includes: [", "includes: ['../outside.yaml', ")})
    # a pattern with '..' is refused outright
    assert "relative path" in _error_text(path)


def test_symlink_pointing_outside_is_refused(package_copy, tmp_path):
    outside = tmp_path / "secret.yaml"
    outside.write_text("table: secret\n")
    path = package_copy()
    (path / "tables" / "secret.yaml").symlink_to(outside)
    assert "outside the package directory" in _error_text(path)


def test_a_directory_without_manifest_is_not_a_package(tmp_path):
    with pytest.raises(PackageError, match="not a dataset package"):
        load_package(tmp_path)


def test_unknown_semantic_file_is_reported(package_copy):
    path = package_copy(edits={"semantics/mystery.yaml": "- a\n"})
    assert "no known role" in _error_text(path)


def test_all_problems_are_reported_together(package_copy):
    path = package_copy(
        edits={
            "tables/books.yaml": ("source: pageCount, type: integer", "source: pageCount, type: nope"),
            "tables/members.yaml": ("primary_key: [member_id]", "primary_key: [nope]"),
        }
    )
    text = _error_text(path)
    assert "books.yaml" in text and "members.yaml" in text


# ---------------------------------------------------------------------------
# Cross-reference validation (lint)
# ---------------------------------------------------------------------------


def _lint_errors(path: Path) -> str:
    return _error_text(path)


def test_the_toy_package_is_valid(toy_package):
    report = validate_package(toy_package)
    assert report.ok, report.errors


def test_value_set_on_a_column_must_exist(package_copy):
    path = package_copy(edits={"tables/members.yaml": ("value_set: member_tier", "value_set: member_tears")})
    assert "undefined value set 'member_tears'" in _lint_errors(path)


def test_value_set_must_apply_to_existing_columns(package_copy):
    path = package_copy(edits={"semantics/value_sets.yaml": ("applies_to: [members.tier]", "applies_to: [members.rank]")})
    assert "members.rank does not exist" in _lint_errors(path)


def test_a_column_cannot_have_two_value_sets(package_copy):
    path = package_copy(edits={"semantics/value_sets.yaml": ("applies_to: [loans.status]", "applies_to: [loans.status, members.tier]")})
    assert "several value sets" in _lint_errors(path)


def test_example_sql_must_only_touch_declared_tables(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("FROM authors a\n    JOIN books b", "FROM authors a\n    JOIN shelves b")})
    assert "undeclared table 'shelves'" in _lint_errors(path)


def test_example_sql_must_only_use_declared_columns(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("a.full_name AS author", "a.surname AS author")})
    assert "unknown column" in _lint_errors(path)


def test_example_sql_must_be_one_select(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("SELECT COUNT(*) AS open_loans FROM loans WHERE returned_at IS NULL", "DELETE FROM loans")})
    assert "must be a SELECT" in _lint_errors(path)
    path2 = package_copy(edits={"semantics/examples.yaml": ("SELECT COUNT(*) AS open_loans FROM loans WHERE returned_at IS NULL", "SELECT 1 FROM loans; SELECT 2 FROM loans")})
    shutil.rmtree(path)
    assert "exactly one statement" in _lint_errors(path2)


def test_example_sql_must_parse(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("SELECT COUNT(*) AS open_loans FROM loans WHERE returned_at IS NULL", "SELEKT COUNT(*) FROM")})
    assert "example_sql" in _lint_errors(path)


def test_example_sql_cannot_be_schema_qualified(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("FROM authors a\n    JOIN books b", "FROM public.authors a\n    JOIN books b")})
    assert "schema-qualified" in _lint_errors(path)


def test_a_golden_question_cannot_repeat_a_few_shot_question(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("question: How many loans are still open?", "question: which books have been borrowed the most")})
    assert "golden_leak" in _lint_errors(path)


def test_expected_columns_must_be_columns_of_the_query(package_copy):
    path = package_copy(edits={"semantics/examples.yaml": ("columns_include: [open_loans]", "columns_include: [closed_loans]")})
    assert "closed_loans" in _lint_errors(path)


def test_guardrail_cases_need_both_outcomes(package_copy):
    original = (TOY_DIR / "semantics" / "vocabulary.yaml").read_text(encoding="utf-8")
    rejects_only = "".join(line for line in original.splitlines(keepends=True) if "expect: allow" not in line)
    path = package_copy(edits={"semantics/vocabulary.yaml": rejects_only})
    assert "at least one allow and one reject" in _lint_errors(path)


def test_graph_must_use_existing_columns(package_copy):
    path = package_copy(edits={"graph.yaml": ("display_properties: [full_name, tier, joined_at]", "display_properties: [full_name, tier, joined_on]")})
    assert "members.joined_on does not exist" in _lint_errors(path)


def test_graph_edges_must_use_existing_columns(package_copy):
    path = package_copy(edits={"graph.yaml": ("source_columns: [member_id], target_columns: [loan_id], not_null: [member_id]", "source_columns: [member_id], target_columns: [loan_id], not_null: [reader_id]")})
    assert "loans.reader_id does not exist" in _lint_errors(path)


def test_graph_flows_must_reference_defined_types(package_copy):
    path = package_copy(edits={"graph.yaml": ("node_types: [Member, Loan, Book, Author], edge_types: [BORROWED, OF_BOOK, WROTE]", "node_types: [Member, Loan, Book, Reader], edge_types: [BORROWED, OF_BOOK, WROTE]")})
    assert "unknown node type Reader" in _lint_errors(path)


def test_suggested_question_requirements_must_be_node_types(package_copy):
    path = package_copy(edits={"semantics/suggested_questions.yaml": ("requires: [Loan]", "requires: [Borrowing]")})
    assert "unknown node type 'Borrowing'" in _lint_errors(path)


def test_relationships_must_use_existing_columns(package_copy):
    path = package_copy(edits={"semantics/relationships.yaml": ("to_columns: [isbn]", "to_columns: [isbm]")})
    assert "books.isbm does not exist" in _lint_errors(path)


def test_refs_must_point_at_existing_columns(package_copy):
    path = package_copy(edits={"tables/books.yaml": ("refs: authors.author_id", "refs: authors.writer_id")})
    assert "authors.writer_id does not exist" in _lint_errors(path)


def test_joined_item_numbers_must_be_normalised_the_same_way(package_copy):
    # loans.copy_number is an item number normalised by stripping zeros; join it to a column that is not.
    old = "description: Each loan is for one book; a book can be lent many times."
    extra = "- from_table: loans\n  from_columns: [copy_number]\n  to_table: loans\n  to_columns: [loan_id]\n"
    path = package_copy(edits={"semantics/relationships.yaml": (old, f"{old}\n{extra}")})
    assert "normalised differently" in _lint_errors(path)


def test_an_edge_endpoint_must_be_normalised_like_the_id_it_refers_to(package_copy):
    # OF_BOOK matches loans.isbn to books.isbn by exact value, so both must be stored the same way.
    old = "{source: isbn, type: text, role: reference, refs: books.isbn,"
    path = package_copy(edits={"tables/loans.yaml": (old, "{source: isbn, type: text, role: reference, normalize: [upper], refs: books.isbn,")})
    errors = _lint_errors(path)
    assert "loans.isbn refers to Book id column books.isbn but is normalised differently" in errors


def test_warnings_flag_gaps_without_failing(toy_package):
    report = validate_package(toy_package, data_dir=TOY_DATA_DIR)
    codes = {w.code for w in report.warnings}
    assert "unlabelled_code" in codes  # books.shelf_code has few short values and no value set
    assert "amount_without_currency" in codes
    assert report.ok


def test_coverage_counts(toy_package):
    c = validate_package(toy_package).coverage
    assert (c.tables, c.node_types, c.edge_types, c.flows) == (4, 4, 3, 1)
    assert c.examples == 2 and c.golden_examples == 5
    assert c.columns_with_description == c.columns


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("salesOrder", "sales_order"),
        ("lastChangeDateTime", "last_change_datetime"),
        ("organizationBpName1", "organization_bp_name1"),
        ("slsUnlmtdOvrdelivIsAllwd", "sls_unlmtd_ovrdeliv_is_allwd"),
        ("HTTPStatus", "http_status"),
        ("already_snake", "already_snake"),
    ],
)
def test_column_names_are_derived_from_source_fields(source, expected):
    assert derive_column_name(source) == expected


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


def test_content_hash_is_stable_and_ignores_layout(package_copy, toy_package):
    assert re.fullmatch(r"[0-9a-f]{64}", toy_package.content_hash)
    copy = load_package(package_copy())
    assert copy.content_hash == toy_package.content_hash  # different location, same content
    # comments and key order do not change the meaning
    reordered = package_copy(edits={
        "tables/authors.yaml": ("table: authors\n", "# a comment\ngrain: author\ntable: authors\n"),
    })
    text = (reordered / "tables" / "authors.yaml").read_text().replace("\ngrain: author\nsource", "\nsource", 1)
    (reordered / "tables" / "authors.yaml").write_text(text)
    assert load_package(reordered).content_hash == toy_package.content_hash


def test_content_hash_changes_with_the_meaning(package_copy, toy_package):
    changed = load_package(package_copy(edits={"tables/books.yaml": ("Title of the book.", "Name of the book.")}))
    assert changed.content_hash != toy_package.content_hash
    renumbered = load_package(package_copy(edits={"package.yaml": ('version: "1.0.0"', 'version: "1.0.1"')}))
    assert renumbered.content_hash != toy_package.content_hash


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------








