CREATE SCHEMA IF NOT EXISTS "ds_o2c";

CREATE TABLE "ds_o2c"."billing_document_cancellations" (
    "billing_document" text NOT NULL,
    "billing_document_type" text,
    "creation_date" date,
    "creation_time" time,
    "last_change_datetime" timestamptz,
    "billing_document_date" date,
    "billing_document_is_cancelled" boolean,
    "total_net_amount" numeric(18,4),
    "transaction_currency" text,
    "company_code" text,
    "fiscal_year" text,
    "accounting_document" text,
    "sold_to_party" text,
    CONSTRAINT "pk_billing_document_cancellations" PRIMARY KEY ("billing_document")
);

CREATE TABLE "ds_o2c"."billing_document_headers" (
    "billing_document" text NOT NULL,
    "billing_document_type" text,
    "creation_date" date,
    "creation_time" time,
    "last_change_datetime" timestamptz,
    "billing_document_date" date,
    "billing_document_is_cancelled" boolean,
    "cancelled_billing_document" text,
    "total_net_amount" numeric(18,4),
    "transaction_currency" text,
    "company_code" text,
    "fiscal_year" text,
    "accounting_document" text,
    "sold_to_party" text,
    CONSTRAINT "pk_billing_document_headers" PRIMARY KEY ("billing_document")
);

CREATE TABLE "ds_o2c"."billing_document_items" (
    "billing_document" text NOT NULL,
    "billing_document_item" text NOT NULL,
    "material" text,
    "billing_quantity" numeric(18,2),
    "billing_quantity_unit" text,
    "net_amount" numeric(18,4),
    "transaction_currency" text,
    "reference_sd_document" text,
    "reference_sd_document_item" text,
    CONSTRAINT "pk_billing_document_items" PRIMARY KEY ("billing_document", "billing_document_item")
);

CREATE TABLE "ds_o2c"."business_partner_addresses" (
    "business_partner" text NOT NULL,
    "address_id" text NOT NULL,
    "validity_start_date" date,
    "validity_end_date" date,
    "address_uuid" text,
    "address_time_zone" text,
    "city_name" text,
    "country" text,
    "po_box_is_without_number" boolean,
    "postal_code" text,
    "region" text,
    "street_name" text,
    CONSTRAINT "pk_business_partner_addresses" PRIMARY KEY ("business_partner", "address_id")
);

CREATE TABLE "ds_o2c"."business_partners" (
    "business_partner" text NOT NULL,
    "customer" text,
    "business_partner_category" text,
    "business_partner_full_name" text,
    "business_partner_grouping" text,
    "business_partner_name" text,
    "created_by_user" text,
    "creation_date" date,
    "creation_time" time,
    "form_of_address" text,
    "last_change_date" date,
    "organization_bp_name1" text,
    "organization_bp_name2" text,
    "business_partner_is_blocked" boolean,
    "is_marked_for_archiving" boolean,
    CONSTRAINT "pk_business_partners" PRIMARY KEY ("business_partner")
);

CREATE TABLE "ds_o2c"."customer_company_assignments" (
    "customer" text NOT NULL,
    "company_code" text NOT NULL,
    "payment_terms" text,
    "reconciliation_account" text,
    "deletion_indicator" boolean,
    "customer_account_group" text,
    CONSTRAINT "pk_customer_company_assignments" PRIMARY KEY ("customer", "company_code")
);

CREATE TABLE "ds_o2c"."customer_sales_area_assignments" (
    "customer" text NOT NULL,
    "sales_organization" text NOT NULL,
    "distribution_channel" text NOT NULL,
    "division" text NOT NULL,
    "complete_delivery_is_defined" boolean,
    "currency" text,
    "customer_payment_terms" text,
    "delivery_priority" text,
    "incoterms_classification" text,
    "incoterms_location1" text,
    "shipping_condition" text,
    "sls_unlmtd_ovrdeliv_is_allwd" boolean,
    "exchange_rate_type" text,
    CONSTRAINT "pk_customer_sales_area_assignments" PRIMARY KEY ("customer", "sales_organization", "distribution_channel", "division")
);

