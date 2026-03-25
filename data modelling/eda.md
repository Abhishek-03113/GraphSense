# EDA Report — SAP O2C Dataset

## Validation

- **19 tables** defined in `ddl.sql`, all 19 have corresponding JSONL data in `data/sap-o2c-data/`
- DDL uses relaxed `VARCHAR(255)` and `NUMERIC(18,4)` — suitable for PostgreSQL
- Schema migrations applied: baseline consolidated migration `V20260325000001__baseline_consolidated.sql`
- All data transformations handled by ingestion pipeline in `src/ingestion/schemas.py`:
  - Nested JSON time objects (`{hours, minutes, seconds}`) → `TIME` via `SAPTime.to_time()`
  - ISO 8601 date strings → `DATE`; datetime strings → `TIMESTAMPTZ`
  - Boolean strings (`"True"`/`"False"`) → proper booleans
  - Empty strings (`""`) → `NULL`

---

## Table Summaries

### Table: billing_document_headers

| Metric | Value |
|--------|-------|
| Row count | 163 |
| Columns | 14 |
| PK | `billing_document` |

**Relationships:**
- `billing_document` → `billing_document_items.billing_document` (1:N, 100% match)
- `sold_to_party` → `business_partners.customer` (100% → 50%, implicit FK)
- `accounting_document` → `journal_entry_items_accounts_receivable.accounting_document` (75% → 100%)
- `cancelled_billing_document` → `billing_document_cancellations.billing_document` (100% → 100%)

**Role:** Central hub linking invoices to customers, accounting entries, and cancellations

---

### Table: billing_document_cancellations

| Metric | Value |
|--------|-------|
| Row count | 80 |
| Columns | 13 |
| PK | `billing_document` |

**Relationships:**
- Referenced by `billing_document_headers.cancelled_billing_document` (100% match)
- `accounting_document` overlaps with `journal_entry_items_AR` (80%) and `payments_AR` (80%)
- `sold_to_party` → `business_partners.customer` (100% → 50%)

**Role:** Target of cancellation lookup from billing headers

---

### Table: billing_document_items

| Metric | Value |
|--------|-------|
| Row count | 245 |
| Columns | 9 |
| PK | `(billing_document, billing_document_item)` |

**Relationships:**
- `billing_document` → `billing_document_headers.billing_document` (100% → 100%)
- `reference_sd_document` → `outbound_delivery_headers.delivery_document` (100% → 97%)
- `material` → `products.product` (100% → 80%)

**Role:** Links billing to delivery documents and products

---

### Table: business_partners

| Metric | Value |
|--------|-------|
| Row count | 8 |
| Columns | 14 |
| PK | `business_partner` |
| Alternate key | `customer` (unique, used as FK target) |

**Relationships:**
- Referenced by `sales_order_headers.sold_to_party` (100% match)
- Referenced by `billing_document_headers.sold_to_party` (100%)
- Referenced by `customer_company_assignments.customer` (100%)
- Referenced by `customer_sales_area_assignments.customer` (100%)
- Referenced by `journal_entry_items_AR.customer` (25%)
- Referenced by `payments_AR.customer` (25%)

**Role:** Master customer table — central to all O2C lookups. **Requires `UNIQUE INDEX` on `customer` column** for FK targets.

---

### Table: business_partner_addresses

| Metric | Value |
|--------|-------|
| Row count | 8 |
| Columns | 12 |
| PK | `(business_partner, address_id)` |

**Relationships:**
- `business_partner` → `business_partners.business_partner` (100% → 100%)

**Role:** 1:1 with business partners in this dataset (8 each)

---

### Table: customer_company_assignments

| Metric | Value |
|--------|-------|
| Row count | 8 |
| Columns | 6 |
| PK | `(customer, company_code)` |

**Relationships:**
- `customer` → `business_partners.customer` (100% → 100%)

**Role:** Customer financial setup per company code

---

### Table: customer_sales_area_assignments

| Metric | Value |
|--------|-------|
| Row count | 28 |
| Columns | 13 |
| PK | `(customer, sales_organization, distribution_channel, division)` |

**Relationships:**
- `customer` → `business_partners.customer` (100% → 100%)

**Role:** Customer sales configuration per sales area

---

### Table: sales_order_headers

| Metric | Value |
|--------|-------|
| Row count | 100 |
| Columns | 17 |
| PK | `sales_order` |

**Relationships:**
- `sold_to_party` → `business_partners.customer` (100% → 100%, implicit FK)
- Referenced by `sales_order_items.sales_order` (100%)
- Referenced by `sales_order_schedule_lines.sales_order` (100%)
- Referenced by `outbound_delivery_items.reference_sd_document` (100% → 86%)

**Role:** Entry point for the O2C flow; links to customer, items, deliveries

---

### Table: sales_order_items

