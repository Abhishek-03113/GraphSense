"""Training pipeline for the text-to-SQL RAG system.

Trains pgvector rag_embeddings table with:
1. Schema (DDL) — dynamically extracted from the live database
2. Relationships — FK constraints + full O2C chain narrative
3. Data profiles — per-table statistical summaries from actual data
4. SQL pairs — curated question→SQL examples (ground truth, static)
5. Documentation — domain context documentation (static)

Usage:
    POST /api/chat/train  — triggers train_all() via the API
"""

import structlog

from .embeddings import (
    content_hash,
    generate_embeddings,
    upsert_embeddings,
    clear_category,
)
from .schema_ingestion import ingest_schema
from .data_profiling import ingest_data_profiles

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Static curated knowledge (kept as ground truth — does not change with data)
# ---------------------------------------------------------------------------

DOCUMENTATION: list[str] = [
    """This is an SAP Order-to-Cash (O2C) dataset. The O2C process flow is:
Customer places a Sales Order -> Sales Order has line items (Sales Order Items) ->
Each Sales Order Item references a Product (material) ->
Outbound Deliveries fulfill Sales Order Items ->
Billing Documents (Invoices) bill for Delivery Items ->
Invoices generate Journal Entries (accounting documents) ->
Payments clear Journal Entries.

The full flow chain is: Customer -> SalesOrder -> SalesOrderItem -> Product,
SalesOrderItem <- DeliveryItem <- Delivery,
DeliveryItem <- InvoiceItem <- Invoice -> Customer,
Invoice -> JournalEntry <- Payment.""",

    """Key relationships between tables:
- sales_order_headers.sold_to_party = business_partners.customer (Customer who placed the order)
- sales_order_items.sales_order = sales_order_headers.sales_order (Order line items)
- sales_order_items.material = products.product (Product ordered)
- outbound_delivery_items.reference_sd_document = sales_order_headers.sales_order (Delivery fulfills SO)
- outbound_delivery_items.reference_sd_document_item = sales_order_items.sales_order_item (Delivery item fulfills SO item)
- billing_document_items.reference_sd_document = outbound_delivery_headers.delivery_document (Invoice bills for delivery)
- billing_document_items.reference_sd_document_item = outbound_delivery_items.delivery_document_item (Invoice item bills delivery item)
- billing_document_headers.sold_to_party = business_partners.customer (Invoice billed to customer)
- billing_document_headers.accounting_document = journal_entry_items_accounts_receivable.accounting_document (Invoice generates journal entry)
- payments_accounts_receivable.clearing_accounting_document = journal_entry_items_accounts_receivable.accounting_document (Payment clears journal entry)
- business_partner_addresses.business_partner = business_partners.business_partner (Customer address)""",

    """IMPORTANT: Item numbers have different formats across tables.
In source tables (sales_order_items, outbound_delivery_items, billing_document_items), item numbers
are zero-padded like '000010', '000020'. In cross-document reference fields (reference_sd_document_item),
they may be stored as '10', '20' without padding. When joining across documents, either use
REGEXP_REPLACE(column, '^0+', '') to strip leading zeros, or CAST to integer for comparison.""",

    """Billing documents can be invoices or cancellations:
- billing_document_headers has billing_document_is_cancelled flag
- billing_document_cancellations table stores cancellation documents
- cancelled_billing_document in billing_document_headers references the original document
To find active (non-cancelled) invoices: WHERE billing_document_is_cancelled = FALSE""",

    """Business partners and customers are related but distinct:
- business_partners.business_partner is the BP ID
- business_partners.customer is the customer number used in sales/billing
- sales_order_headers.sold_to_party references business_partners.customer (NOT business_partner)
- billing_document_headers.sold_to_party also references business_partners.customer
- To find a customer name: JOIN business_partners ON customer = sold_to_party""",

    """Delivery status tracking:
- sales_order_headers.overall_delivery_status: 'A' = not delivered, 'B' = partially delivered, 'C' = fully delivered
- outbound_delivery_headers.overall_goods_movement_status: 'A' = not started, 'C' = completed
- outbound_delivery_headers.overall_picking_status: 'A' = not started, 'B' = partial, 'C' = completed
A 'broken flow' means a sales order that has been delivered but not billed, or billed without delivery.""",

    """Financial amounts:
- All amount fields use NUMERIC(18,4) precision
- transaction_currency stores the ISO currency code (e.g., 'USD', 'EUR')
- Journal entries have both transaction currency and company code currency amounts
- Payments have clearing_accounting_document that links back to the journal entry they clear
- amount_in_transaction_currency can be negative for credit memos""",
]

