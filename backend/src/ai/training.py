"""Training data for the text-to-SQL RAG pipeline.

Trains ChromaDB with:
1. DDL schemas for all 17 tables
2. Documentation about O2C graph relationships and domain context
3. SQL question-answer pairs for common query patterns
"""

import hashlib
import structlog

from .embeddings import get_ddl_collection, get_docs_collection, get_sql_collection

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 1. DDL Training Data
# ---------------------------------------------------------------------------

DDL_SCHEMAS: list[str] = [
    """CREATE TABLE sales_order_headers (
    sales_order VARCHAR(255) PRIMARY KEY,
    sales_order_type VARCHAR(255),
    sales_organization VARCHAR(255),
    distribution_channel VARCHAR(255),
    organization_division VARCHAR(255),
    sold_to_party VARCHAR(255),  -- FK to business_partners.customer
    creation_date DATE,
    created_by_user VARCHAR(255),
    last_change_datetime TIMESTAMPTZ,
    total_net_amount NUMERIC(18,4),
    overall_delivery_status VARCHAR(255),
    transaction_currency VARCHAR(255),
    pricing_date DATE,
    requested_delivery_date DATE,
    incoterms_classification VARCHAR(255),
    incoterms_location1 VARCHAR(255),
    customer_payment_terms VARCHAR(255)
);""",
    """CREATE TABLE sales_order_items (
    sales_order VARCHAR(255) NOT NULL,
    sales_order_item VARCHAR(255) NOT NULL,
    sales_order_item_category VARCHAR(255),
    material VARCHAR(255),  -- FK to products.product
    requested_quantity NUMERIC(18,2),
    requested_quantity_unit VARCHAR(255),
    transaction_currency VARCHAR(255),
    net_amount NUMERIC(18,4),
    material_group VARCHAR(255),
    production_plant VARCHAR(255),
    storage_location VARCHAR(255),
    PRIMARY KEY (sales_order, sales_order_item)
);""",
    """CREATE TABLE outbound_delivery_headers (
    delivery_document VARCHAR(255) PRIMARY KEY,
    actual_goods_movement_date DATE,
    actual_goods_movement_time TIME,
    creation_date DATE,
    creation_time TIME,
    hdr_general_incompletion_status VARCHAR(255),
    last_change_date DATE,
    overall_goods_movement_status VARCHAR(255),
    overall_picking_status VARCHAR(255),
    shipping_point VARCHAR(255)
);""",
    """CREATE TABLE outbound_delivery_items (
    delivery_document VARCHAR(255) NOT NULL,
    delivery_document_item VARCHAR(255) NOT NULL,
    actual_delivery_quantity NUMERIC(18,2),
    batch VARCHAR(255),
    delivery_quantity_unit VARCHAR(255),
    plant VARCHAR(255),
    reference_sd_document VARCHAR(255),       -- FK back to sales_order_headers.sales_order
    reference_sd_document_item VARCHAR(255),   -- FK back to sales_order_items.sales_order_item
    storage_location VARCHAR(255),
    PRIMARY KEY (delivery_document, delivery_document_item)
);""",
    """CREATE TABLE billing_document_headers (
    billing_document VARCHAR(255) PRIMARY KEY,
    billing_document_type VARCHAR(255),
    creation_date DATE,
    creation_time TIME,
    last_change_datetime TIMESTAMPTZ,
    billing_document_date DATE,
    billing_document_is_cancelled BOOLEAN DEFAULT FALSE,
    cancelled_billing_document VARCHAR(255),
    total_net_amount NUMERIC(18,4),
    transaction_currency VARCHAR(255),
    company_code VARCHAR(255),
    fiscal_year VARCHAR(255),
    accounting_document VARCHAR(255),  -- FK to journal_entry_items_accounts_receivable.accounting_document
    sold_to_party VARCHAR(255)         -- FK to business_partners.customer
);""",
    """CREATE TABLE billing_document_items (
    billing_document VARCHAR(255) NOT NULL,
    billing_document_item VARCHAR(255) NOT NULL,
    material VARCHAR(255),
    billing_quantity NUMERIC(18,2),
    billing_quantity_unit VARCHAR(255),
    net_amount NUMERIC(18,4),
    transaction_currency VARCHAR(255),
    reference_sd_document VARCHAR(255),       -- FK back to outbound_delivery_headers.delivery_document
    reference_sd_document_item VARCHAR(255),   -- FK back to outbound_delivery_items.delivery_document_item
    PRIMARY KEY (billing_document, billing_document_item)
);""",
    """CREATE TABLE journal_entry_items_accounts_receivable (
    company_code VARCHAR(255) NOT NULL,
    fiscal_year VARCHAR(255) NOT NULL,
    accounting_document VARCHAR(255) NOT NULL,
    accounting_document_item VARCHAR(255) NOT NULL,
    gl_account VARCHAR(255),
    reference_document VARCHAR(255),
    profit_center VARCHAR(255),
    transaction_currency VARCHAR(255),
    amount_in_transaction_currency NUMERIC(18,4),
    company_code_currency VARCHAR(255),
    amount_in_company_code_currency NUMERIC(18,4),
    posting_date DATE,
    document_date DATE,
    accounting_document_type VARCHAR(255),
    last_change_datetime TIMESTAMPTZ,
    customer VARCHAR(255),
    financial_account_type VARCHAR(255),
    clearing_date DATE,
    clearing_accounting_document VARCHAR(255),  -- FK to payments clearing
    clearing_doc_fiscal_year VARCHAR(255),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);""",
    """CREATE TABLE payments_accounts_receivable (
    company_code VARCHAR(255) NOT NULL,
    fiscal_year VARCHAR(255) NOT NULL,
    accounting_document VARCHAR(255) NOT NULL,
    accounting_document_item VARCHAR(255) NOT NULL,
    clearing_date DATE,
    clearing_accounting_document VARCHAR(255),  -- FK to journal_entry_items_accounts_receivable.accounting_document
    clearing_doc_fiscal_year VARCHAR(255),
    amount_in_transaction_currency NUMERIC(18,4),
    transaction_currency VARCHAR(255),
    amount_in_company_code_currency NUMERIC(18,4),
    company_code_currency VARCHAR(255),
    customer VARCHAR(255),
    posting_date DATE,
    document_date DATE,
    gl_account VARCHAR(255),
    financial_account_type VARCHAR(255),
    profit_center VARCHAR(255),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);""",
    """CREATE TABLE business_partners (
    business_partner VARCHAR(255) PRIMARY KEY,
    customer VARCHAR(255),
    business_partner_category VARCHAR(255),
    business_partner_full_name VARCHAR(255),
    business_partner_grouping VARCHAR(255),
    business_partner_name VARCHAR(255),
    created_by_user VARCHAR(255),
    creation_date DATE,
    creation_time TIME,
    form_of_address VARCHAR(255),
    last_change_date DATE,
    organization_bp_name1 VARCHAR(255),
    organization_bp_name2 VARCHAR(255),
    business_partner_is_blocked BOOLEAN DEFAULT FALSE,
    is_marked_for_archiving BOOLEAN DEFAULT FALSE
);""",
    """CREATE TABLE business_partner_addresses (
    business_partner VARCHAR(255) NOT NULL,
    address_id VARCHAR(255) NOT NULL,
    validity_start_date DATE,
    validity_end_date DATE,
    address_uuid VARCHAR(255),
    address_time_zone VARCHAR(255),
    city_name VARCHAR(255),
    country VARCHAR(255),
    postal_code VARCHAR(255),
    region VARCHAR(255),
    street_name VARCHAR(255),
    PRIMARY KEY (business_partner, address_id)
);""",
    """CREATE TABLE products (
    product VARCHAR(255) PRIMARY KEY,
    product_type VARCHAR(255),
    creation_date DATE,
    created_by_user VARCHAR(255),
    last_change_date DATE,
    last_change_datetime TIMESTAMPTZ,
    is_marked_for_deletion BOOLEAN DEFAULT FALSE,
    product_old_id VARCHAR(255),
    gross_weight NUMERIC(18,2),
    weight_unit VARCHAR(255),
    net_weight NUMERIC(18,2),
    product_group VARCHAR(255),
    base_unit VARCHAR(255),
    division VARCHAR(255),
    industry_sector VARCHAR(255)
);""",
    """CREATE TABLE product_descriptions (
    product VARCHAR(255) NOT NULL,
    language VARCHAR(255) NOT NULL,
    product_description VARCHAR(255),
    PRIMARY KEY (product, language)
);""",
    """CREATE TABLE plants (
    plant VARCHAR(255) PRIMARY KEY,
    plant_name VARCHAR(255),
    valuation_area VARCHAR(255),
    plant_customer VARCHAR(255),
    plant_supplier VARCHAR(255),
    factory_calendar VARCHAR(255),
    sales_organization VARCHAR(255),
    address_id VARCHAR(255),
    distribution_channel VARCHAR(255),
    division VARCHAR(255),
    language VARCHAR(255),
    is_marked_for_archiving BOOLEAN DEFAULT FALSE
);""",
    """CREATE TABLE product_plants (
    product VARCHAR(255) NOT NULL,
    plant VARCHAR(255) NOT NULL,
    availability_check_type VARCHAR(255),
    profit_center VARCHAR(255),
    mrp_type VARCHAR(255),
    PRIMARY KEY (product, plant)
);""",
    """CREATE TABLE product_storage_locations (
    product VARCHAR(255) NOT NULL,
    plant VARCHAR(255) NOT NULL,
    storage_location VARCHAR(255) NOT NULL,
    PRIMARY KEY (product, plant, storage_location)
);""",
    """CREATE TABLE customer_company_assignments (
    customer VARCHAR(255) NOT NULL,
    company_code VARCHAR(255) NOT NULL,
    payment_terms VARCHAR(255),
    reconciliation_account VARCHAR(255),
    deletion_indicator BOOLEAN DEFAULT FALSE,
    customer_account_group VARCHAR(255),
    PRIMARY KEY (customer, company_code)
);""",
    """CREATE TABLE customer_sales_area_assignments (
    customer VARCHAR(255) NOT NULL,
    sales_organization VARCHAR(255) NOT NULL,
    distribution_channel VARCHAR(255) NOT NULL,
    division VARCHAR(255) NOT NULL,
    complete_delivery_is_defined BOOLEAN DEFAULT FALSE,
    currency VARCHAR(255),
    customer_payment_terms VARCHAR(255),
    delivery_priority VARCHAR(255),
    incoterms_classification VARCHAR(255),
    incoterms_location1 VARCHAR(255),
    shipping_condition VARCHAR(255),
    exchange_rate_type VARCHAR(255),
    PRIMARY KEY (customer, sales_organization, distribution_channel, division)
);""",
]


