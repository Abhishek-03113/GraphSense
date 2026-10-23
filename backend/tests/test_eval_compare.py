"""Comparing result sets: order, column names, float noise and types do not matter; content does."""

import datetime as dt
from decimal import Decimal

import pytest

from src.intelligence.eval.compare import cells_equal, compare_results, normalise_cell


def test_row_order_does_not_matter():
    assert compare_results([(1, "a"), (2, "b")], [(2, "b"), (1, "a")]).equal


def test_column_order_does_not_matter_and_names_are_not_even_seen():
    ref = [("North", 10), ("South", 20)]
    cand = [(10, "North"), (20, "South")]
    result = compare_results(ref, cand)
    assert result.equal and result.mapping == (1, 0)


def test_numbers_match_across_types_and_float_noise():
    assert compare_results([(Decimal("12.50"),)], [(12.5,)]).equal
    assert compare_results([(0.1 + 0.2,)], [(0.3,)]).equal
    assert compare_results([(3,)], [("3.00",)]).equal
    assert not compare_results([(1.0,)], [(1.1,)]).equal


def test_tolerance_is_relative_for_large_numbers():
    assert compare_results([(1_000_000.0,)], [(1_000_000.4,)]).equal
    assert not compare_results([(1_000_000.0,)], [(1_001_000.0,)]).equal


def test_dates_and_timestamps_name_the_same_moment():
    assert compare_results([(dt.date(2025, 4, 2),)], [("2025-04-02",)]).equal
    assert compare_results([(dt.datetime(2025, 4, 2, tzinfo=dt.UTC),)], [("2025-04-02T00:00:00+00:00",)]).equal
    assert compare_results([(dt.datetime(2025, 4, 2, 9, 30, tzinfo=dt.UTC),)], [("2025-04-02T09:30:00Z",)]).equal
    assert not compare_results([(dt.date(2025, 4, 2),)], [("2025-04-03",)]).equal


def test_text_is_trimmed_but_case_matters():
    assert compare_results([("Acme ",)], [("Acme",)]).equal
    assert not compare_results([("Acme",)], [("acme",)]).equal


def test_none_is_a_value_of_its_own():
    assert compare_results([(None, 1)], [(None, 1)]).equal
    assert not compare_results([(None,)], [(0,)]).equal
    assert not compare_results([(None,)], [("",)]).equal


def test_different_row_counts_are_reported():
    result = compare_results([(1,), (2,)], [(1,)])
    assert not result.equal and "row count" in result.reason


def test_duplicate_rows_are_counted():
    assert not compare_results([(1,), (1,), (2,)], [(1,), (2,), (2,)]).equal
    assert compare_results([(1,), (1,), (2,)], [(2,), (1,), (1,)]).equal


def test_a_wrong_value_is_a_mismatch():
    result = compare_results([("a", 1), ("b", 2)], [("a", 1), ("b", 3)])
    assert not result.equal and not result.superset


def test_rows_must_pair_up_not_just_columns():
    # Same values per column, but combined differently.
    assert not compare_results([("a", 1), ("b", 2)], [("a", 2), ("b", 1)]).equal


def test_extra_columns_are_allowed_only_in_the_lenient_reading():
    ref = [(1,), (2,)]
    cand = [(1, "x"), (2, "y")]
    result = compare_results(ref, cand)
    assert not result.equal and result.superset and result.reason == "extra columns"


def test_missing_columns_fail_both_readings():
    result = compare_results([(1, "x")], [(1,)])
    assert not result.equal and not result.superset


def test_identical_columns_do_not_confuse_the_matching():
    # Two columns with the same content: either may stand for either.
    assert compare_results([(0, 0, "a")], [(0, "a", 0)]).equal


def test_empty_results():
    assert compare_results([], []).equal
    assert compare_results([], [], ).superset
    assert not compare_results([], [(1,)]).equal


def test_normalise_cell_kinds():
    assert normalise_cell(True) == ("bool", True)
    assert normalise_cell(None) == ("null", None)
    assert normalise_cell(5) == ("num", 5.0)
    assert normalise_cell(" 12 ") == ("num", 12.0)
    assert normalise_cell("0012")[0] == "num"  # identifiers that look numeric compare as numbers
    assert normalise_cell("abc") == ("str", "abc")
    assert normalise_cell(float("nan"))[0] == "str"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [(1.0, 1.0000001, True), (1.0, 1.001, False), (0.0, 1e-9, True)],
)
def test_cells_equal_tolerance(a, b, expected):
    assert cells_equal(normalise_cell(a), normalise_cell(b)) is expected
