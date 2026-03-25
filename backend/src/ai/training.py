"""Training data for the text-to-SQL RAG pipeline.

Trains pgvector rag_embeddings table with:
1. DDL schemas for all 17 tables
2. Documentation about O2C graph relationships and domain context
3. SQL question-answer pairs for common query patterns
4. Data summaries derived from ingested PostgreSQL data
"""

import structlog
from sqlalchemy import text

from .embeddings import (
    content_hash,
    generate_embeddings,
    upsert_embeddings,
)

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


# ---------------------------------------------------------------------------
# 4. Data-driven summaries from ingested PostgreSQL data
# ---------------------------------------------------------------------------

DATA_SUMMARY_QUERIES: list[tuple[str, str]] = [
    (
        "customer_overview",
        """SELECT
            'The dataset contains ' || COUNT(DISTINCT bp.customer) || ' customers. '
            || 'Top customers by order volume: '
            || string_agg(sub.summary, '; ')
        AS summary
        FROM business_partners bp,
        LATERAL (
            SELECT bp2.customer || ' (' || bp2.business_partner_full_name || ', '
                || COUNT(DISTINCT soh.sales_order) || ' orders, '
                || COALESCE(SUM(soh.total_net_amount)::text, '0') || ' ' || COALESCE(soh.transaction_currency, '') || ')'
                AS summary
            FROM business_partners bp2
            JOIN sales_order_headers soh ON soh.sold_to_party = bp2.customer
            GROUP BY bp2.customer, bp2.business_partner_full_name, soh.transaction_currency
            ORDER BY COUNT(DISTINCT soh.sales_order) DESC
            LIMIT 10
        ) sub;""",
    ),
    (
        "product_overview",
        """SELECT
            'The dataset contains ' || COUNT(DISTINCT p.product) || ' products. '
            || 'Top products by sales volume: '
            || string_agg(sub.summary, '; ')
        AS summary
        FROM products p,
        LATERAL (
            SELECT p2.product || ' (' || COALESCE(pd.product_description, 'no description') || ', '
                || COALESCE(SUM(soi.requested_quantity)::text, '0') || ' units across '
                || COUNT(DISTINCT soi.sales_order) || ' orders)'
                AS summary
            FROM products p2
            LEFT JOIN product_descriptions pd ON p2.product = pd.product AND pd.language = 'EN'
            JOIN sales_order_items soi ON soi.material = p2.product
            GROUP BY p2.product, pd.product_description
            ORDER BY SUM(soi.requested_quantity) DESC NULLS LAST
            LIMIT 10
        ) sub;""",
    ),
    (
        "order_statistics",
        """SELECT
            'Sales order statistics: '
            || COUNT(*) || ' total orders, '
            || 'total value ' || COALESCE(SUM(total_net_amount)::text, '0') || ' ' || COALESCE(transaction_currency, '') || ', '
            || 'average order value ' || COALESCE(ROUND(AVG(total_net_amount), 2)::text, '0') || ', '
            || 'date range: ' || COALESCE(MIN(creation_date)::text, 'N/A') || ' to ' || COALESCE(MAX(creation_date)::text, 'N/A') || '. '
            || 'Delivery status breakdown: '
            || string_agg(DISTINCT
                CASE overall_delivery_status
                    WHEN 'A' THEN 'Not delivered'
                    WHEN 'B' THEN 'Partially delivered'
                    WHEN 'C' THEN 'Fully delivered'
                    ELSE overall_delivery_status
                END || ': ' || cnt::text, ', ')
        AS summary
        FROM sales_order_headers,
        LATERAL (
            SELECT overall_delivery_status AS ds, COUNT(*) AS cnt
            FROM sales_order_headers
            GROUP BY overall_delivery_status
        ) status_counts
        GROUP BY transaction_currency;""",
    ),
    (
        "billing_overview",
        """SELECT
            'Billing overview: '
            || COUNT(*) || ' total billing documents, '
            || COUNT(*) FILTER (WHERE billing_document_is_cancelled = FALSE) || ' active invoices, '
            || COUNT(*) FILTER (WHERE billing_document_is_cancelled = TRUE) || ' cancelled, '
            || 'total invoiced amount: ' || COALESCE(SUM(total_net_amount) FILTER (WHERE billing_document_is_cancelled = FALSE)::text, '0')
            || ' ' || COALESCE(transaction_currency, '') || ', '
            || 'date range: ' || COALESCE(MIN(billing_document_date)::text, 'N/A')
            || ' to ' || COALESCE(MAX(billing_document_date)::text, 'N/A')
        AS summary
        FROM billing_document_headers
        GROUP BY transaction_currency;""",
    ),
    (
        "payment_overview",
        """SELECT
            'Payment overview: '
            || COUNT(DISTINCT accounting_document) || ' payment documents, '
            || 'total payment amount: ' || COALESCE(SUM(amount_in_transaction_currency)::text, '0')
            || ' ' || COALESCE(transaction_currency, '') || ', '
            || 'date range: ' || COALESCE(MIN(posting_date)::text, 'N/A')
            || ' to ' || COALESCE(MAX(posting_date)::text, 'N/A')
        AS summary
        FROM payments_accounts_receivable
        GROUP BY transaction_currency;""",
    ),
    (
        "delivery_overview",
        """SELECT
            'Delivery overview: '
            || COUNT(*) || ' outbound deliveries, '
            || 'goods movement status — completed: '
            || COUNT(*) FILTER (WHERE overall_goods_movement_status = 'C')
            || ', not started: '
            || COUNT(*) FILTER (WHERE overall_goods_movement_status = 'A')
            || '. Picking status — completed: '
            || COUNT(*) FILTER (WHERE overall_picking_status = 'C')
            || ', partial: '
            || COUNT(*) FILTER (WHERE overall_picking_status = 'B')
            || ', not started: '
            || COUNT(*) FILTER (WHERE overall_picking_status = 'A')
            || '. Date range: ' || COALESCE(MIN(creation_date)::text, 'N/A')
            || ' to ' || COALESCE(MAX(creation_date)::text, 'N/A')
        AS summary
        FROM outbound_delivery_headers;""",
    ),
    (
        "plant_overview",
        """SELECT
            'The dataset contains ' || COUNT(*) || ' plants: '
            || string_agg(plant || ' (' || COALESCE(plant_name, 'unnamed') || ')', ', ')
        AS summary
        FROM plants;""",
    ),
    (
        "flow_completeness",
        """SELECT
            'O2C flow completeness: '
            || 'Orders with deliveries: ' || COUNT(DISTINCT soh.sales_order) FILTER (
                WHERE EXISTS (SELECT 1 FROM outbound_delivery_items odi WHERE odi.reference_sd_document = soh.sales_order)
            ) || ' of ' || COUNT(DISTINCT soh.sales_order) || ' total orders. '
            || 'Orders with invoices: ' || COUNT(DISTINCT soh.sales_order) FILTER (
                WHERE EXISTS (
                    SELECT 1 FROM outbound_delivery_items odi
                    JOIN billing_document_items bdi ON bdi.reference_sd_document = odi.delivery_document
                    WHERE odi.reference_sd_document = soh.sales_order
                )
            ) || '. '
            || 'Invoices with journal entries: ' || (
                SELECT COUNT(*) FROM billing_document_headers WHERE accounting_document IS NOT NULL AND billing_document_is_cancelled = FALSE
            ) || '. '
            || 'Journal entries with payments: ' || (
                SELECT COUNT(DISTINCT je.accounting_document)
                FROM journal_entry_items_accounts_receivable je
                WHERE EXISTS (SELECT 1 FROM payments_accounts_receivable p WHERE p.clearing_accounting_document = je.accounting_document)
            )
        AS summary
        FROM sales_order_headers soh;""",
    ),
]