# ---------------------------------------------------------------------------
# 2. Domain Documentation
# ---------------------------------------------------------------------------

DOCUMENTATION: list[str] = [
    # O2C flow overview
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

    # Table relationships
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

    # Item number normalization
    """IMPORTANT: Item numbers have different formats across tables.
In source tables (sales_order_items, outbound_delivery_items, billing_document_items), item numbers
are zero-padded like '000010', '000020'. In cross-document reference fields (reference_sd_document_item),
they may be stored as '10', '20' without padding. When joining across documents, either use
REGEXP_REPLACE(column, '^0+', '') to strip leading zeros, or CAST to integer for comparison.""",

    # Billing document types
    """Billing documents can be invoices or cancellations:
- billing_document_headers has billing_document_is_cancelled flag
- billing_document_cancellations table stores cancellation documents
- cancelled_billing_document in billing_document_headers references the original document
To find active (non-cancelled) invoices: WHERE billing_document_is_cancelled = FALSE""",

    # Business partners and customers
    """Business partners and customers are related but distinct:
- business_partners.business_partner is the BP ID
- business_partners.customer is the customer number used in sales/billing
- sales_order_headers.sold_to_party references business_partners.customer (NOT business_partner)
- billing_document_headers.sold_to_party also references business_partners.customer
- To find a customer name: JOIN business_partners ON customer = sold_to_party""",

    # Delivery and fulfillment status
    """Delivery status tracking:
- sales_order_headers.overall_delivery_status: 'A' = not delivered, 'B' = partially delivered, 'C' = fully delivered
- outbound_delivery_headers.overall_goods_movement_status: 'A' = not started, 'C' = completed
- outbound_delivery_headers.overall_picking_status: 'A' = not started, 'B' = partial, 'C' = completed
A 'broken flow' means a sales order that has been delivered but not billed, or billed without delivery.""",

    # Financial data
    """Financial amounts:
- All amount fields use NUMERIC(18,4) precision
- transaction_currency stores the ISO currency code (e.g., 'USD', 'EUR')
- Journal entries have both transaction currency and company code currency amounts
- Payments have clearing_accounting_document that links back to the journal entry they clear
- amount_in_transaction_currency can be negative for credit memos""",
]