CREATE TABLE "ds_o2c"."journal_entry_items_accounts_receivable" (
    "company_code" text NOT NULL,
    "fiscal_year" text NOT NULL,
    "accounting_document" text NOT NULL,
    "accounting_document_item" text NOT NULL,
    "gl_account" text,
    "reference_document" text,
    "profit_center" text,
    "transaction_currency" text,
    "amount_in_transaction_currency" numeric(18,4),
    "company_code_currency" text,
    "amount_in_company_code_currency" numeric(18,4),
    "posting_date" date,
    "document_date" date,
    "accounting_document_type" text,
    "last_change_datetime" timestamptz,
    "customer" text,
    "financial_account_type" text,
    "clearing_date" date,
    "clearing_accounting_document" text,
    "clearing_doc_fiscal_year" text,
    CONSTRAINT "pk_journal_entry_items_accounts_receivable" PRIMARY KEY ("company_code", "fiscal_year", "accounting_document", "accounting_document_item")
);

CREATE TABLE "ds_o2c"."outbound_delivery_headers" (
    "delivery_document" text NOT NULL,
    "actual_goods_movement_date" date,
    "actual_goods_movement_time" time,
    "creation_date" date,
    "creation_time" time,
    "hdr_general_incompletion_status" text,
    "last_change_date" date,
    "overall_goods_movement_status" text,
    "overall_picking_status" text,
    "shipping_point" text,
    CONSTRAINT "pk_outbound_delivery_headers" PRIMARY KEY ("delivery_document")
);

CREATE TABLE "ds_o2c"."outbound_delivery_items" (
    "delivery_document" text NOT NULL,
    "delivery_document_item" text NOT NULL,
    "actual_delivery_quantity" numeric(18,2),
    "batch" text,
    "delivery_quantity_unit" text,
    "plant" text,
    "reference_sd_document" text,
    "reference_sd_document_item" text,
    "storage_location" text,
    CONSTRAINT "pk_outbound_delivery_items" PRIMARY KEY ("delivery_document", "delivery_document_item")
);

CREATE TABLE "ds_o2c"."payments_accounts_receivable" (
    "company_code" text NOT NULL,
    "fiscal_year" text NOT NULL,
    "accounting_document" text NOT NULL,
    "accounting_document_item" text NOT NULL,
    "clearing_date" date,
    "clearing_accounting_document" text,
    "clearing_doc_fiscal_year" text,
    "amount_in_transaction_currency" numeric(18,4),
    "transaction_currency" text,
    "amount_in_company_code_currency" numeric(18,4),
    "company_code_currency" text,
    "customer" text,
    "posting_date" date,
    "document_date" date,
    "gl_account" text,
    "financial_account_type" text,
    "profit_center" text,
    CONSTRAINT "pk_payments_accounts_receivable" PRIMARY KEY ("company_code", "fiscal_year", "accounting_document", "accounting_document_item")
);

CREATE TABLE "ds_o2c"."plants" (
    "plant" text NOT NULL,
    "plant_name" text,
    "valuation_area" text,
    "plant_customer" text,
    "plant_supplier" text,
    "factory_calendar" text,
    "sales_organization" text,
    "address_id" text,
    "distribution_channel" text,
    "division" text,
    "language" text,
    "is_marked_for_archiving" boolean,
    CONSTRAINT "pk_plants" PRIMARY KEY ("plant")
);

CREATE TABLE "ds_o2c"."product_descriptions" (
    "product" text NOT NULL,
    "language" text NOT NULL,
    "product_description" text,
    CONSTRAINT "pk_product_descriptions" PRIMARY KEY ("product", "language")
);

CREATE TABLE "ds_o2c"."product_plants" (
    "product" text NOT NULL,
    "plant" text NOT NULL,
    "availability_check_type" text,
    "profit_center" text,
    "mrp_type" text,
    CONSTRAINT "pk_product_plants" PRIMARY KEY ("product", "plant")
);

CREATE TABLE "ds_o2c"."product_storage_locations" (
    "product" text NOT NULL,
    "plant" text NOT NULL,
    "storage_location" text NOT NULL,
    CONSTRAINT "pk_product_storage_locations" PRIMARY KEY ("product", "plant", "storage_location")
);

CREATE TABLE "ds_o2c"."products" (
    "product" text NOT NULL,
    "product_type" text,
    "creation_date" date,
    "created_by_user" text,
    "last_change_date" date,
    "last_change_datetime" timestamptz,
    "is_marked_for_deletion" boolean,
    "product_old_id" text,
    "gross_weight" numeric(18,2),
    "weight_unit" text,
    "net_weight" numeric(18,2),
    "product_group" text,
    "base_unit" text,
    "division" text,
    "industry_sector" text,
    CONSTRAINT "pk_products" PRIMARY KEY ("product")
);

