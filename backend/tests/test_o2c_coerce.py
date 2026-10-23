"""Coercion of real order-to-cash records (one or more per table, copied from the sample data)."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from src.datasets import row_coercer
from tests.conftest import FIXTURES

REAL = json.loads((FIXTURES / "o2c_real_records.json").read_text(encoding="utf-8"))

PY_TYPES = {
    "text": str,
    "integer": int,
    "bigint": int,
    "decimal": Decimal,
    "boolean": bool,
    "date": dt.date,
    "time": dt.time,
    "timestamp": dt.datetime,
}


def _cases():
    return [
        pytest.param(directory, record, id=f"{directory}[{index}]")
        for directory, records in REAL.items()
        for index, record in enumerate(records)
    ]


def _row(o2c_package, directory, record):
    table = next(t for t in o2c_package.tables if t.source.path == directory)
    row, issues = row_coercer(table)(record)
    assert issues == []
    return dict(zip([c.name for c in table.stored_columns()], row, strict=True))


def test_the_fixture_covers_all_19_tables(o2c_package):
    assert sorted(REAL) == sorted(t.source.path for t in o2c_package.tables)
    assert len(REAL) == 19


@pytest.mark.parametrize("directory,record", _cases())
def test_real_records_coerce_without_issues(o2c_package, directory, record):
    table = next(t for t in o2c_package.tables if t.source.path == directory)
    row, issues = row_coercer(table)(record)
    assert issues == []
    stored = table.stored_columns()
    assert len(row) == len(stored)
    for value, col in zip(row, stored, strict=True):
        if value is None:
            assert col.nullable, f"{table.table}.{col.name} is NULL but not nullable"
            continue
        assert type(value) is PY_TYPES[col.sql_type.kind], (table.table, col.name, value)


@pytest.mark.parametrize("directory,record", _cases())
def test_real_records_use_only_declared_or_ignored_fields(o2c_package, directory, record):
    table = next(t for t in o2c_package.tables if t.source.path == directory)
    assert set(record) <= table.source_fields, set(record) - table.source_fields


def test_dates_times_and_timestamps_from_the_source_shape(o2c_package):
    record = REAL["sales_order_headers"][0]
    row = _row(o2c_package, "sales_order_headers", record)
    assert row["creation_date"] == dt.date(2025, 3, 31)  # "2025-03-31T00:00:00.000Z"
    assert row["last_change_datetime"] == dt.datetime(2025, 3, 31, 6, 42, 38, 786000, tzinfo=dt.UTC)
    header = _row(o2c_package, "billing_document_headers", REAL["billing_document_headers"][0])
    assert isinstance(header["creation_time"], dt.time)  # from {"hours":..,"minutes":..,"seconds":..}


def test_time_object_becomes_a_time(o2c_package):
    record = dict(REAL["outbound_delivery_headers"][0])
    record["creationTime"] = {"hours": 6, "minutes": 49, "seconds": 13}
    row = _row(o2c_package, "outbound_delivery_headers", record)
    assert row["creation_time"] == dt.time(6, 49, 13)


def test_empty_string_and_null_become_null(o2c_package):
    record = dict(REAL["sales_order_items"][0], salesDocumentRjcnReason="", material=None)
    row = _row(o2c_package, "sales_order_items", record)
    assert row["sales_document_rjcn_reason"] is None
    assert row["material"] is None


def test_empty_string_is_kept_when_the_policy_says_so(o2c_package):
    table = o2c_package.table("sales_order_items")
    record = dict(REAL["sales_order_items"][0], salesDocumentRjcnReason="")
    row, _ = row_coercer(table, empty_string_is_null=False)(record)
    index = list(table.column_names).index("sales_document_rjcn_reason")
    assert row[index] == ""


def test_decimal_amounts_are_exact(o2c_package):
    record = dict(REAL["sales_order_headers"][0], totalNetAmount="17108.25")
    assert _row(o2c_package, "sales_order_headers", record)["total_net_amount"] == Decimal("17108.2500")


def test_booleans_are_json_booleans(o2c_package):
    record = REAL["products"][0]
    assert _row(o2c_package, "products", record)["is_marked_for_deletion"] is False


def test_item_numbers_are_made_canonical_across_tables(o2c_package):
    """Deliveries pad item numbers ('000010'), orders and invoices do not ('10')."""
    delivery = _row(o2c_package, "outbound_delivery_items", dict(REAL["outbound_delivery_items"][0], deliveryDocumentItem="000010", referenceSdDocumentItem="000010"))
    order = _row(o2c_package, "sales_order_items", dict(REAL["sales_order_items"][0], salesOrderItem="10"))
    invoice = _row(o2c_package, "billing_document_items", dict(REAL["billing_document_items"][0], billingDocumentItem="10", referenceSdDocumentItem="10"))
    assert delivery["delivery_document_item"] == delivery["reference_sd_document_item"] == order["sales_order_item"] == "10"
    assert invoice["billing_document_item"] == invoice["reference_sd_document_item"] == "10"

