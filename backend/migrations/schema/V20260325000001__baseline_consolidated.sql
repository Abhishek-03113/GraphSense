-- Migration: Consolidated baseline schema for SAP O2C data model
-- Category: schema
-- Combines original DDL with dropped empty columns (from EDA analysis)

CREATE TABLE IF NOT EXISTS billing_document_headers (
    billing_document           VARCHAR(255)    NOT NULL PRIMARY KEY,
    billing_document_type      VARCHAR(255),
    creation_date              DATE,
    creation_time              TIME,
    last_change_datetime       TIMESTAMPTZ,
    billing_document_date      DATE,
    billing_document_is_cancelled BOOLEAN     DEFAULT FALSE,
    cancelled_billing_document VARCHAR(255),
    total_net_amount           NUMERIC(18, 4),
    transaction_currency       VARCHAR(255),
    company_code               VARCHAR(255),
    fiscal_year                VARCHAR(255),
    accounting_document        VARCHAR(255),
    sold_to_party              VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS billing_document_cancellations (
    billing_document              VARCHAR(255)    NOT NULL PRIMARY KEY,
    billing_document_type         VARCHAR(255),
    creation_date                 DATE,
    creation_time                 TIME,
    last_change_datetime          TIMESTAMPTZ,
    billing_document_date         DATE,
    billing_document_is_cancelled BOOLEAN        DEFAULT FALSE,
    -- cancelled_billing_document dropped (100% null in data)
    total_net_amount              NUMERIC(18, 4),
    transaction_currency          VARCHAR(255),
    company_code                  VARCHAR(255),
    fiscal_year                   VARCHAR(255),
    accounting_document           VARCHAR(255),
    sold_to_party                 VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS billing_document_items (
    billing_document          VARCHAR(255)   NOT NULL,
    billing_document_item     VARCHAR(255)    NOT NULL,
    material                  VARCHAR(255),
    billing_quantity          NUMERIC(18, 2),
    billing_quantity_unit     VARCHAR(255),
    net_amount                NUMERIC(18, 4),
    transaction_currency      VARCHAR(255),
    reference_sd_document     VARCHAR(255),
    reference_sd_document_item VARCHAR(255),
    PRIMARY KEY (billing_document, billing_document_item)
);

CREATE TABLE IF NOT EXISTS business_partner_addresses (
    business_partner           VARCHAR(255)   NOT NULL,
    address_id                 VARCHAR(255)   NOT NULL,
    validity_start_date        DATE,
    validity_end_date          DATE,
    address_uuid               VARCHAR(255),
    address_time_zone          VARCHAR(255),
    city_name                  VARCHAR(255),
    country                    VARCHAR(255),
    -- po_box, po_box_deviating_*, po_box_lobby_name, po_box_postal_code dropped (100% null)
    po_box_is_without_number   BOOLEAN       DEFAULT FALSE,
    postal_code                VARCHAR(255),
    region                     VARCHAR(255),
    street_name                VARCHAR(255),
    -- tax_jurisdiction, transport_zone dropped (100% null)
    PRIMARY KEY (business_partner, address_id)
);

CREATE TABLE IF NOT EXISTS business_partners (
    business_partner           VARCHAR(255)   NOT NULL PRIMARY KEY,
    customer                   VARCHAR(255),
    business_partner_category  VARCHAR(255),
    business_partner_full_name VARCHAR(255),
    business_partner_grouping  VARCHAR(255),
    business_partner_name      VARCHAR(255),
    -- correspondence_language dropped (100% null)
    created_by_user            VARCHAR(255),
    creation_date              DATE,
    creation_time              TIME,
    -- first_name, last_name dropped (100% null)
    form_of_address            VARCHAR(255),
    -- industry dropped (100% null)
    last_change_date           DATE,
    organization_bp_name1      VARCHAR(255),
    organization_bp_name2      VARCHAR(255),
    business_partner_is_blocked BOOLEAN      DEFAULT FALSE,
    is_marked_for_archiving    BOOLEAN       DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS customer_company_assignments (
    customer                         VARCHAR(255)   NOT NULL,
    company_code                     VARCHAR(255)    NOT NULL,
    -- accounting_clerk, accounting_clerk_fax_number, accounting_clerk_internet_address,
    -- accounting_clerk_phone_number, alternative_payer_account, payment_blocking_reason,
    -- payment_methods_list dropped (100% null)
    payment_terms                    VARCHAR(255),
    reconciliation_account           VARCHAR(255),
    deletion_indicator               BOOLEAN       DEFAULT FALSE,
    customer_account_group           VARCHAR(255),
    PRIMARY KEY (customer, company_code)
);

CREATE TABLE IF NOT EXISTS customer_sales_area_assignments (
    customer                      VARCHAR(255)   NOT NULL,
    sales_organization            VARCHAR(255)    NOT NULL,
    distribution_channel          VARCHAR(255)    NOT NULL,
    division                      VARCHAR(255)    NOT NULL,
    -- billing_is_blocked_for_customer, credit_control_area dropped (100% null)
    complete_delivery_is_defined  BOOLEAN       DEFAULT FALSE,
    currency                      VARCHAR(255),
    customer_payment_terms        VARCHAR(255),
    delivery_priority             VARCHAR(255),
    incoterms_classification      VARCHAR(255),
    incoterms_location1           VARCHAR(255),
    -- sales_group, sales_office, supplying_plant, sales_district dropped (100% null)
    shipping_condition            VARCHAR(255),
    sls_unlmtd_ovrdeliv_is_allwd  BOOLEAN       DEFAULT FALSE,
    exchange_rate_type            VARCHAR(255),
    PRIMARY KEY (customer, sales_organization, distribution_channel, division)
);

CREATE TABLE IF NOT EXISTS journal_entry_items_accounts_receivable (
    company_code                   VARCHAR(255)    NOT NULL,
    fiscal_year                    VARCHAR(255)    NOT NULL,
    accounting_document            VARCHAR(255)   NOT NULL,
    accounting_document_item       VARCHAR(255)    NOT NULL,
    gl_account                     VARCHAR(255),
    reference_document             VARCHAR(255),
    -- cost_center dropped (100% null)
    profit_center                  VARCHAR(255),
    transaction_currency           VARCHAR(255),
    amount_in_transaction_currency NUMERIC(18, 4),
    company_code_currency          VARCHAR(255),
    amount_in_company_code_currency NUMERIC(18, 4),
    posting_date                   DATE,
    document_date                  DATE,
    accounting_document_type       VARCHAR(255),
    -- assignment_reference dropped (100% null)
    last_change_datetime           TIMESTAMPTZ,
    customer                       VARCHAR(255),
    financial_account_type         VARCHAR(255),
    clearing_date                  DATE,
    clearing_accounting_document   VARCHAR(255),
    clearing_doc_fiscal_year       VARCHAR(255),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);

CREATE TABLE IF NOT EXISTS outbound_delivery_headers (
    delivery_document               VARCHAR(255)   NOT NULL PRIMARY KEY,
    actual_goods_movement_date      DATE,
    actual_goods_movement_time      TIME,
    creation_date                   DATE,
    creation_time                   TIME,
    -- delivery_block_reason, header_billing_block_reason dropped (100% null)
    hdr_general_incompletion_status VARCHAR(255),
    last_change_date                DATE,
    overall_goods_movement_status   VARCHAR(255),
    overall_picking_status          VARCHAR(255),
    -- overall_proof_of_delivery_status dropped (100% null)
    shipping_point                  VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS outbound_delivery_items (
    delivery_document          VARCHAR(255)   NOT NULL,
    delivery_document_item     VARCHAR(255)    NOT NULL,
    actual_delivery_quantity   NUMERIC(18, 2),
    batch                      VARCHAR(255),
    delivery_quantity_unit     VARCHAR(255),
    -- item_billing_block_reason, last_change_date dropped (100% null)
    plant                      VARCHAR(255),
    reference_sd_document      VARCHAR(255),
    reference_sd_document_item VARCHAR(255),
    storage_location           VARCHAR(255),
    PRIMARY KEY (delivery_document, delivery_document_item)
);

CREATE TABLE IF NOT EXISTS payments_accounts_receivable (
    company_code                    VARCHAR(255)    NOT NULL,
    fiscal_year                     VARCHAR(255)    NOT NULL,
    accounting_document             VARCHAR(255)   NOT NULL,
    accounting_document_item        VARCHAR(255)    NOT NULL,
    clearing_date                   DATE,
    clearing_accounting_document    VARCHAR(255),
    clearing_doc_fiscal_year        VARCHAR(255),
    amount_in_transaction_currency  NUMERIC(18, 4),
    transaction_currency            VARCHAR(255),
    amount_in_company_code_currency NUMERIC(18, 4),
    company_code_currency           VARCHAR(255),
    customer                        VARCHAR(255),
    -- invoice_reference, invoice_reference_fiscal_year, sales_document, sales_document_item dropped (100% null)
    posting_date                    DATE,
    document_date                   DATE,
    -- assignment_reference, cost_center dropped (100% null)
    gl_account                      VARCHAR(255),
    financial_account_type          VARCHAR(255),
    profit_center                   VARCHAR(255),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);

CREATE TABLE IF NOT EXISTS plants (
    plant                             VARCHAR(255)    NOT NULL PRIMARY KEY,
    plant_name                        VARCHAR(255),
    valuation_area                    VARCHAR(255),
    plant_customer                    VARCHAR(255),
    plant_supplier                    VARCHAR(255),
    factory_calendar                  VARCHAR(255),
    -- default_purchasing_organization dropped (100% null)
    sales_organization                VARCHAR(255),
    address_id                        VARCHAR(255),
    -- plant_category dropped (100% null)
    distribution_channel              VARCHAR(255),
    division                          VARCHAR(255),
    language                          VARCHAR(255),
    is_marked_for_archiving           BOOLEAN       DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS product_descriptions (
    product             VARCHAR(255)   NOT NULL,
    language            VARCHAR(255)    NOT NULL,
    product_description VARCHAR(255),
    PRIMARY KEY (product, language)
);

CREATE TABLE IF NOT EXISTS product_plants (
    product                      VARCHAR(255)   NOT NULL,
    plant                        VARCHAR(255)    NOT NULL,
    -- country_of_origin, region_of_origin, production_invtry_managed_loc, fiscal_year_variant dropped (100% null)
    availability_check_type      VARCHAR(255),
    profit_center                VARCHAR(255),
    mrp_type                     VARCHAR(255),
    PRIMARY KEY (product, plant)
);

CREATE TABLE IF NOT EXISTS product_storage_locations (
    product                               VARCHAR(255)   NOT NULL,
    plant                                 VARCHAR(255)    NOT NULL,
    storage_location                      VARCHAR(255)    NOT NULL,
    -- physical_inventory_block_ind, date_of_last_posted_cnt_un_rstrcd_stk dropped (100% null)
    PRIMARY KEY (product, plant, storage_location)
);

CREATE TABLE IF NOT EXISTS products (
    product                          VARCHAR(255)   NOT NULL PRIMARY KEY,
    product_type                     VARCHAR(255),
    -- cross_plant_status, cross_plant_status_validity_date dropped (100% null)
    creation_date                    DATE,
    created_by_user                  VARCHAR(255),
    last_change_date                 DATE,
    last_change_datetime             TIMESTAMPTZ,
    is_marked_for_deletion           BOOLEAN       DEFAULT FALSE,
    product_old_id                   VARCHAR(255),
    gross_weight                     NUMERIC(18, 2),
    weight_unit                      VARCHAR(255),
    net_weight                       NUMERIC(18, 2),
    product_group                    VARCHAR(255),
    base_unit                        VARCHAR(255),
    division                         VARCHAR(255),
    industry_sector                  VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS sales_order_headers (
    sales_order                     VARCHAR(255)   NOT NULL PRIMARY KEY,
    sales_order_type                VARCHAR(255),
    sales_organization              VARCHAR(255),
    distribution_channel            VARCHAR(255),
    organization_division           VARCHAR(255),
    -- sales_group, sales_office dropped (100% null)
    sold_to_party                   VARCHAR(255),
    creation_date                   DATE,
    created_by_user                 VARCHAR(255),
    last_change_datetime            TIMESTAMPTZ,
    total_net_amount                NUMERIC(18, 4),
    overall_delivery_status         VARCHAR(255),
    -- overall_ord_reltd_billg_status, overall_sd_doc_reference_status dropped (100% null)
    transaction_currency            VARCHAR(255),
    pricing_date                    DATE,
    requested_delivery_date         DATE,
    -- header_billing_block_reason, delivery_block_reason dropped (100% null)
    incoterms_classification        VARCHAR(255),
    incoterms_location1             VARCHAR(255),
    customer_payment_terms          VARCHAR(255)
    -- total_credit_check_status dropped (100% null)
);

CREATE TABLE IF NOT EXISTS sales_order_items (
    sales_order                VARCHAR(255)   NOT NULL,
    sales_order_item           VARCHAR(255)    NOT NULL,
    sales_order_item_category  VARCHAR(255),
    material                   VARCHAR(255),
    requested_quantity         NUMERIC(18, 2),
    requested_quantity_unit    VARCHAR(255),
    transaction_currency       VARCHAR(255),
    net_amount                 NUMERIC(18, 4),
    material_group             VARCHAR(255),
    production_plant           VARCHAR(255),
    storage_location           VARCHAR(255),
    sales_document_rjcn_reason VARCHAR(255),
    -- item_billing_block_reason dropped (100% null)
    PRIMARY KEY (sales_order, sales_order_item)
);

CREATE TABLE IF NOT EXISTS sales_order_schedule_lines (
    sales_order                           VARCHAR(255)   NOT NULL,
    sales_order_item                      VARCHAR(255)    NOT NULL,
    schedule_line                         VARCHAR(255)    NOT NULL,
    confirmed_delivery_date               DATE,
    order_quantity_unit                   VARCHAR(255),
    confd_order_qty_by_matl_avail_check   NUMERIC(18, 2),
    PRIMARY KEY (sales_order, sales_order_item, schedule_line)
);