# ---------------------------------------------------------------------------
# Train functions
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


def _train_static(engine) -> dict[str, int]:
    """Train DDL, docs, and SQL pairs (static data)."""
    # DDL schemas
    ddl_items = _embed_and_prepare(DDL_SCHEMAS, "ddl")
    ddl_count = upsert_embeddings(engine, ddl_items)
    logger.info("train.ddl", count=ddl_count)

    # Documentation
    doc_items = _embed_and_prepare(DOCUMENTATION, "documentation")
    doc_count = upsert_embeddings(engine, doc_items)
    logger.info("train.docs", count=doc_count)

    # SQL pairs — embed the question, store the SQL in metadata
    questions = [q for q, _ in SQL_PAIRS]
    sql_metas = [{"sql": sql, "question": q} for q, sql in SQL_PAIRS]
    sql_items = _embed_and_prepare(questions, "sql_pair", sql_metas)
    sql_count = upsert_embeddings(engine, sql_items)
    logger.info("train.sql_pairs", count=sql_count)

    return {"ddl": ddl_count, "documentation": doc_count, "sql_pairs": sql_count}


def _train_data_summaries(engine) -> int:
    """Generate and embed summaries from actual ingested data."""
    summaries: list[str] = []
    metas: list[dict] = []

    with engine.connect() as conn:
        for name, query in DATA_SUMMARY_QUERIES:
            try:
                row = conn.execute(text(query)).fetchone()
                if row and row[0]:
                    summary = str(row[0])
                    summaries.append(summary)
                    metas.append({"source_query": name})
                    logger.info("train.data_summary.ok", name=name, length=len(summary))
                else:
                    logger.warning("train.data_summary.empty", name=name)
            except Exception:
                logger.exception("train.data_summary.failed", name=name)

    if not summaries:
        return 0

    items = _embed_and_prepare(summaries, "data_summary", metas)
    count = upsert_embeddings(engine, items)
    logger.info("train.data_summaries", count=count)
    return count


def train_all() -> dict[str, int]:
    """Load all training data into pgvector rag_embeddings. Returns counts."""
    from src.ai.chat import _get_sync_engine

    engine = _get_sync_engine()

    counts = _train_static(engine)
    data_count = _train_data_summaries(engine)
    counts["data_summaries"] = data_count

    logger.info("train.complete", **counts)
    return counts