SQL_PAIRS: list[tuple[str, str]] = [
    (
        "Which products are associated with the highest number of billing documents?",
        """SELECT p.product, pd.product_description, COUNT(DISTINCT bdi.billing_document) AS billing_doc_count
FROM billing_document_items bdi
JOIN products p ON bdi.material = p.product
LEFT JOIN product_descriptions pd ON p.product = pd.product AND pd.language = 'EN'
GROUP BY p.product, pd.product_description
ORDER BY billing_doc_count DESC
LIMIT 10;"""
    ),
    (
        "Trace the full flow of a billing document",
        """SELECT
    bdh.billing_document AS invoice,
    bdh.sold_to_party AS customer,
    bp.business_partner_full_name AS customer_name,
    bdi.reference_sd_document AS delivery,
    odi.reference_sd_document AS sales_order,
    soh.sold_to_party AS so_customer,
    bdh.accounting_document AS journal_entry,
    bdh.total_net_amount AS invoice_amount,
    bdh.transaction_currency,
    soh.total_net_amount AS order_amount,
    soh.creation_date AS order_date,
    bdh.billing_document_date AS invoice_date
FROM billing_document_headers bdh
JOIN billing_document_items bdi ON bdh.billing_document = bdi.billing_document
LEFT JOIN outbound_delivery_items odi
    ON bdi.reference_sd_document = odi.delivery_document
    AND REGEXP_REPLACE(bdi.reference_sd_document_item, '^0+', '') = REGEXP_REPLACE(odi.delivery_document_item, '^0+', '')
LEFT JOIN sales_order_headers soh ON odi.reference_sd_document = soh.sales_order
LEFT JOIN business_partners bp ON bdh.sold_to_party = bp.customer
LIMIT 20;"""
    ),
    (
        "Find sales orders that have been delivered but not billed",
        """SELECT DISTINCT soh.sales_order, soh.sold_to_party AS customer,
    soh.total_net_amount, soh.creation_date, soh.overall_delivery_status
FROM sales_order_headers soh
JOIN sales_order_items soi ON soh.sales_order = soi.sales_order
JOIN outbound_delivery_items odi
    ON odi.reference_sd_document = soh.sales_order
    AND REGEXP_REPLACE(odi.reference_sd_document_item, '^0+', '') = REGEXP_REPLACE(soi.sales_order_item, '^0+', '')
WHERE NOT EXISTS (
    SELECT 1 FROM billing_document_items bdi
    JOIN outbound_delivery_items odi2
        ON bdi.reference_sd_document = odi2.delivery_document
        AND REGEXP_REPLACE(bdi.reference_sd_document_item, '^0+', '') = REGEXP_REPLACE(odi2.delivery_document_item, '^0+', '')
    WHERE odi2.reference_sd_document = soh.sales_order
)
LIMIT 20;"""
    ),
    (
        "Find sales orders that were billed but never delivered",
        """SELECT DISTINCT soh.sales_order, soh.sold_to_party AS customer,
    soh.total_net_amount, soh.creation_date
FROM sales_order_headers soh
JOIN billing_document_headers bdh ON bdh.sold_to_party = soh.sold_to_party
WHERE soh.overall_delivery_status = 'A'
AND bdh.billing_document_is_cancelled = FALSE
LIMIT 20;"""
    ),
    (
        "What is the total revenue by customer?",
        """SELECT bp.customer, bp.business_partner_full_name,
    SUM(bdh.total_net_amount) AS total_revenue,
    COUNT(DISTINCT bdh.billing_document) AS invoice_count,
    bdh.transaction_currency
FROM billing_document_headers bdh
JOIN business_partners bp ON bdh.sold_to_party = bp.customer
WHERE bdh.billing_document_is_cancelled = FALSE
GROUP BY bp.customer, bp.business_partner_full_name, bdh.transaction_currency
ORDER BY total_revenue DESC
LIMIT 20;"""
    ),
    (
        "Show the complete O2C flow for a specific sales order",
        """SELECT
    soh.sales_order,
    soh.sold_to_party AS customer,
    soi.sales_order_item,
    soi.material AS product,
    soi.net_amount AS item_amount,
    odh.delivery_document,
    odi.actual_delivery_quantity,
    bdh.billing_document AS invoice,
    bdh.total_net_amount AS invoice_amount,
    bdh.accounting_document AS journal_entry,
    par.accounting_document AS payment_document
FROM sales_order_headers soh
JOIN sales_order_items soi ON soh.sales_order = soi.sales_order
LEFT JOIN outbound_delivery_items odi
    ON odi.reference_sd_document = soh.sales_order
    AND REGEXP_REPLACE(odi.reference_sd_document_item, '^0+', '') = REGEXP_REPLACE(soi.sales_order_item, '^0+', '')
LEFT JOIN outbound_delivery_headers odh ON odi.delivery_document = odh.delivery_document
LEFT JOIN billing_document_items bdi
    ON bdi.reference_sd_document = odi.delivery_document
    AND REGEXP_REPLACE(bdi.reference_sd_document_item, '^0+', '') = REGEXP_REPLACE(odi.delivery_document_item, '^0+', '')
LEFT JOIN billing_document_headers bdh ON bdi.billing_document = bdh.billing_document
LEFT JOIN journal_entry_items_accounts_receivable je
    ON bdh.accounting_document = je.accounting_document
LEFT JOIN payments_accounts_receivable par
    ON je.accounting_document = par.clearing_accounting_document
LIMIT 30;"""
    ),
    (
        "How many sales orders, deliveries, invoices, and payments are there?",
        """SELECT
    (SELECT COUNT(*) FROM sales_order_headers) AS sales_orders,
    (SELECT COUNT(*) FROM outbound_delivery_headers) AS deliveries,
    (SELECT COUNT(*) FROM billing_document_headers WHERE billing_document_is_cancelled = FALSE) AS invoices,
    (SELECT COUNT(DISTINCT accounting_document) FROM payments_accounts_receivable) AS payments;"""
    ),
    (
        "What are the top selling products by quantity?",
        """SELECT soi.material AS product, pd.product_description,
    SUM(soi.requested_quantity) AS total_quantity,
    soi.requested_quantity_unit AS unit,
    COUNT(DISTINCT soi.sales_order) AS order_count
FROM sales_order_items soi
JOIN products p ON soi.material = p.product
LEFT JOIN product_descriptions pd ON p.product = pd.product AND pd.language = 'EN'
GROUP BY soi.material, pd.product_description, soi.requested_quantity_unit
ORDER BY total_quantity DESC
LIMIT 10;"""
    ),
    (
        "Show invoices that have not been paid yet",
        """SELECT bdh.billing_document, bdh.sold_to_party AS customer,
    bp.business_partner_full_name AS customer_name,
    bdh.total_net_amount, bdh.transaction_currency,
    bdh.billing_document_date, bdh.accounting_document
FROM billing_document_headers bdh
LEFT JOIN business_partners bp ON bdh.sold_to_party = bp.customer
WHERE bdh.billing_document_is_cancelled = FALSE
AND bdh.accounting_document IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM payments_accounts_receivable par
    WHERE par.clearing_accounting_document = bdh.accounting_document
)
LIMIT 20;"""
    ),
    (
        "Which customers have the most sales orders?",
        """SELECT bp.customer, bp.business_partner_full_name,
    COUNT(DISTINCT soh.sales_order) AS order_count,
    SUM(soh.total_net_amount) AS total_amount,
    soh.transaction_currency
FROM sales_order_headers soh
JOIN business_partners bp ON soh.sold_to_party = bp.customer
GROUP BY bp.customer, bp.business_partner_full_name, soh.transaction_currency
ORDER BY order_count DESC
LIMIT 10;"""
    ),
    (
        "Show customer addresses",
        """SELECT bp.customer, bp.business_partner_full_name,
    bpa.city_name, bpa.region, bpa.country, bpa.postal_code, bpa.street_name
FROM business_partners bp
JOIN business_partner_addresses bpa ON bp.business_partner = bpa.business_partner
LIMIT 20;"""
    ),
    (
        "What is the average order value?",
        """SELECT
    AVG(total_net_amount) AS avg_order_value,
    MIN(total_net_amount) AS min_order_value,
    MAX(total_net_amount) AS max_order_value,
    transaction_currency
FROM sales_order_headers
WHERE total_net_amount IS NOT NULL
GROUP BY transaction_currency;"""
    ),
    (
        "Show the monthly sales trend",
        """SELECT DATE_TRUNC('month', creation_date) AS month,
    COUNT(*) AS order_count,
    SUM(total_net_amount) AS total_amount,
    transaction_currency
FROM sales_order_headers
WHERE creation_date IS NOT NULL
GROUP BY DATE_TRUNC('month', creation_date), transaction_currency
ORDER BY month;"""
    ),
    (
        "List all products with their descriptions",
        """SELECT p.product, pd.product_description, p.product_type,
    p.product_group, p.base_unit, p.gross_weight, p.weight_unit
FROM products p
LEFT JOIN product_descriptions pd ON p.product = pd.product AND pd.language = 'EN'
ORDER BY p.product
LIMIT 50;"""
    ),
    (
        "Find incomplete O2C flows where delivery exists but no invoice",
        """SELECT DISTINCT
    soh.sales_order,
    soh.sold_to_party AS customer,
    odh.delivery_document,
    soh.total_net_amount,
    soh.creation_date AS order_date,
    odh.creation_date AS delivery_date,
    'Delivered but not billed' AS status
FROM sales_order_headers soh
JOIN outbound_delivery_items odi ON odi.reference_sd_document = soh.sales_order
JOIN outbound_delivery_headers odh ON odi.delivery_document = odh.delivery_document
WHERE NOT EXISTS (
    SELECT 1 FROM billing_document_items bdi
    WHERE bdi.reference_sd_document = odi.delivery_document
)
LIMIT 20;"""
    ),
]


