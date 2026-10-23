"""Type-driven coercion: converters, normalisers, rejections (on the toy package)."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from src.datasets import load_package, row_coercer
from src.datasets.coerce import converter_for
from src.datasets.models import parse_type
from src.datasets.normalizers import apply_normalizers, strip_leading_zeros
from tests.conftest import TOY_DIR


def test_a_text_column_holding_true_stays_text(toy_package):
    """The old loader turned any "True" string into a boolean, whatever the column."""
    table = toy_package.table("books")
    record = {"isbn": "1", "title": "True", "shelfCode": "False", "isReference": "True"}
    row, issues = row_coercer(table)(record)
    values = dict(zip(table.column_names, row, strict=True))
    assert issues == []
    assert values["title"] == "True" and values["shelf_code"] == "False"
    assert values["is_reference"] is True


def test_leading_zeros_of_a_non_item_code_are_kept(toy_package):
    table = toy_package.table("books")
    row, _ = row_coercer(table)({"isbn": "1", "shelfCode": "05"})
    assert dict(zip(table.column_names, row, strict=True))["shelf_code"] == "05"


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_missing_primary_key_rejects_the_row(toy_package):
    table = toy_package.table("loans")
    _, issues = row_coercer(table)({"loanId": "", "loanedOn": "2025-01-01"})
    assert [(i.column, i.code, i.severity) for i in issues] == [("loan_id", "missing_required", "reject")]


def test_a_required_column_rejects_the_row(toy_package):
    _, issues = row_coercer(toy_package.table("loans"))({"loanId": "L1"})
    assert [(i.column, i.code) for i in issues] == [("loaned_on", "missing_required")]


@pytest.mark.parametrize(
    "column,value",
    [
        ("loanedOn", "not a date"),
        ("loanedOn", "2025-13-45"),
        ("loanedOn", 20250101),
        ("lateFee", "twelve"),
        ("lateFee", "NaN"),
        ("lateFee", "123456789.00"),  # too many digits for decimal(8,2)
        ("lateFee", True),
        ("returnedAt", "yesterday"),
    ],
)
def test_bad_values_reject_the_row_with_the_column_named(toy_package, column, value):
    record = {"loanId": "L1", "loanedOn": "2025-01-01", column: value}
    _, issues = row_coercer(toy_package.table("loans"))(record)
    assert [i.column for i in issues if i.severity == "reject"] == [{"loanedOn": "loaned_on", "lateFee": "late_fee", "returnedAt": "returned_at"}[column]]
    assert issues[0].code == "invalid_value"


def test_issue_samples_never_include_sensitive_values(toy_package):
    table = toy_package.table("members")
    # make the sensitive column invalid for its type by feeding a list
    _, issues = row_coercer(table)({"memberId": "M1", "email": ["secret@example.test"]})
    assert issues and issues[0].column == "email"
    assert issues[0].sample is None
    _, issues = row_coercer(table)({"memberId": "M1", "joinedAt": "garbage"})
    assert issues[0].sample == "'garbage'"


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("2025-03-31", dt.date(2025, 3, 31)), ("2025-03-31T00:00:00.000Z", dt.date(2025, 3, 31)),
     ("9999-12-31T23:59:59.000Z", dt.date(9999, 12, 31)), ("2025-03-31T23:30:00-02:00", dt.date(2025, 4, 1))],
)
def test_date_forms(value, expected):
    assert converter_for(parse_type("date"))(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [({"hours": 6, "minutes": 49, "seconds": 13}, dt.time(6, 49, 13)), ("06:49:13", dt.time(6, 49, 13)),
     ("PT06H49M13S", dt.time(6, 49, 13)), ("PT1H", dt.time(1, 0, 0)), ({"hours": "7", "minutes": "0", "seconds": "5"}, dt.time(7, 0, 5))],
)
def test_time_forms(value, expected):
    assert converter_for(parse_type("time"))(value) == expected


@pytest.mark.parametrize("value", [{"hours": 25, "minutes": 0, "seconds": 0}, {"hours": 1}, "25:00:00", 3.5])
def test_bad_times(value):
    with pytest.raises(ValueError):
        converter_for(parse_type("time"))(value)


@pytest.mark.parametrize(
    "value,expected",
    [("2025-03-31T06:42:38.786Z", dt.datetime(2025, 3, 31, 6, 42, 38, 786000, tzinfo=dt.UTC)),
     ("2025-03-31T08:00:00+02:00", dt.datetime(2025, 3, 31, 6, 0, tzinfo=dt.UTC)),
     ("2025-03-31T06:00:00", dt.datetime(2025, 3, 31, 6, 0, tzinfo=dt.UTC)),
     ("2025-03-31", dt.datetime(2025, 3, 31, tzinfo=dt.UTC))],
)
def test_timestamp_forms(value, expected):
    assert converter_for(parse_type("timestamp"))(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(True, True), (False, False), ("true", True), ("False", False), ("TRUE", True), (1, True), (0, False)],
)
def test_boolean_forms(value, expected):
    assert converter_for(parse_type("boolean"))(value) is expected


@pytest.mark.parametrize("value", ["yes", "X", 2, None.__class__])
def test_bad_booleans(value):
    with pytest.raises(ValueError):
        converter_for(parse_type("boolean"))(value)


@pytest.mark.parametrize(
    "type_,value,expected",
    [("decimal(18,4)", "9966.1", Decimal("9966.1000")), ("decimal(18,2)", 10, Decimal("10.00")),
     ("decimal(18,2)", 1.005, Decimal("1.01")), ("decimal(5,2)", "-0.005", Decimal("-0.01")),
     ("integer", "42", 42), ("integer", 7.0, 7), ("bigint", "-9007199254740993", -9007199254740993)],
)
def test_numbers(type_, value, expected):
    assert converter_for(parse_type(type_))(value) == expected


@pytest.mark.parametrize("type_,value", [("integer", "4.5"), ("integer", 2**31), ("integer", True), ("decimal(5,2)", "1000.00"), ("decimal(5,2)", "abc")])
def test_bad_numbers(type_, value):
    with pytest.raises(ValueError):
        converter_for(parse_type(type_))(value)


def test_json_columns_take_structures_as_they_are():
    convert = converter_for(parse_type("json"))
    assert convert({"a": [1, 2]}) == {"a": [1, 2]}


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [("000010", "10"), ("10", "10"), ("0", "0"), ("000", "0"), ("0100", "100"), ("A010", "A010")])
def test_strip_leading_zeros_is_idempotent(value, expected):
    assert strip_leading_zeros(value) == expected
    assert strip_leading_zeros(strip_leading_zeros(value)) == expected


def test_normalisers_chain_in_order():
    assert apply_normalizers("  Ab  C ", ("collapse_whitespace", "upper")) == "AB C"
    assert apply_normalizers("  x ", ("trim", "lower")) == "x"


def test_keep_raw_keeps_the_original_text(package_copy):
    path = package_copy(edits={"tables/loans.yaml": ("normalize: [strip_leading_zeros],", "normalize: [strip_leading_zeros], keep_raw: true,")})
    table = load_package(path).table("loans")
    row, issues = row_coercer(table)({"loanId": "L1", "loanedOn": "2025-01-01", "copyNumber": "0007"})
    values = dict(zip([c.name for c in table.stored_columns()], row, strict=True))
    assert issues == []
    assert values["copy_number"] == "7" and values["copy_number_raw"] == "0007"


def test_toy_records_from_the_fixture_data_load(toy_package):
    """The toy package's own sample files coerce cleanly end to end."""
    from tests.conftest import TOY_DATA_DIR

    total = 0
    for table in toy_package.tables:
        coerce = row_coercer(table)
        for file in sorted((TOY_DATA_DIR / table.source.path).glob("*.jsonl")):
            for line in file.read_text(encoding="utf-8").splitlines():
                _row, issues = coerce(json.loads(line))
                assert issues == [], (table.table, line)
                total += 1
    assert total == 11
    assert TOY_DIR.exists()
