"""Write a small, realistic, synthetic Order-to-Cash dataset as raw source files.

There is no sample data in the repository, so this generates a deterministic
dataset in the *raw export shape* of the real data: one directory per table with
``part-0001.jsonl``, camelCase keys, every value a string, empty strings for
missing values, ``2025-01-06T00:00:00.000Z`` dates, ``{"hours":..}`` time
objects and zero-padded item numbers.  Loading it goes through the normal
``graphsense ingest`` path, so demos and CI exercise the same coercion and
normalisation as real data.

Usage (from ``backend/``)::

    python scripts/make_demo_data.py --out /tmp/demo-data      # writes /tmp/demo-data/sap-o2c-data/...
    graphsense ingest o2c --data-root /tmp/demo-data

The generated data covers what the graph layer has to handle:

* 10 customers (one with an address on file, one blocked) and 24 products with
  English and German descriptions
* 100 sales orders with 1-4 items, in USD, EUR and INR
* deliveries for most orders and invoices for most deliveries, journal entries
  with one or two line items, and payments for most invoices
* item numbers zero-padded in the item tables (``000010``) but short in the
  cross-document references (``10``), as in the real export
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CUSTOMER_NAMES = [
    "Cardenas, Parker and Avila",
    "Nelson, Fitzpatrick and Jordan",
    "Melton, Bender and Sanchez",
    "Bernard Horn",
    "Northwind Traders",
    "Fabrikam Industries",
    "Adventure Works Cycles",
    "Contoso Retail Group",
    "Wide World Importers",
    "Tailspin Toys",
]
CITIES = [
    ("Chicago", "US", "IL"),
    ("Munich", "DE", "BY"),
    ("Leeds", "GB", "ENG"),
    ("Lyon", "FR", "ARA"),
    ("Pune", "IN", "MH"),
    ("Rotterdam", "NL", "ZH"),
]
PRODUCT_NAMES = [
    "Trail running shoes", "Waterproof jacket", "Merino base layer", "Hydration pack",
    "Trekking poles", "Headlamp", "Insulated bottle", "Camp stove", "Dry bag 20L",
    "Sleeping mat", "Climbing harness", "Rain trousers", "Fleece pullover", "Sun hat",
    "Gaiters", "First aid kit", "Compass", "Map case", "Tent pegs", "Ground sheet",
    "Cooking pot", "Water filter", "Wool socks", "Bivvy bag",
]
GERMAN_NAMES = {0: "Trailrunning-Schuhe", 1: "Wasserdichte Jacke", 2: "Merino-Unterzieher"}
CURRENCIES = ["USD"] * 6 + ["EUR"] * 3 + ["INR"]
TABLES = [  # tables the demo fills
    "payments_accounts_receivable",
    "journal_entry_items_accounts_receivable",
    "billing_document_items",
    "billing_document_headers",
    "outbound_delivery_items",
    "outbound_delivery_headers",
    "sales_order_items",
    "sales_order_headers",
    "product_descriptions",
    "products",
    "business_partner_addresses",
    "business_partners",
]


def money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def build(seed: int = 7) -> dict[str, list[dict]]:
    """The whole dataset as ``table -> rows``; deterministic for a given seed."""
    rng = random.Random(seed)
    rows: dict[str, list[dict]] = {name: [] for name in TABLES}
    base = dt.date(2025, 1, 6)

    for index, name in enumerate(CUSTOMER_NAMES):
        partner = str(310000100 + index)
        created = base - dt.timedelta(days=400 + index * 9)
        rows["business_partners"].append({
            "business_partner": partner,
            "customer": partner,
            "business_partner_category": "2",
            "business_partner_full_name": name,
            "business_partner_name": name,
            "organization_bp_name1": name.split(",")[0],
            "business_partner_grouping": "BP02",
            "created_by_user": "SEEDUSER",
            "creation_date": created,
            "last_change_date": created + dt.timedelta(days=30),
            "business_partner_is_blocked": index == 9,
            "is_marked_for_archiving": False,
        })
        if index < 6:
            city, country, region = CITIES[index]
            rows["business_partner_addresses"].append({
                "business_partner": partner,
                "address_id": str(1000 + index * 7),
                "city_name": city,
                "country": country,
                "region": region,
                "postal_code": str(10000 + index * 1234),
                "street_name": f"{10 + index * 3} Market Street",
                "validity_start_date": created,
                "validity_end_date": dt.date(9999, 12, 31),
                "address_time_zone": "UTC",
            })

    products = []
    for index, name in enumerate(PRODUCT_NAMES):
        code = f"S89073670{index + 1:05d}"
        products.append(code)
        rows["products"].append({
            "product": code,
            "product_type": "ZPRD" if index % 3 else "FERT",
            "product_group": ["Footwear", "Outerwear", "Apparel", "Equipment"][index % 4],
            "base_unit": "PC",
            "gross_weight": Decimal(rng.randint(10, 400)) / 100,
            "net_weight": Decimal(rng.randint(5, 350)) / 100,
            "weight_unit": "KG",
            "division": "00",
            "industry_sector": "M",
            "creation_date": base - dt.timedelta(days=700),
            "is_marked_for_deletion": False,
        })
        rows["product_descriptions"].append(
            {"product": code, "language": "EN", "product_description": name}
        )
        if index in GERMAN_NAMES:
            rows["product_descriptions"].append(
                {"product": code, "language": "DE", "product_description": GERMAN_NAMES[index]}
            )

    delivery_no, billing_no, accounting_no = 80738000, 90504200, 9400000000
    for n in range(100):
        order = str(740500 + n)
        customer = rows["business_partners"][rng.randrange(len(CUSTOMER_NAMES))]["customer"]
        currency = rng.choice(CURRENCIES)
        created = base + dt.timedelta(days=n * 2 + rng.randint(0, 1))
        items = []
        for line in range(rng.randint(1, 4)):
            quantity = Decimal(rng.randint(1, 12))
            net = (quantity * money(rng, 20, 180)).quantize(Decimal("0.01"))
            items.append({
                "sales_order": order,
                "sales_order_item": f"{(line + 1) * 10:06d}",
                "sales_order_item_category": "TAN",
                "material": rng.choice(products),
                "requested_quantity": quantity,
                "requested_quantity_unit": "PC",
                "transaction_currency": currency,
                "net_amount": net,
                "material_group": "ZMG1",
                "production_plant": "1710",
                "storage_location": "171A",
            })
        total = sum((item["net_amount"] for item in items), Decimal(0))
        has_delivery = rng.random() < 0.86
        rows["sales_order_headers"].append({
            "sales_order": order,
            "sales_order_type": "OR",
            "sales_organization": "1710",
            "distribution_channel": "10",
            "organization_division": "00",
            "sold_to_party": customer,
            "creation_date": created,
            "created_by_user": "SEEDUSER",
            "last_change_datetime": dt.datetime.combine(created, dt.time(9, 30), dt.UTC),
            "total_net_amount": total,
            "overall_delivery_status": "C" if has_delivery else "A",
            "transaction_currency": currency,
            "pricing_date": created,
            "requested_delivery_date": created + dt.timedelta(days=7),
            "incoterms_classification": "FOB",
            "incoterms_location1": "Origin",
            "customer_payment_terms": "Z009",
        })
        rows["sales_order_items"].extend(items)
        if not has_delivery:
            continue

        delivery_no += 1
        delivery = str(delivery_no)
        shipped = created + dt.timedelta(days=rng.randint(2, 6))
        rows["outbound_delivery_headers"].append({
            "delivery_document": delivery,
            "creation_date": shipped,
            "actual_goods_movement_date": shipped + dt.timedelta(days=1),
            "overall_goods_movement_status": "C",
            "overall_picking_status": "C",
            "shipping_point": "1710",
            "hdr_general_incompletion_status": "C",
            "last_change_date": shipped,
        })
        delivery_items = []
        for item in items:
            row = {
                "delivery_document": delivery,
                "delivery_document_item": item["sales_order_item"],
                "actual_delivery_quantity": item["requested_quantity"],
                "delivery_quantity_unit": "PC",
                "plant": "1710",
                "storage_location": "171A",
                # Cross-document references use the short item number.
                "reference_sd_document": order,
                "reference_sd_document_item": str(int(item["sales_order_item"])),
            }
            delivery_items.append(row)
        rows["outbound_delivery_items"].extend(delivery_items)
        if rng.random() > 0.8:
            continue

        billing_no += 1
        accounting_no += 1
        invoice = str(billing_no)
        billed = shipped + dt.timedelta(days=rng.randint(1, 5))
        cancelled = rng.random() < 0.03
        invoice_total = sum((i["net_amount"] for i in items), Decimal(0))
        rows["billing_document_headers"].append({
            "billing_document": invoice,
            "billing_document_type": "F2",
            "creation_date": billed,
            "billing_document_date": billed,
            "billing_document_is_cancelled": cancelled,
            "total_net_amount": invoice_total,
            "transaction_currency": currency,
            "company_code": "ABCD",
            "fiscal_year": "2025",
            "accounting_document": str(accounting_no),
            "sold_to_party": customer,
            "last_change_datetime": dt.datetime.combine(billed, dt.time(11, 0), dt.UTC),
        })
        for d_item, item in zip(delivery_items, items):
            rows["billing_document_items"].append({
                "billing_document": invoice,
                # Billing items are numbered without padding.
                "billing_document_item": str(int(d_item["delivery_document_item"])),
                "material": item["material"],
                "billing_quantity": item["requested_quantity"],
                "billing_quantity_unit": "PC",
                "net_amount": item["net_amount"],
                "transaction_currency": currency,
                "reference_sd_document": delivery,
                "reference_sd_document_item": str(int(d_item["delivery_document_item"])),
            })

        paid = rng.random() < 0.65
        payment_doc = str(accounting_no + 1000000)
        cleared = billed + dt.timedelta(days=rng.randint(10, 40))
        # One receivable line, or two (e.g. instalments) for about a quarter of the invoices.
        if rng.random() < 0.25:
            first = (invoice_total / 2).quantize(Decimal("0.01"))
            amounts = (first, invoice_total - first)
        else:
            amounts = (invoice_total,)
        for line, amount in enumerate(amounts, start=1):
            rows["journal_entry_items_accounts_receivable"].append({
                "company_code": "ABCD",
                "fiscal_year": "2025",
                "accounting_document": str(accounting_no),
                "accounting_document_item": str(line),
                "gl_account": "15005000",
                "reference_document": invoice,
                "profit_center": "YB101",
                "transaction_currency": currency,
                "amount_in_transaction_currency": amount,
                "company_code_currency": "USD",
                "amount_in_company_code_currency": amount,
                "posting_date": billed,
                "document_date": billed,
                "accounting_document_type": "RV",
                "customer": customer,
                "financial_account_type": "D",
                "clearing_date": cleared if paid else None,
                "clearing_accounting_document": payment_doc if paid else None,
                "clearing_doc_fiscal_year": "2025" if paid else None,
            })
        if paid:
            rows["payments_accounts_receivable"].append({
                "company_code": "ABCD",
                "fiscal_year": "2025",
                "accounting_document": payment_doc,
                "accounting_document_item": "1",
                "clearing_date": cleared,
                # The payment clears the invoice's accounting document.
                "clearing_accounting_document": str(accounting_no),
                "clearing_doc_fiscal_year": "2025",
                "amount_in_transaction_currency": invoice_total,
                "transaction_currency": currency,
                "amount_in_company_code_currency": invoice_total,
                "company_code_currency": "USD",
                "customer": customer,
                "posting_date": cleared,
                "document_date": cleared,
                "gl_account": "15005000",
                "financial_account_type": "D",
                "profit_center": "YB101",
            })
    return rows


def raw_value(value):
    """A value in the shape of the source export (everything a string, empty for missing)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    if isinstance(value, dt.time):
        return {"hours": value.hour, "minutes": value.minute, "seconds": value.second}
    return str(value)


def write(data: dict[str, list[dict]], out: Path, dataset_id: str = "o2c") -> dict[str, int]:
    """Write ``data`` below ``out`` where the package expects its source files."""
    from src.datasets.registry import get_package

    package = get_package(dataset_id)
    counts = {}
    for table in package.tables:
        rows = data.get(table.table, [])
        directory = out / package.source.default_subdir / table.source.path
        directory.mkdir(parents=True, exist_ok=True)
        sources = {c.name: c.source for c in table.columns}
        with (directory / "part-0001.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                record = {sources[name]: raw_value(value) for name, value in row.items() if name in sources}
                handle.write(json.dumps(record) + "\n")
        counts[table.table] = len(rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="data root to write into")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    counts = write(build(args.seed), args.out)
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if n)
    print(f"Wrote {summary}")
    print(f"Load it with: graphsense ingest o2c --data-root {args.out}")


if __name__ == "__main__":
    main()