CREATE TABLE "ds_o2c"."sales_order_headers" (
    "sales_order" text NOT NULL,
    "sales_order_type" text,
    "sales_organization" text,
    "distribution_channel" text,
    "organization_division" text,
    "sold_to_party" text,
    "creation_date" date,
    "created_by_user" text,
    "last_change_datetime" timestamptz,
    "total_net_amount" numeric(18,4),
    "overall_delivery_status" text,
    "transaction_currency" text,
    "pricing_date" date,
    "requested_delivery_date" date,
    "incoterms_classification" text,
    "incoterms_location1" text,
    "customer_payment_terms" text,
    CONSTRAINT "pk_sales_order_headers" PRIMARY KEY ("sales_order")
);

CREATE TABLE "ds_o2c"."sales_order_items" (
    "sales_order" text NOT NULL,
    "sales_order_item" text NOT NULL,
    "sales_order_item_category" text,
    "material" text,
    "requested_quantity" numeric(18,2),
    "requested_quantity_unit" text,
    "transaction_currency" text,
    "net_amount" numeric(18,4),
    "material_group" text,
    "production_plant" text,
    "storage_location" text,
    "sales_document_rjcn_reason" text,
    CONSTRAINT "pk_sales_order_items" PRIMARY KEY ("sales_order", "sales_order_item")
);

CREATE TABLE "ds_o2c"."sales_order_schedule_lines" (
    "sales_order" text NOT NULL,
    "sales_order_item" text NOT NULL,
    "schedule_line" text NOT NULL,
    "confirmed_delivery_date" date,
    "order_quantity_unit" text,
    "confd_order_qty_by_matl_avail_check" numeric(18,2),
    CONSTRAINT "pk_sales_order_schedule_lines" PRIMARY KEY ("sales_order", "sales_order_item", "schedule_line")
);

CREATE INDEX "ix_billing_document_cancellations__sold_to_party" ON "ds_o2c"."billing_document_cancellations" ("sold_to_party");

CREATE INDEX "ix_billing_document_cancellations__accounting_document" ON "ds_o2c"."billing_document_cancellations" ("accounting_document");

CREATE INDEX "ix_billing_document_headers__sold_to_party" ON "ds_o2c"."billing_document_headers" ("sold_to_party");

CREATE INDEX "ix_billing_document_headers__accounting_document" ON "ds_o2c"."billing_document_headers" ("accounting_document");

CREATE INDEX "ix_billing_document_items__material" ON "ds_o2c"."billing_document_items" ("material");

CREATE INDEX "ix_billing_document_items__reference_sd_document_refer_2b4d8db8" ON "ds_o2c"."billing_document_items" ("reference_sd_document", "reference_sd_document_item");

CREATE INDEX "ix_business_partners__customer" ON "ds_o2c"."business_partners" ("customer");

CREATE INDEX "ix_journal_entry_items_accounts_receivable__reference_document" ON "ds_o2c"."journal_entry_items_accounts_receivable" ("reference_document");

CREATE INDEX "ix_journal_entry_items_accounts_receivable__customer" ON "ds_o2c"."journal_entry_items_accounts_receivable" ("customer");

CREATE INDEX "ix_journal_entry_items_accounts_receivable__accounting_document" ON "ds_o2c"."journal_entry_items_accounts_receivable" ("accounting_document");

CREATE INDEX "ix_outbound_delivery_items__reference_sd_document_refe_4e5279ed" ON "ds_o2c"."outbound_delivery_items" ("reference_sd_document", "reference_sd_document_item");

CREATE INDEX "ix_payments_accounts_receivable__customer" ON "ds_o2c"."payments_accounts_receivable" ("customer");

CREATE INDEX "ix_payments_accounts_receivable__accounting_document" ON "ds_o2c"."payments_accounts_receivable" ("accounting_document");

CREATE INDEX "ix_payments_accounts_receivable__clearing_accounting_document" ON "ds_o2c"."payments_accounts_receivable" ("clearing_accounting_document");

CREATE INDEX "ix_sales_order_headers__sold_to_party" ON "ds_o2c"."sales_order_headers" ("sold_to_party");

CREATE INDEX "ix_sales_order_items__material" ON "ds_o2c"."sales_order_items" ("material");

