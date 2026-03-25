"""
Relationship Integrity Analysis for SAP O2C Knowledge Graph
============================================================
Detects orphaned entities, broken joins, and graph layer gaps.

Usage:
    cd "data modelling"
    python relationship.py

Requires: psycopg2-binary, tabulate
    pip install psycopg2-binary tabulate
"""

import sys
from collections import defaultdict
from typing import Any

import psycopg2
from tabulate import tabulate

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
DSN = "host=localhost port=5432 dbname=dodgeai user=postgres password=postgres"


def query(conn, sql: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def query_scalar(conn, sql: str) -> Any:
    rows = query(conn, sql)
    return rows[0][0] if rows else 0


# ---------------------------------------------------------------------------
# 1. Table row counts
# ---------------------------------------------------------------------------
def print_row_counts(conn):
    tables = [
        "sales_order_headers", "sales_order_items",
        "outbound_delivery_headers", "outbound_delivery_items",
        "billing_document_headers", "billing_document_items",
        "journal_entry_items_accounts_receivable", "payments_accounts_receivable",
        "business_partners", "business_partner_addresses", "products",
    ]
    rows = []
    for t in tables:
        cnt = query_scalar(conn, f"SELECT count(*) FROM {t}")
        rows.append([t, cnt])
    print("\n=== TABLE ROW COUNTS ===")
    print(tabulate(rows, headers=["Table", "Count"], tablefmt="simple_grid"))


# ---------------------------------------------------------------------------
# 2. Orphan detection — missing upstream/downstream links
# ---------------------------------------------------------------------------
ORPHAN_CHECKS = [
    # (description, SQL returning count of orphans)

    # --- Sales Orders without Customer ---
    (
        "SalesOrder → Customer (missing sold_to_party in business_partners)",
        """
        SELECT count(*) FROM sales_order_headers soh
        WHERE soh.sold_to_party IS NOT NULL
          AND soh.sold_to_party NOT IN (SELECT customer FROM business_partners WHERE customer IS NOT NULL)
          AND soh.sold_to_party NOT IN (SELECT business_partner FROM business_partners)
        """,
    ),
    (
        "SalesOrder with NULL sold_to_party",
        "SELECT count(*) FROM sales_order_headers WHERE sold_to_party IS NULL",
    ),

    # --- Sales Order Items without header ---
    (
        "SalesOrderItem → SalesOrder (orphan items)",
        """
        SELECT count(*) FROM sales_order_items soi
        WHERE soi.sales_order NOT IN (SELECT sales_order FROM sales_order_headers)
        """,
    ),

    # --- Sales Order Items without Product ---
    (
        "SalesOrderItem → Product (material not in products table)",
        """
        SELECT count(*) FROM sales_order_items soi
        WHERE soi.material IS NOT NULL
          AND soi.material NOT IN (SELECT product FROM products)
        """,
    ),
    (
        "SalesOrderItem with NULL material",
        "SELECT count(*) FROM sales_order_items WHERE material IS NULL",
    ),

    # --- Delivery Items without Sales Order reference ---
    (
        "DeliveryItem → SalesOrder (reference_sd_document not in sales_order_headers)",
        """
        SELECT count(*) FROM outbound_delivery_items odi
        WHERE odi.reference_sd_document IS NOT NULL
          AND odi.reference_sd_document NOT IN (SELECT sales_order FROM sales_order_headers)
        """,
    ),
    (
        "DeliveryItem with NULL reference_sd_document",
        "SELECT count(*) FROM outbound_delivery_items WHERE reference_sd_document IS NULL",
    ),

    # --- Delivery Items without header ---
    (
        "DeliveryItem → Delivery (orphan items)",
        """
        SELECT count(*) FROM outbound_delivery_items odi
        WHERE odi.delivery_document NOT IN (SELECT delivery_document FROM outbound_delivery_headers)
        """,
    ),

    # --- Sales Orders without any Delivery ---
    (
        "SalesOrder without any Delivery (no downstream fulfilment)",
        """
        SELECT count(*) FROM sales_order_headers soh
        WHERE soh.sales_order NOT IN (
            SELECT DISTINCT odi.reference_sd_document
            FROM outbound_delivery_items odi
            WHERE odi.reference_sd_document IS NOT NULL
        )
        """,
    ),

    # --- Billing Items without Delivery reference ---
    (
        "InvoiceItem → Delivery (reference_sd_document not in outbound_delivery_headers)",
        """
        SELECT count(*) FROM billing_document_items bdi
        WHERE bdi.reference_sd_document IS NOT NULL
          AND bdi.reference_sd_document NOT IN (SELECT delivery_document FROM outbound_delivery_headers)
        """,
    ),
    (
        "InvoiceItem with NULL reference_sd_document",
        "SELECT count(*) FROM billing_document_items WHERE reference_sd_document IS NULL",
    ),

    # --- Billing Items without header ---
    (
        "InvoiceItem → Invoice (orphan items)",
        """
        SELECT count(*) FROM billing_document_items bdi
        WHERE bdi.billing_document NOT IN (SELECT billing_document FROM billing_document_headers)
        """,
    ),

    # --- Invoice without Customer ---
    (
        "Invoice → Customer (sold_to_party not in business_partners)",
        """
        SELECT count(*) FROM billing_document_headers bdh
        WHERE bdh.sold_to_party IS NOT NULL
          AND bdh.sold_to_party NOT IN (SELECT customer FROM business_partners WHERE customer IS NOT NULL)
          AND bdh.sold_to_party NOT IN (SELECT business_partner FROM business_partners)
        """,
    ),
    (
        "Invoice with NULL sold_to_party",
        "SELECT count(*) FROM billing_document_headers WHERE sold_to_party IS NULL",
    ),

    # --- Deliveries without any Invoice ---
    (
        "Delivery without any Invoice (no downstream billing)",
        """
        SELECT count(*) FROM outbound_delivery_headers odh
        WHERE odh.delivery_document NOT IN (
            SELECT DISTINCT bdi.reference_sd_document
            FROM billing_document_items bdi
            WHERE bdi.reference_sd_document IS NOT NULL
        )
        """,
    ),

    # --- Invoice without JournalEntry ---
    (
        "Invoice → JournalEntry (accounting_document NULL or not in journal_entries)",
        """
        SELECT count(*) FROM billing_document_headers bdh
        WHERE bdh.accounting_document IS NULL
           OR bdh.accounting_document NOT IN (
               SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable
           )
        """,
    ),
    (
        "Invoice with NULL accounting_document",
        "SELECT count(*) FROM billing_document_headers WHERE accounting_document IS NULL",
    ),

    # --- JournalEntry without Payment (uncleared) ---
    (
        "JournalEntry without Payment (not cleared)",
        """
        SELECT count(DISTINCT je.accounting_document) FROM journal_entry_items_accounts_receivable je
        WHERE je.accounting_document NOT IN (
            SELECT DISTINCT clearing_accounting_document
            FROM payments_accounts_receivable
            WHERE clearing_accounting_document IS NOT NULL
        )
        """,
    ),

    # --- Payment clearing non-existent JournalEntry ---
    (
        "Payment → JournalEntry (clearing_accounting_document not in journal_entries)",
        """
        SELECT count(DISTINCT par.clearing_accounting_document)
        FROM payments_accounts_receivable par
        WHERE par.clearing_accounting_document IS NOT NULL
          AND par.clearing_accounting_document NOT IN (
              SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable
          )
        """,
    ),

    # --- Business Partner without Address ---
    (
        "Customer without Address",
        """
        SELECT count(*) FROM business_partners bp
        WHERE bp.business_partner NOT IN (
            SELECT DISTINCT business_partner FROM business_partner_addresses
        )
        """,
    ),
]


def run_orphan_checks(conn):
    print("\n=== ORPHAN / BROKEN LINK DETECTION ===")
    results = []
    for desc, sql in ORPHAN_CHECKS:
        cnt = query_scalar(conn, sql)
        status = "OK" if cnt == 0 else "ISSUE"
        results.append([status, desc, cnt])
    print(tabulate(results, headers=["Status", "Check", "Count"], tablefmt="simple_grid"))
    return results


# ---------------------------------------------------------------------------
# 3. Cross-document join validation (item-level key matching)
# ---------------------------------------------------------------------------
def validate_cross_doc_joins(conn):
    print("\n=== CROSS-DOCUMENT JOIN VALIDATION ===")
    checks = [
        (
            "DeliveryItem.reference_sd_document_item → SalesOrderItem (normalized)",
            """
            SELECT count(*) FROM outbound_delivery_items odi
            WHERE odi.reference_sd_document IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM sales_order_items soi
                  WHERE soi.sales_order = odi.reference_sd_document
                    AND REGEXP_REPLACE(soi.sales_order_item::text, '^0+', '')
                      = REGEXP_REPLACE(odi.reference_sd_document_item::text, '^0+', '')
              )
            """,
        ),
        (
            "InvoiceItem.reference_sd_document_item → DeliveryItem (normalized)",
            """
            SELECT count(*) FROM billing_document_items bdi
            WHERE bdi.reference_sd_document IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM outbound_delivery_items odi
                  WHERE odi.delivery_document = bdi.reference_sd_document
                    AND REGEXP_REPLACE(odi.delivery_document_item::text, '^0+', '')
                      = REGEXP_REPLACE(bdi.reference_sd_document_item::text, '^0+', '')
              )
            """,
        ),
        (
            "Invoice.accounting_document → JournalEntry.accounting_document",
            """
            SELECT count(*) FROM billing_document_headers bdh
            WHERE bdh.accounting_document IS NOT NULL
              AND bdh.accounting_document NOT IN (
                  SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable
              )
            """,
        ),
        (
            "Payment.clearing_accounting_document → JournalEntry.accounting_document",
            """
            SELECT count(DISTINCT par.clearing_accounting_document)
            FROM payments_accounts_receivable par
            WHERE par.clearing_accounting_document IS NOT NULL
              AND par.clearing_accounting_document NOT IN (
                  SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable
              )
            """,
        ),
    ]
    results = []
    for desc, sql in checks:
        cnt = query_scalar(conn, sql)
        status = "OK" if cnt == 0 else "BROKEN"
        results.append([status, desc, cnt])
    print(tabulate(results, headers=["Status", "Join Check", "Unmatched"], tablefmt="simple_grid"))
    return results


# ---------------------------------------------------------------------------
# 4. Customer linkage validation (every entity traceable to a Customer)
# ---------------------------------------------------------------------------
def validate_customer_linkage(conn):
    print("\n=== CUSTOMER LINKAGE (sold_to_party → business_partners) ===")

    # Check how sold_to_party maps to business_partners
    checks = [
        (
            "sold_to_party matches business_partners.customer",
            """
            SELECT count(DISTINCT soh.sold_to_party) FROM sales_order_headers soh
            WHERE soh.sold_to_party IN (SELECT customer FROM business_partners WHERE customer IS NOT NULL)
            """,
        ),
        (
            "sold_to_party matches business_partners.business_partner",
            """
            SELECT count(DISTINCT soh.sold_to_party) FROM sales_order_headers soh
            WHERE soh.sold_to_party IN (SELECT business_partner FROM business_partners)
            """,
        ),
        (
            "Distinct sold_to_party values in sales_order_headers",
            "SELECT count(DISTINCT sold_to_party) FROM sales_order_headers WHERE sold_to_party IS NOT NULL",
        ),
        (
            "Distinct sold_to_party values in billing_document_headers",
            "SELECT count(DISTINCT sold_to_party) FROM billing_document_headers WHERE sold_to_party IS NOT NULL",
        ),
        (
            "business_partners.customer values",
            "SELECT count(DISTINCT customer) FROM business_partners WHERE customer IS NOT NULL",
        ),
        (
            "business_partners.business_partner values",
            "SELECT count(DISTINCT business_partner) FROM business_partners",
        ),
    ]
    results = []
    for desc, sql in checks:
        cnt = query_scalar(conn, sql)
        results.append([desc, cnt])
    print(tabulate(results, headers=["Metric", "Count"], tablefmt="simple_grid"))

    # Sample mismatches
    sample = query(conn, """
        SELECT DISTINCT soh.sold_to_party
        FROM sales_order_headers soh
        WHERE soh.sold_to_party NOT IN (SELECT business_partner FROM business_partners)
        LIMIT 10
    """)
    if sample:
        print(f"\nSample sold_to_party NOT in business_partners.business_partner: {[r[0] for r in sample]}")

    sample2 = query(conn, """
        SELECT DISTINCT soh.sold_to_party
        FROM sales_order_headers soh
        WHERE soh.sold_to_party NOT IN (SELECT customer FROM business_partners WHERE customer IS NOT NULL)
        LIMIT 10
    """)
    if sample2:
        print(f"Sample sold_to_party NOT in business_partners.customer: {[r[0] for r in sample2]}")

    # Show actual bp values for comparison
    bp_vals = query(conn, "SELECT business_partner, customer FROM business_partners LIMIT 10")
    print(f"\nbusiness_partners sample (bp, customer): {bp_vals}")


# ---------------------------------------------------------------------------
# 5. Graph layer validation — edges the graph SHOULD create vs DB reality
# ---------------------------------------------------------------------------
def validate_graph_edges(conn):
    print("\n=== GRAPH LAYER EDGE VALIDATION ===")
    print("Checking if graph_repository edge derivation matches actual DB joins.\n")

    norm = "REGEXP_REPLACE({col}::text, '^0+', '')"

    edge_checks = [
        (
            "PLACED (Customer→SalesOrder)",
            "SELECT count(*) FROM sales_order_headers WHERE sold_to_party IS NOT NULL",
        ),
        (
            "HAS_ITEM (SalesOrder→SalesOrderItem)",
            "SELECT count(*) FROM sales_order_items",
        ),
        (
            "INCLUDES (SalesOrderItem→Product)",
            "SELECT count(*) FROM sales_order_items WHERE material IS NOT NULL",
        ),
        (
            "HAS_ITEM (Delivery→DeliveryItem)",
            "SELECT count(*) FROM outbound_delivery_items",
        ),
        (
            "FULFILLS (DeliveryItem→SalesOrderItem)",
            "SELECT count(*) FROM outbound_delivery_items WHERE reference_sd_document IS NOT NULL",
        ),
        (
            "HAS_ITEM (Invoice→InvoiceItem)",
            "SELECT count(*) FROM billing_document_items",
        ),
        (
            "BILLS_FOR (InvoiceItem→DeliveryItem)",
            "SELECT count(*) FROM billing_document_items WHERE reference_sd_document IS NOT NULL",
        ),
        (
            "BILLED_TO (Invoice→Customer)",
            "SELECT count(*) FROM billing_document_headers WHERE sold_to_party IS NOT NULL",
        ),
        (
            "GENERATES (Invoice→JournalEntry)",
            "SELECT count(*) FROM billing_document_headers WHERE accounting_document IS NOT NULL",
        ),
        (
            "CLEARS (Payment→JournalEntry)",
            """
            SELECT count(DISTINCT (accounting_document, clearing_accounting_document))
            FROM payments_accounts_receivable WHERE clearing_accounting_document IS NOT NULL
            """,
        ),
        (
            "HAS_ADDRESS (Customer→Address)",
            "SELECT count(*) FROM business_partner_addresses",
        ),
    ]

    results = []
    for desc, sql in edge_checks:
        cnt = query_scalar(conn, sql)
        results.append([desc, cnt])
    print(tabulate(results, headers=["Edge Type", "Potential Edges"], tablefmt="simple_grid"))

    # Check graph-specific issues: Customer node type uses sold_to_party as ID,
    # but business_partners PK is business_partner. Are they the same?
    print("\n--- KEY IDENTITY CHECK ---")
    print("Graph uses sold_to_party as Customer node ID (from PLACED/BILLED_TO edges).")
    print("business_partners table PK is business_partner.")

    mismatch = query_scalar(conn, """
        SELECT count(DISTINCT soh.sold_to_party) FROM sales_order_headers soh
        WHERE soh.sold_to_party IS NOT NULL
          AND soh.sold_to_party NOT IN (SELECT business_partner FROM business_partners)
    """)
    print(f"sold_to_party values NOT matching business_partner PK: {mismatch}")

    # Check if sold_to_party matches via customer column instead
    via_customer = query_scalar(conn, """
        SELECT count(DISTINCT soh.sold_to_party) FROM sales_order_headers soh
        WHERE soh.sold_to_party IS NOT NULL
          AND soh.sold_to_party IN (SELECT customer FROM business_partners WHERE customer IS NOT NULL)
          AND soh.sold_to_party NOT IN (SELECT business_partner FROM business_partners)
    """)
    if via_customer > 0:
        print(f"  → {via_customer} match business_partners.customer but NOT business_partners.business_partner")
        print("  → GRAPH BUG: PLACED/BILLED_TO use sold_to_party as Customer ID,")
        print("    but /entities/Customer returns business_partner as ID.")
        print("    These IDs will never match → broken node identity.")


# ---------------------------------------------------------------------------
# 6. Partial flow detection — entities with incomplete E2E chain
# ---------------------------------------------------------------------------
def detect_partial_flows(conn):
    print("\n=== PARTIAL O2C FLOW DETECTION ===")
    print("Expected: SalesOrder → DeliveryItem → InvoiceItem → JournalEntry → Payment\n")

    # Sales orders that reach each stage
    stages = [
        ("SalesOrders (total)", "SELECT count(*) FROM sales_order_headers"),
        ("→ with Delivery", """
            SELECT count(DISTINCT soh.sales_order) FROM sales_order_headers soh
            WHERE soh.sales_order IN (
                SELECT odi.reference_sd_document FROM outbound_delivery_items odi
                WHERE odi.reference_sd_document IS NOT NULL
            )
        """),
        ("→ with Invoice (via Delivery)", """
            SELECT count(DISTINCT soh.sales_order) FROM sales_order_headers soh
            WHERE soh.sales_order IN (
                SELECT odi.reference_sd_document FROM outbound_delivery_items odi
                WHERE odi.reference_sd_document IS NOT NULL
                  AND odi.delivery_document IN (
                      SELECT bdi.reference_sd_document FROM billing_document_items bdi
                      WHERE bdi.reference_sd_document IS NOT NULL
                  )
            )
        """),
        ("→ with JournalEntry (via Invoice)", """
            SELECT count(DISTINCT soh.sales_order) FROM sales_order_headers soh
            WHERE soh.sales_order IN (
                SELECT odi.reference_sd_document FROM outbound_delivery_items odi
                WHERE odi.reference_sd_document IS NOT NULL
                  AND odi.delivery_document IN (
                      SELECT bdi.reference_sd_document FROM billing_document_items bdi
                      WHERE bdi.reference_sd_document IS NOT NULL
                        AND bdi.billing_document IN (
                            SELECT bdh.billing_document FROM billing_document_headers bdh
                            WHERE bdh.accounting_document IS NOT NULL
                              AND bdh.accounting_document IN (
                                  SELECT DISTINCT accounting_document
                                  FROM journal_entry_items_accounts_receivable
                              )
                        )
                  )
            )
        """),
        ("→ with Payment (via JournalEntry)", """
            SELECT count(DISTINCT soh.sales_order) FROM sales_order_headers soh
            WHERE soh.sales_order IN (
                SELECT odi.reference_sd_document FROM outbound_delivery_items odi
                WHERE odi.reference_sd_document IS NOT NULL
                  AND odi.delivery_document IN (
                      SELECT bdi.reference_sd_document FROM billing_document_items bdi
                      WHERE bdi.reference_sd_document IS NOT NULL
                        AND bdi.billing_document IN (
                            SELECT bdh.billing_document FROM billing_document_headers bdh
                            WHERE bdh.accounting_document IS NOT NULL
                              AND bdh.accounting_document IN (
                                  SELECT DISTINCT je.accounting_document
                                  FROM journal_entry_items_accounts_receivable je
                                  WHERE je.accounting_document IN (
                                      SELECT DISTINCT clearing_accounting_document
                                      FROM payments_accounts_receivable
                                      WHERE clearing_accounting_document IS NOT NULL
                                  )
                              )
                        )
                  )
            )
        """),
    ]

    results = []
    for desc, sql in stages:
        cnt = query_scalar(conn, sql)
        results.append([desc, cnt])
    print(tabulate(results, headers=["Stage", "Count"], tablefmt="simple_grid"))


# ---------------------------------------------------------------------------
# 7. Sample broken records
# ---------------------------------------------------------------------------
def show_sample_broken_records(conn):
    print("\n=== SAMPLE BROKEN RECORDS ===")

    samples = [
        (
            "SalesOrders without any Delivery",
            """
            SELECT soh.sales_order, soh.sold_to_party, soh.creation_date
            FROM sales_order_headers soh
            WHERE soh.sales_order NOT IN (
                SELECT DISTINCT reference_sd_document FROM outbound_delivery_items
                WHERE reference_sd_document IS NOT NULL
            )
            LIMIT 5
            """,
            ["sales_order", "sold_to_party", "creation_date"],
        ),
        (
            "Invoices without JournalEntry",
            """
            SELECT bdh.billing_document, bdh.accounting_document, bdh.sold_to_party
            FROM billing_document_headers bdh
            WHERE bdh.accounting_document IS NULL
               OR bdh.accounting_document NOT IN (
                   SELECT DISTINCT accounting_document FROM journal_entry_items_accounts_receivable
               )
            LIMIT 5
            """,
            ["billing_document", "accounting_document", "sold_to_party"],
        ),
        (
            "Uncleared JournalEntries (no Payment)",
            """
            SELECT DISTINCT je.accounting_document, je.customer, je.posting_date
            FROM journal_entry_items_accounts_receivable je
            WHERE je.accounting_document NOT IN (
                SELECT DISTINCT clearing_accounting_document
                FROM payments_accounts_receivable
                WHERE clearing_accounting_document IS NOT NULL
            )
            LIMIT 5
            """,
            ["accounting_document", "customer", "posting_date"],
        ),
    ]

    for title, sql, cols in samples:
        rows = query(conn, sql)
        if rows:
            print(f"\n{title}:")
            print(tabulate(rows, headers=cols, tablefmt="simple_grid"))
        else:
            print(f"\n{title}: None found (OK)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        conn = psycopg2.connect(DSN)
    except Exception as e:
        print(f"ERROR: Cannot connect to database: {e}")
        print("Make sure PostgreSQL is running (docker-compose up -d)")
        sys.exit(1)

    try:
        print("=" * 70)
        print(" O2C RELATIONSHIP INTEGRITY ANALYSIS")
        print("=" * 70)

        print_row_counts(conn)
        orphan_results = run_orphan_checks(conn)
        cross_doc_results = validate_cross_doc_joins(conn)
        validate_customer_linkage(conn)
        validate_graph_edges(conn)
        detect_partial_flows(conn)
        show_sample_broken_records(conn)

        # --- Summary ---
        print("\n" + "=" * 70)
        print(" SUMMARY: ROOT CAUSES & RECOMMENDATIONS")
        print("=" * 70)

        issues = [r for r in orphan_results if r[0] == "ISSUE"]
        broken_joins = [r for r in cross_doc_results if r[0] == "BROKEN"]

        if not issues and not broken_joins:
            print("\nNo orphan or broken join issues detected.")
        else:
            print(f"\nOrphan issues: {len(issues)}")
            print(f"Broken joins: {len(broken_joins)}")
            print("\nPer-issue root cause analysis printed above.")
            print("\nCommon root causes:")
            print("  1. DATA: Missing rows / NULL FKs in source JSONL files")
            print("  2. INGESTION: Rows skipped during JSONL parsing (type/format errors)")
            print("  3. SCHEMA: sold_to_party ↔ business_partner identity mismatch")
            print("  4. GRAPH: Edge derivation uses sold_to_party as Customer node ID")
            print("     but /entities/Customer returns business_partner — ID mismatch")
            print("\nRecommendations:")
            print("  - Verify sold_to_party maps to business_partner (not customer column)")
            print("  - Add NULL-key warnings during ingestion")
            print("  - Add FK constraints or validation to migration scripts")
            print("  - Fix graph_repository Customer node ID if bp vs customer mismatch exists")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