| Metric | Value |
|--------|-------|
| Row count | 167 |
| Columns | 12 |
| PK | `(sales_order, sales_order_item)` |

**Relationships:**
- `sales_order` → `sales_order_headers.sales_order` (100% → 100%)
- `material` → `products.product` (100% → 100%, implicit FK)
- `production_plant` → `plants.plant` (100% → 16%)

**Role:** Links orders to products and plants

---

### Table: sales_order_schedule_lines

| Metric | Value |
|--------|-------|
| Row count | 179 |
| Columns | 6 |
| PK | `(sales_order, sales_order_item, schedule_line)` |

**Relationships:**
- `(sales_order, sales_order_item)` → `sales_order_items.(sales_order, sales_order_item)` (100%)

**Role:** Delivery schedule detail for order items

---

### Table: outbound_delivery_headers

| Metric | Value |
|--------|-------|
| Row count | 86 |
| Columns | 10 |
| PK | `delivery_document` |

**Relationships:**
- Referenced by `outbound_delivery_items.delivery_document` (100% → 100%)
- Referenced by `billing_document_items.reference_sd_document` (100% → 97%)

**Role:** Links delivery items to billing; bridges sales orders to invoices

---

### Table: outbound_delivery_items

| Metric | Value |
|--------|-------|
| Row count | 137 |
| Columns | 9 |
| PK | `(delivery_document, delivery_document_item)` |

**Relationships:**
- `delivery_document` → `outbound_delivery_headers.delivery_document` (100% → 100%)
- `reference_sd_document` → `sales_order_headers.sales_order` (100% → 86%, implicit FK)
- `plant` → `plants.plant` (100% → 11%)

**Role:** Links deliveries back to sales orders and forward to billing

---

### Table: journal_entry_items_accounts_receivable

| Metric | Value |
|--------|-------|
| Row count | 123 |
| Columns | 20 |
| PK | `(company_code, fiscal_year, accounting_document, accounting_document_item)` |

**Relationships:**
- `accounting_document` overlaps with `billing_document_headers.accounting_document` (100% ← 75%)
- `accounting_document` overlaps with `payments_AR.accounting_document` (98% → 100%)
- `customer` → `business_partners.customer` (100% → 25%)

**Role:** Bridges billing to payments via `accounting_document`

---

### Table: payments_accounts_receivable

| Metric | Value |
|--------|-------|
| Row count | 120 |
| Columns | 17 |
| PK | `(company_code, fiscal_year, accounting_document, accounting_document_item)` |

**Relationships:**
- `accounting_document` overlaps with `journal_entry_items_AR.accounting_document` (100% ← 98%)
- `customer` → `business_partners.customer` (100% → 25%)
- `clearing_accounting_document` overlaps with journal entries (100%)

**Role:** Terminal node in O2C flow; linked via `accounting_document` bridge

**Note:** `invoice_reference` is 100% NULL. Direct billing→payment link broken. Workaround: use `accounting_document` bridge through journal entries (98-100% overlap).

---

### Table: plants

| Metric | Value |
|--------|-------|
| Row count | 44 |
| Columns | 12 |
| PK | `plant` |

**Relationships:**
- Referenced by `product_plants.plant` (100%)
- Referenced by `product_storage_locations.plant` (100%)
- Referenced by `sales_order_items.production_plant` (100% → 16%)
- Referenced by `outbound_delivery_items.plant` (100% → 11%)

**Role:** Master plant data; connects products and deliveries to physical locations

---

### Table: products

| Metric | Value |
|--------|-------|
| Row count | 69 |
| Columns | 15 |
| PK | `product` |

**Relationships:**
- Referenced by `product_descriptions.product` (100%)
- Referenced by `product_plants.product` (100%)
- Referenced by `product_storage_locations.product` (100%)
- Referenced by `sales_order_items.material` (100%, implicit FK — different column name)
- Referenced by `billing_document_items.material` (80%, implicit FK)

**Role:** Master product table; central to product hierarchy and transactional items

---

### Table: product_descriptions

| Metric | Value |
|--------|-------|
| Row count | 69 |
| Columns | 3 |
| PK | `(product, language)` |

**Relationships:**
- `product` → `products.product` (100% → 100%)

**Role:** Product display names

---

### Table: product_plants

| Metric | Value |
|--------|-------|
| Row count | 3,036 |
| Columns | 5 |
| PK | `(product, plant)` |

**Relationships:**
- `product` → `products.product` (100% → 100%)
- `plant` → `plants.plant` (100% → 100%)

**Role:** Product availability per plant; bridges product and plant master data

---

### Table: product_storage_locations

| Metric | Value |
|--------|-------|
| Row count | 16,723 |
| Columns | 3 |
| PK | `(product, plant, storage_location)` |