# ---------------------------------------------------------------------------
# Static training helpers
# ---------------------------------------------------------------------------


def _embed_and_prepare(
    texts: list[str],
    category: str,
    metadatas: list[dict] | None = None,
) -> list[dict]:
    """Generate embeddings and build upsert-ready rows."""
    if not texts:
        return []

    embeddings = generate_embeddings(texts)
    items: list[dict] = []

    for i, (txt, emb) in enumerate(zip(texts, embeddings)):
        items.append({
            "category": category,
            "content": txt,
            "metadata": metadatas[i] if metadatas else {},
            "embedding": emb,
            "content_hash": content_hash(f"{category}:{txt}"),
        })

    return items


def _train_sql_pairs(engine) -> int:
    """Embed curated SQL question→answer pairs and upsert under 'sql_pair'."""
    clear_category(engine, "sql_pair")
    questions = [q for q, _ in SQL_PAIRS]
    sql_metas = [{"sql": sql, "question": q} for q, sql in SQL_PAIRS]
    items = _embed_and_prepare(questions, "sql_pair", sql_metas)
    count = upsert_embeddings(engine, items)
    logger.info("train.sql_pairs", count=count)
    return count


def _train_documentation(engine) -> int:
    """Embed domain documentation strings and upsert under 'documentation'."""
    clear_category(engine, "documentation")
    items = _embed_and_prepare(DOCUMENTATION, "documentation")
    count = upsert_embeddings(engine, items)
    logger.info("train.documentation", count=count)
    return count


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------


def train_all() -> dict[str, int]:
    """Dynamically train all RAG categories from the live database.

    Categories trained:
    - 'schema'        — one embedding per table (reconstructed DDL from DB)
    - 'relationships' — FK constraints + full O2C chain narrative
    - 'data_profile'  — per-table statistical summaries from actual data
    - 'sql_pair'      — curated question→SQL examples (static ground truth)
    - 'documentation' — domain context documentation (static)

    Returns dict with upserted count per category.
    """
    from src.ai.chat import _get_sync_engine

    engine = _get_sync_engine()
    counts: dict[str, int] = {}

    # Dynamic: introspect live DB
    schema_counts = ingest_schema(engine)
    counts.update(schema_counts)

    data_count = ingest_data_profiles(engine)
    counts["data_profile"] = data_count

    # Static: curated knowledge that doesn't change with data
    counts["sql_pair"] = _train_sql_pairs(engine)
    counts["documentation"] = _train_documentation(engine)

    logger.info("train.complete", **counts)
    return counts