# ---------------------------------------------------------------------------
# 3. SQL Question-Answer Pairs
# ---------------------------------------------------------------------------

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


def _content_hash(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()[:12]


def train_all() -> dict[str, int]:
    """Load all training data into ChromaDB collections. Returns counts."""
    ddl_col = get_ddl_collection()
    docs_col = get_docs_collection()
    sql_col = get_sql_collection()

    # Train DDL
    ddl_ids = []
    ddl_docs = []
    for i, ddl in enumerate(DDL_SCHEMAS):
        doc_id = f"ddl-{i}-{_content_hash(ddl)}"
        ddl_ids.append(doc_id)
        ddl_docs.append(ddl)

    if ddl_ids:
        ddl_col.upsert(ids=ddl_ids, documents=ddl_docs)
    logger.info("train.ddl", count=len(ddl_ids))

    # Train documentation
    doc_ids = []
    doc_docs = []
    for i, doc in enumerate(DOCUMENTATION):
        doc_id = f"doc-{i}-{_content_hash(doc)}"
        doc_ids.append(doc_id)
        doc_docs.append(doc)

    if doc_ids:
        docs_col.upsert(ids=doc_ids, documents=doc_docs)
    logger.info("train.docs", count=len(doc_ids))

    # Train SQL pairs
    sql_ids = []
    sql_docs = []
    sql_metas = []
    for i, (question, sql) in enumerate(SQL_PAIRS):
        doc_id = f"sql-{i}-{_content_hash(question)}"
        sql_ids.append(doc_id)
        sql_docs.append(question)
        sql_metas.append({"sql": sql, "question": question})

    if sql_ids:
        sql_col.upsert(ids=sql_ids, documents=sql_docs, metadatas=sql_metas)
    logger.info("train.sql_pairs", count=len(sql_ids))

    counts = {"ddl": len(ddl_ids), "documentation": len(doc_ids), "sql_pairs": len(sql_ids)}
    logger.info("train.complete", **counts)
    return counts