**Relationships:**
- `product` → `products.product` (100% → 100%)
- `plant` → `plants.plant` (100% → 100%)

**Role:** Storage-level granularity for product inventory

---

## Schema Improvements

### Table Names
SAP table names are kept as-is. The team is already familiar with them, and renaming would add confusion without value.

### Column Cleanup Summary

All 57 empty/null columns have been removed in the consolidated baseline migration `V20260325000001__baseline_consolidated.sql`.

| Table | Columns Dropped | Reason |
|-------|----------------|--------|
| billing_document_cancellations | 1 | 100% empty |
| business_partners | 4 | 100% empty (org-only data) |
| business_partner_addresses | 8 | 100% empty PO box / tax fields |
| customer_company_assignments | 7 | 100% empty clerk / payment fields |
| customer_sales_area_assignments | 6 | 100% empty area config fields |
| journal_entry_items_AR | 2 | 100% empty |
| outbound_delivery_headers | 3 | 100% empty block / status fields |
| outbound_delivery_items | 2 | 100% empty / null |
| payments_AR | 6 | 100% null (includes broken invoice_reference) |
| plants | 2 | 100% empty |
| product_plants | 4 | 100% empty origin / variant fields |
| product_storage_locations | 2 | 100% empty / null |
| products | 2 | 100% empty status fields |
| sales_order_headers | 7 | 100% empty block / status fields |
| sales_order_items | 1 | 100% empty |
| **Total** | **57** | |

### Required Index

```sql
CREATE UNIQUE INDEX uq_bp_customer ON business_partners(customer);
```

This enables `customer` to serve as an FK target (it is not the PK but is referenced by 6+ tables).

---

## Final Relationships / Data Flow

### Explicit FK Constraints

#### Transactional O2C Chain
```
sales_order_headers.sold_to_party        → business_partners.customer
sales_order_items.sales_order            → sales_order_headers.sales_order
sales_order_schedule_lines.(SO, SOI)     → sales_order_items.(sales_order, sales_order_item)
outbound_delivery_items.ref_sd_document  → sales_order_headers.sales_order
outbound_delivery_items.delivery_doc     → outbound_delivery_headers.delivery_document
billing_document_items.ref_sd_document   → outbound_delivery_headers.delivery_document
billing_document_items.billing_document  → billing_document_headers.billing_document
billing_document_headers.sold_to_party   → business_partners.customer
billing_document_headers.cancelled_bd    → billing_document_cancellations.billing_document
```

#### Financial Chain (logical — composite PK prevents simple FK)
```
billing_document_headers.accounting_document  ≈ journal_entries_AR.accounting_document
journal_entries_AR.accounting_document        ≈ payments_AR.accounting_document
```

#### Master Data
```
business_partner_addresses.business_partner  → business_partners.business_partner
customer_company_assignments.customer        → business_partners.customer
customer_sales_area_assignments.customer     → business_partners.customer
journal_entries_AR.customer                  → business_partners.customer
payments_AR.customer                         → business_partners.customer
product_descriptions.product                 → products.product
product_plants.product                       → products.product
product_plants.plant                         → plants.plant
product_storage_locations.product            → products.product
product_storage_locations.plant              → plants.plant
sales_order_items.material                   → products.product
sales_order_items.production_plant           → plants.plant
billing_document_items.material              → products.product
outbound_delivery_items.plant                → plants.plant
```

### End-to-End Data Flow Paths

#### Path 1: Full O2C (9 hops)
```
Customer → Sales Order → SO Items → Delivery Items → Delivery Header → Billing Items → Billing Header → Journal Entry → Payment
```

| Hop | Join |
|-----|------|
| 1 | `business_partners.customer = sales_order_headers.sold_to_party` |
| 2 | `sales_order_headers.sales_order = sales_order_items.sales_order` |
| 3 | `sales_order_headers.sales_order = outbound_delivery_items.reference_sd_document` |
| 4 | `outbound_delivery_items.delivery_document = outbound_delivery_headers.delivery_document` |
| 5 | `outbound_delivery_headers.delivery_document = billing_document_items.reference_sd_document` |
| 6 | `billing_document_items.billing_document = billing_document_headers.billing_document` |
| 7 | `billing_document_headers.accounting_document = journal_entries_AR.accounting_document` |
| 8 | `journal_entries_AR.accounting_document = payments_AR.accounting_document` |

#### Path 2: Product Master (3 branches)
```
Products → Product Descriptions
Products → Product Plants → Plants
Products → Product Storage Locations
```

#### Path 3: Customer Master (2 branches)
```
Business Partners → BP Addresses
Business Partners → Customer Company Assignments
Business Partners → Customer Sales Area Assignments
```

#### Path 4: Cancellation Check (1 hop)
```
Billing Doc Headers → Billing Doc Cancellations
  via: cancelled_billing_document = billing_document
```
