# SAP Order-to-Cash (O2C) — Data Schemas

> **19 tables** derived from SAP O2C process data.  
> Each section contains: the representative JSON sample, a JSON Schema, and a PostgreSQL DDL statement.

---

## Table of Contents

1. [billing_document_headers](#1-billing_document_headers)
2. [billing_document_cancellations](#2-billing_document_cancellations)
3. [billing_document_items](#3-billing_document_items)
4. [business_partner_addresses](#4-business_partner_addresses)
5. [business_partners](#5-business_partners)
6. [customer_company_assignments](#6-customer_company_assignments)
7. [customer_sales_area_assignments](#7-customer_sales_area_assignments)
8. [journal_entry_items_accounts_receivable](#8-journal_entry_items_accounts_receivable)
9. [outbound_delivery_headers](#9-outbound_delivery_headers)
10. [outbound_delivery_items](#10-outbound_delivery_items)
11. [payments_accounts_receivable](#11-payments_accounts_receivable)
12. [plants](#12-plants)
13. [product_descriptions](#13-product_descriptions)
14. [product_plants](#14-product_plants)
15. [product_storage_locations](#15-product_storage_locations)
16. [products](#16-products)
17. [sales_order_headers](#17-sales_order_headers)
18. [sales_order_items](#18-sales_order_items)
19. [sales_order_schedule_lines](#19-sales_order_schedule_lines)

---

## 1. `billing_document_headers`

### JSON Sample
```json
{
  "billingDocument": "90504274",
  "billingDocumentType": "F2",
  "creationDate": "2025-04-03T00:00:00.000Z",
  "creationTime": { "hours": 11, "minutes": 31, "seconds": 13 },
  "lastChangeDateTime": "2025-07-24T11:42:30.485Z",
  "billingDocumentDate": "2025-04-02T00:00:00.000Z",
  "billingDocumentIsCancelled": true,
  "cancelledBillingDocument": "",
  "totalNetAmount": "253.39",
  "transactionCurrency": "INR",
  "companyCode": "ABCD",
  "fiscalYear": "2025",
  "accountingDocument": "9400000275",
  "soldToParty": "320000083"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "billing_document_headers",
  "type": "object",
  "required": ["billingDocument"],
  "properties": {
    "billingDocument":          { "type": "string", "maxLength": 10 },
    "billingDocumentType":      { "type": "string", "maxLength": 4 },
    "creationDate":             { "type": "string", "format": "date-time" },
    "creationTime":             {
      "type": "object",
      "properties": {
        "hours":   { "type": "integer" },
        "minutes": { "type": "integer" },
        "seconds": { "type": "integer" }
      }
    },
    "lastChangeDateTime":       { "type": "string", "format": "date-time" },
    "billingDocumentDate":      { "type": "string", "format": "date-time" },
    "billingDocumentIsCancelled": { "type": "boolean" },
    "cancelledBillingDocument": { "type": "string", "maxLength": 10 },
    "totalNetAmount":           { "type": "string" },
    "transactionCurrency":      { "type": "string", "maxLength": 5 },
    "companyCode":              { "type": "string", "maxLength": 4 },
    "fiscalYear":               { "type": "string", "maxLength": 4 },
    "accountingDocument":       { "type": "string", "maxLength": 10 },
    "soldToParty":              { "type": "string", "maxLength": 10 }
  }
}
```

### DDL
```sql
CREATE TABLE billing_document_headers (
    billing_document           VARCHAR(10)    NOT NULL PRIMARY KEY,
    billing_document_type      VARCHAR(4),
    creation_date              DATE,
    creation_time              TIME,
    last_change_datetime       TIMESTAMPTZ,
    billing_document_date      DATE,
    billing_document_is_cancelled BOOLEAN     DEFAULT FALSE,
    cancelled_billing_document VARCHAR(10),
    total_net_amount           NUMERIC(15, 2),
    transaction_currency       VARCHAR(5),
    company_code               VARCHAR(4),
    fiscal_year                VARCHAR(4),
    accounting_document        VARCHAR(10),
    sold_to_party              VARCHAR(10)
);
```

---

## 2. `billing_document_cancellations`

> **Note:** The source folder `billing_document_cancellations/` maps to the second billing document JSON record (same schema as `billing_document_headers` but specifically for cancelled documents). The distinguishing flag is `billingDocumentIsCancelled = true`.

### JSON Sample
```json
{
  "billingDocument": "90504248",
  "billingDocumentType": "F2",
  "creationDate": "2025-04-03T00:00:00.000Z",
  "creationTime": { "hours": 11, "minutes": 31, "seconds": 13 },
  "lastChangeDateTime": "2025-04-03T11:31:37.331Z",
  "billingDocumentDate": "2025-04-02T00:00:00.000Z",
  "billingDocumentIsCancelled": false,
  "cancelledBillingDocument": "",
  "totalNetAmount": "216.1",
  "transactionCurrency": "INR",
  "companyCode": "ABCD",
  "fiscalYear": "2025",
  "accountingDocument": "9400000249",
  "soldToParty": "320000083"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "billing_document_cancellations",
  "type": "object",
  "required": ["billingDocument"],
  "properties": {
    "billingDocument":            { "type": "string", "maxLength": 10 },
    "billingDocumentType":        { "type": "string", "maxLength": 4 },
    "creationDate":               { "type": "string", "format": "date-time" },
    "creationTime":               {
      "type": "object",
      "properties": {
        "hours":   { "type": "integer" },
        "minutes": { "type": "integer" },
        "seconds": { "type": "integer" }
      }
    },
    "lastChangeDateTime":         { "type": "string", "format": "date-time" },
    "billingDocumentDate":        { "type": "string", "format": "date-time" },
    "billingDocumentIsCancelled": { "type": "boolean" },
    "cancelledBillingDocument":   { "type": "string", "maxLength": 10 },
    "totalNetAmount":             { "type": "string" },
    "transactionCurrency":        { "type": "string", "maxLength": 5 },
    "companyCode":                { "type": "string", "maxLength": 4 },
    "fiscalYear":                 { "type": "string", "maxLength": 4 },
    "accountingDocument":         { "type": "string", "maxLength": 10 },
    "soldToParty":                { "type": "string", "maxLength": 10 }
  }
}
```

### DDL
```sql
CREATE TABLE billing_document_cancellations (
    billing_document              VARCHAR(10)    NOT NULL PRIMARY KEY,
    billing_document_type         VARCHAR(4),
    creation_date                 DATE,
    creation_time                 TIME,
    last_change_datetime          TIMESTAMPTZ,
    billing_document_date         DATE,
    billing_document_is_cancelled BOOLEAN        DEFAULT FALSE,
    cancelled_billing_document    VARCHAR(10),
    total_net_amount              NUMERIC(15, 2),
    transaction_currency          VARCHAR(5),
    company_code                  VARCHAR(4),
    fiscal_year                   VARCHAR(4),
    accounting_document           VARCHAR(10),
    sold_to_party                 VARCHAR(10)
);
```

---

## 3. `billing_document_items`

### JSON Sample
```json
{
  "billingDocument": "90504298",
  "billingDocumentItem": "10",
  "material": "B8907367041603",
  "billingQuantity": "1",
  "billingQuantityUnit": "PC",
  "netAmount": "533.05",
  "transactionCurrency": "INR",
  "referenceSdDocument": "80738109",
  "referenceSdDocumentItem": "10"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "billing_document_items",
  "type": "object",
  "required": ["billingDocument", "billingDocumentItem"],
  "properties": {
    "billingDocument":        { "type": "string", "maxLength": 10 },
    "billingDocumentItem":    { "type": "string", "maxLength": 6 },
    "material":               { "type": "string", "maxLength": 40 },
    "billingQuantity":        { "type": "string" },
    "billingQuantityUnit":    { "type": "string", "maxLength": 3 },
    "netAmount":              { "type": "string" },
    "transactionCurrency":    { "type": "string", "maxLength": 5 },
    "referenceSdDocument":    { "type": "string", "maxLength": 10 },
    "referenceSdDocumentItem":{ "type": "string", "maxLength": 6 }
  }
}
```

### DDL
```sql
CREATE TABLE billing_document_items (
    billing_document          VARCHAR(10)   NOT NULL,
    billing_document_item     VARCHAR(6)    NOT NULL,
    material                  VARCHAR(40),
    billing_quantity          NUMERIC(15, 3),
    billing_quantity_unit     VARCHAR(3),
    net_amount                NUMERIC(15, 2),
    transaction_currency      VARCHAR(5),
    reference_sd_document     VARCHAR(10),
    reference_sd_document_item VARCHAR(6),
    PRIMARY KEY (billing_document, billing_document_item)
);
```

---

## 4. `business_partner_addresses`

### JSON Sample
```json
{
  "businessPartner": "310000108",
  "addressId": "4605",
  "validityStartDate": "2024-04-16T00:00:00.000Z",
  "validityEndDate": "9999-12-31T23:59:59.000Z",
  "addressUuid": "af79c9a3-05bf-1ede-bef9-0812e7757c0e",
  "addressTimeZone": "INDIA",
  "cityName": "Lake Christopher",
  "country": "IN",
  "poBox": "",
  "poBoxDeviatingCityName": "",
  "poBoxDeviatingCountry": "",
  "poBoxDeviatingRegion": "",
  "poBoxIsWithoutNumber": false,
  "poBoxLobbyName": "",
  "poBoxPostalCode": "",
  "postalCode": "18589",
  "region": "TS",
  "streetName": "0171 Rebecca Glen",
  "taxJurisdiction": "",
  "transportZone": ""
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "business_partner_addresses",
  "type": "object",
  "required": ["businessPartner", "addressId"],
  "properties": {
    "businessPartner":          { "type": "string", "maxLength": 10 },
    "addressId":                { "type": "string", "maxLength": 10 },
    "validityStartDate":        { "type": "string", "format": "date-time" },
    "validityEndDate":          { "type": "string", "format": "date-time" },
    "addressUuid":              { "type": "string", "format": "uuid" },
    "addressTimeZone":          { "type": "string", "maxLength": 10 },
    "cityName":                 { "type": "string", "maxLength": 40 },
    "country":                  { "type": "string", "maxLength": 3 },
    "poBox":                    { "type": "string", "maxLength": 10 },
    "poBoxDeviatingCityName":   { "type": "string", "maxLength": 40 },
    "poBoxDeviatingCountry":    { "type": "string", "maxLength": 3 },
    "poBoxDeviatingRegion":     { "type": "string", "maxLength": 3 },
    "poBoxIsWithoutNumber":     { "type": "boolean" },
    "poBoxLobbyName":           { "type": "string", "maxLength": 40 },
    "poBoxPostalCode":          { "type": "string", "maxLength": 10 },
    "postalCode":               { "type": "string", "maxLength": 10 },
    "region":                   { "type": "string", "maxLength": 3 },
    "streetName":               { "type": "string", "maxLength": 60 },
    "taxJurisdiction":          { "type": "string", "maxLength": 15 },
    "transportZone":            { "type": "string", "maxLength": 10 }
  }
}
```

### DDL
```sql
CREATE TABLE business_partner_addresses (
    business_partner           VARCHAR(10)   NOT NULL,
    address_id                 VARCHAR(10)   NOT NULL,
    validity_start_date        DATE,
    validity_end_date          DATE,
    address_uuid               UUID,
    address_time_zone          VARCHAR(10),
    city_name                  VARCHAR(40),
    country                    VARCHAR(3),
    po_box                     VARCHAR(10),
    po_box_deviating_city_name VARCHAR(40),
    po_box_deviating_country   VARCHAR(3),
    po_box_deviating_region    VARCHAR(3),
    po_box_is_without_number   BOOLEAN       DEFAULT FALSE,
    po_box_lobby_name          VARCHAR(40),
    po_box_postal_code         VARCHAR(10),
    postal_code                VARCHAR(10),
    region                     VARCHAR(3),
    street_name                VARCHAR(60),
    tax_jurisdiction           VARCHAR(15),
    transport_zone             VARCHAR(10),
    PRIMARY KEY (business_partner, address_id)
);
```

---

## 5. `business_partners`

### JSON Sample
```json
{
  "businessPartner": "310000108",
  "customer": "310000108",
  "businessPartnerCategory": "2",
  "businessPartnerFullName": "Cardenas, Parker and Avila",
  "businessPartnerGrouping": "Y101",
  "businessPartnerName": "Cardenas, Parker and Avila",
  "correspondenceLanguage": "",
  "createdByUser": "USER750",
  "creationDate": "2024-04-16T00:00:00.000Z",
  "creationTime": { "hours": 13, "minutes": 36, "seconds": 43 },
  "firstName": "",
  "formOfAddress": "0003",
  "industry": "",
  "lastChangeDate": "2025-06-27T00:00:00.000Z",
  "lastName": "",
  "organizationBpName1": "Cardenas, Parker and Avila",
  "organizationBpName2": "",
  "businessPartnerIsBlocked": false,
  "isMarkedForArchiving": false
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "business_partners",
  "type": "object",
  "required": ["businessPartner"],
  "properties": {
    "businessPartner":          { "type": "string", "maxLength": 10 },
    "customer":                 { "type": "string", "maxLength": 10 },
    "businessPartnerCategory":  { "type": "string", "maxLength": 1 },
    "businessPartnerFullName":  { "type": "string", "maxLength": 81 },
    "businessPartnerGrouping":  { "type": "string", "maxLength": 4 },
    "businessPartnerName":      { "type": "string", "maxLength": 81 },
    "correspondenceLanguage":   { "type": "string", "maxLength": 2 },
    "createdByUser":            { "type": "string", "maxLength": 12 },
    "creationDate":             { "type": "string", "format": "date-time" },
    "creationTime":             {
      "type": "object",
      "properties": {
        "hours":   { "type": "integer" },
        "minutes": { "type": "integer" },
        "seconds": { "type": "integer" }
      }
    },
    "firstName":                { "type": "string", "maxLength": 40 },
    "formOfAddress":            { "type": "string", "maxLength": 4 },
    "industry":                 { "type": "string", "maxLength": 10 },
    "lastChangeDate":           { "type": "string", "format": "date-time" },
    "lastName":                 { "type": "string", "maxLength": 40 },
    "organizationBpName1":      { "type": "string", "maxLength": 40 },
    "organizationBpName2":      { "type": "string", "maxLength": 40 },
    "businessPartnerIsBlocked": { "type": "boolean" },
    "isMarkedForArchiving":     { "type": "boolean" }
  }
}
```

### DDL
```sql
CREATE TABLE business_partners (
    business_partner           VARCHAR(10)   NOT NULL PRIMARY KEY,
    customer                   VARCHAR(10),
    business_partner_category  VARCHAR(1),
    business_partner_full_name VARCHAR(81),
    business_partner_grouping  VARCHAR(4),
    business_partner_name      VARCHAR(81),
    correspondence_language    VARCHAR(2),
    created_by_user            VARCHAR(12),
    creation_date              DATE,
    creation_time              TIME,
    first_name                 VARCHAR(40),
    form_of_address            VARCHAR(4),
    industry                   VARCHAR(10),
    last_change_date           DATE,
    last_name                  VARCHAR(40),
    organization_bp_name1      VARCHAR(40),
    organization_bp_name2      VARCHAR(40),
    business_partner_is_blocked BOOLEAN      DEFAULT FALSE,
    is_marked_for_archiving    BOOLEAN       DEFAULT FALSE
);
```

---

## 6. `customer_company_assignments`

### JSON Sample
```json
{
  "customer": "310000108",
  "companyCode": "ABCD",
  "accountingClerk": "",
  "accountingClerkFaxNumber": "",
  "accountingClerkInternetAddress": "",
  "accountingClerkPhoneNumber": "",
  "alternativePayerAccount": "",
  "paymentBlockingReason": "",
  "paymentMethodsList": "",
  "paymentTerms": "",
  "reconciliationAccount": "15500010",
  "deletionIndicator": false,
  "customerAccountGroup": "Y101"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "customer_company_assignments",
  "type": "object",
  "required": ["customer", "companyCode"],
  "properties": {
    "customer":                        { "type": "string", "maxLength": 10 },
    "companyCode":                     { "type": "string", "maxLength": 4 },
    "accountingClerk":                 { "type": "string", "maxLength": 2 },
    "accountingClerkFaxNumber":        { "type": "string", "maxLength": 31 },
    "accountingClerkInternetAddress":  { "type": "string", "maxLength": 130 },
    "accountingClerkPhoneNumber":      { "type": "string", "maxLength": 30 },
    "alternativePayerAccount":         { "type": "string", "maxLength": 10 },
    "paymentBlockingReason":           { "type": "string", "maxLength": 1 },
    "paymentMethodsList":              { "type": "string", "maxLength": 10 },
    "paymentTerms":                    { "type": "string", "maxLength": 4 },
    "reconciliationAccount":           { "type": "string", "maxLength": 10 },
    "deletionIndicator":               { "type": "boolean" },
    "customerAccountGroup":            { "type": "string", "maxLength": 4 }
  }
}
```

### DDL
```sql
CREATE TABLE customer_company_assignments (
    customer                         VARCHAR(10)   NOT NULL,
    company_code                     VARCHAR(4)    NOT NULL,
    accounting_clerk                 VARCHAR(2),
    accounting_clerk_fax_number      VARCHAR(31),
    accounting_clerk_internet_address VARCHAR(130),
    accounting_clerk_phone_number    VARCHAR(30),
    alternative_payer_account        VARCHAR(10),
    payment_blocking_reason          VARCHAR(1),
    payment_methods_list             VARCHAR(10),
    payment_terms                    VARCHAR(4),
    reconciliation_account           VARCHAR(10),
    deletion_indicator               BOOLEAN       DEFAULT FALSE,
    customer_account_group           VARCHAR(4),
    PRIMARY KEY (customer, company_code)
);
```

---

## 7. `customer_sales_area_assignments`

### JSON Sample
```json
{
  "customer": "310000108",
  "salesOrganization": "ABCD",
  "distributionChannel": "05",
  "division": "99",
  "billingIsBlockedForCustomer": "",
  "completeDeliveryIsDefined": false,
  "creditControlArea": "",
  "currency": "INR",
  "customerPaymentTerms": "Z009",
  "deliveryPriority": "0",
  "incotermsClassification": "FOR",
  "incotermsLocation1": "Millerborough",
  "salesGroup": "",
  "salesOffice": "",
  "shippingCondition": "01",
  "slsUnlmtdOvrdelivIsAllwd": false,
  "supplyingPlant": "",
  "salesDistrict": "",
  "exchangeRateType": "M"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "customer_sales_area_assignments",
  "type": "object",
  "required": ["customer", "salesOrganization", "distributionChannel", "division"],
  "properties": {
    "customer":                   { "type": "string", "maxLength": 10 },
    "salesOrganization":          { "type": "string", "maxLength": 4 },
    "distributionChannel":        { "type": "string", "maxLength": 2 },
    "division":                   { "type": "string", "maxLength": 2 },
    "billingIsBlockedForCustomer":{ "type": "string", "maxLength": 2 },
    "completeDeliveryIsDefined":  { "type": "boolean" },
    "creditControlArea":          { "type": "string", "maxLength": 4 },
    "currency":                   { "type": "string", "maxLength": 5 },
    "customerPaymentTerms":       { "type": "string", "maxLength": 4 },
    "deliveryPriority":           { "type": "string", "maxLength": 2 },
    "incotermsClassification":    { "type": "string", "maxLength": 3 },
    "incotermsLocation1":         { "type": "string", "maxLength": 70 },
    "salesGroup":                 { "type": "string", "maxLength": 3 },
    "salesOffice":                { "type": "string", "maxLength": 4 },
    "shippingCondition":          { "type": "string", "maxLength": 2 },
    "slsUnlmtdOvrdelivIsAllwd":   { "type": "boolean" },
    "supplyingPlant":             { "type": "string", "maxLength": 4 },
    "salesDistrict":              { "type": "string", "maxLength": 6 },
    "exchangeRateType":           { "type": "string", "maxLength": 4 }
  }
}
```

### DDL
```sql
CREATE TABLE customer_sales_area_assignments (
    customer                      VARCHAR(10)   NOT NULL,
    sales_organization            VARCHAR(4)    NOT NULL,
    distribution_channel          VARCHAR(2)    NOT NULL,
    division                      VARCHAR(2)    NOT NULL,
    billing_is_blocked_for_customer VARCHAR(2),
    complete_delivery_is_defined  BOOLEAN       DEFAULT FALSE,
    credit_control_area           VARCHAR(4),
    currency                      VARCHAR(5),
    customer_payment_terms        VARCHAR(4),
    delivery_priority             VARCHAR(2),
    incoterms_classification      VARCHAR(3),
    incoterms_location1           VARCHAR(70),
    sales_group                   VARCHAR(3),
    sales_office                  VARCHAR(4),
    shipping_condition            VARCHAR(2),
    sls_unlmtd_ovrdeliv_is_allwd  BOOLEAN       DEFAULT FALSE,
    supplying_plant               VARCHAR(4),
    sales_district                VARCHAR(6),
    exchange_rate_type            VARCHAR(4),
    PRIMARY KEY (customer, sales_organization, distribution_channel, division)
);
```

---

## 8. `journal_entry_items_accounts_receivable`

### JSON Sample
```json
{
  "companyCode": "ABCD",
  "fiscalYear": "2025",
  "accountingDocument": "9400000220",
  "glAccount": "15500020",
  "referenceDocument": "90504219",
  "costCenter": "",
  "profitCenter": "ABC001",
  "transactionCurrency": "INR",
  "amountInTransactionCurrency": "897.03",
  "companyCodeCurrency": "INR",
  "amountInCompanyCodeCurrency": "897.03",
  "postingDate": "2025-04-02T00:00:00.000Z",
  "documentDate": "2025-04-02T00:00:00.000Z",
  "accountingDocumentType": "RV",
  "accountingDocumentItem": "1",
  "assignmentReference": "",
  "lastChangeDateTime": "2025-07-24T11:43:59.000Z",
  "customer": "320000083",
  "financialAccountType": "D",
  "clearingDate": "2025-04-02T00:00:00.000Z",
  "clearingAccountingDocument": "9400635977",
  "clearingDocFiscalYear": "2025"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "journal_entry_items_accounts_receivable",
  "type": "object",
  "required": ["companyCode", "fiscalYear", "accountingDocument", "accountingDocumentItem"],
  "properties": {
    "companyCode":                    { "type": "string", "maxLength": 4 },
    "fiscalYear":                     { "type": "string", "maxLength": 4 },
    "accountingDocument":             { "type": "string", "maxLength": 10 },
    "glAccount":                      { "type": "string", "maxLength": 10 },
    "referenceDocument":              { "type": "string", "maxLength": 16 },
    "costCenter":                     { "type": "string", "maxLength": 10 },
    "profitCenter":                   { "type": "string", "maxLength": 10 },
    "transactionCurrency":            { "type": "string", "maxLength": 5 },
    "amountInTransactionCurrency":    { "type": "string" },
    "companyCodeCurrency":            { "type": "string", "maxLength": 5 },
    "amountInCompanyCodeCurrency":    { "type": "string" },
    "postingDate":                    { "type": "string", "format": "date-time" },
    "documentDate":                   { "type": "string", "format": "date-time" },
    "accountingDocumentType":         { "type": "string", "maxLength": 2 },
    "accountingDocumentItem":         { "type": "string", "maxLength": 3 },
    "assignmentReference":            { "type": "string", "maxLength": 18 },
    "lastChangeDateTime":             { "type": "string", "format": "date-time" },
    "customer":                       { "type": "string", "maxLength": 10 },
    "financialAccountType":           { "type": "string", "maxLength": 1 },
    "clearingDate":                   { "type": ["string", "null"], "format": "date-time" },
    "clearingAccountingDocument":     { "type": ["string", "null"], "maxLength": 10 },
    "clearingDocFiscalYear":          { "type": ["string", "null"], "maxLength": 4 }
  }
}
```

### DDL
```sql
CREATE TABLE journal_entry_items_accounts_receivable (
    company_code                   VARCHAR(4)    NOT NULL,
    fiscal_year                    VARCHAR(4)    NOT NULL,
    accounting_document            VARCHAR(10)   NOT NULL,
    accounting_document_item       VARCHAR(3)    NOT NULL,
    gl_account                     VARCHAR(10),
    reference_document             VARCHAR(16),
    cost_center                    VARCHAR(10),
    profit_center                  VARCHAR(10),
    transaction_currency           VARCHAR(5),
    amount_in_transaction_currency NUMERIC(23, 2),
    company_code_currency          VARCHAR(5),
    amount_in_company_code_currency NUMERIC(23, 2),
    posting_date                   DATE,
    document_date                  DATE,
    accounting_document_type       VARCHAR(2),
    assignment_reference           VARCHAR(18),
    last_change_datetime           TIMESTAMPTZ,
    customer                       VARCHAR(10),
    financial_account_type         VARCHAR(1),
    clearing_date                  DATE,
    clearing_accounting_document   VARCHAR(10),
    clearing_doc_fiscal_year       VARCHAR(4),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);
```

---

## 9. `outbound_delivery_headers`

### JSON Sample
```json
{
  "actualGoodsMovementDate": null,
  "actualGoodsMovementTime": { "hours": 0, "minutes": 0, "seconds": 0 },
  "creationDate": "2025-03-31T00:00:00.000Z",
  "creationTime": { "hours": 6, "minutes": 49, "seconds": 13 },
  "deliveryBlockReason": "",
  "deliveryDocument": "80737721",
  "hdrGeneralIncompletionStatus": "C",
  "headerBillingBlockReason": "",
  "lastChangeDate": null,
  "overallGoodsMovementStatus": "A",
  "overallPickingStatus": "C",
  "overallProofOfDeliveryStatus": "",
  "shippingPoint": "1920"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "outbound_delivery_headers",
  "type": "object",
  "required": ["deliveryDocument"],
  "properties": {
    "actualGoodsMovementDate":      { "type": ["string", "null"], "format": "date-time" },
    "actualGoodsMovementTime":      {
      "type": "object",
      "properties": {
        "hours":   { "type": "integer" },
        "minutes": { "type": "integer" },
        "seconds": { "type": "integer" }
      }
    },
    "creationDate":                 { "type": "string", "format": "date-time" },
    "creationTime":                 {
      "type": "object",
      "properties": {
        "hours":   { "type": "integer" },
        "minutes": { "type": "integer" },
        "seconds": { "type": "integer" }
      }
    },
    "deliveryBlockReason":          { "type": "string", "maxLength": 2 },
    "deliveryDocument":             { "type": "string", "maxLength": 10 },
    "hdrGeneralIncompletionStatus": { "type": "string", "maxLength": 1 },
    "headerBillingBlockReason":     { "type": "string", "maxLength": 2 },
    "lastChangeDate":               { "type": ["string", "null"], "format": "date-time" },
    "overallGoodsMovementStatus":   { "type": "string", "maxLength": 1 },
    "overallPickingStatus":         { "type": "string", "maxLength": 1 },
    "overallProofOfDeliveryStatus": { "type": "string", "maxLength": 1 },
    "shippingPoint":                { "type": "string", "maxLength": 4 }
  }
}
```

### DDL
```sql
CREATE TABLE outbound_delivery_headers (
    delivery_document               VARCHAR(10)   NOT NULL PRIMARY KEY,
    actual_goods_movement_date      DATE,
    actual_goods_movement_time      TIME,
    creation_date                   DATE,
    creation_time                   TIME,
    delivery_block_reason           VARCHAR(2),
    hdr_general_incompletion_status VARCHAR(1),
    header_billing_block_reason     VARCHAR(2),
    last_change_date                DATE,
    overall_goods_movement_status   VARCHAR(1),
    overall_picking_status          VARCHAR(1),
    overall_proof_of_delivery_status VARCHAR(1),
    shipping_point                  VARCHAR(4)
);
```

---

## 10. `outbound_delivery_items`

### JSON Sample
```json
{
  "actualDeliveryQuantity": "1",
  "batch": "",
  "deliveryDocument": "80738076",
  "deliveryDocumentItem": "000010",
  "deliveryQuantityUnit": "PC",
  "itemBillingBlockReason": "",
  "lastChangeDate": null,
  "plant": "WB05",
  "referenceSdDocument": "740556",
  "referenceSdDocumentItem": "000010",
  "storageLocation": "5031"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "outbound_delivery_items",
  "type": "object",
  "required": ["deliveryDocument", "deliveryDocumentItem"],
  "properties": {
    "actualDeliveryQuantity":   { "type": "string" },
    "batch":                    { "type": "string", "maxLength": 10 },
    "deliveryDocument":         { "type": "string", "maxLength": 10 },
    "deliveryDocumentItem":     { "type": "string", "maxLength": 6 },
    "deliveryQuantityUnit":     { "type": "string", "maxLength": 3 },
    "itemBillingBlockReason":   { "type": "string", "maxLength": 2 },
    "lastChangeDate":           { "type": ["string", "null"], "format": "date-time" },
    "plant":                    { "type": "string", "maxLength": 4 },
    "referenceSdDocument":      { "type": "string", "maxLength": 10 },
    "referenceSdDocumentItem":  { "type": "string", "maxLength": 6 },
    "storageLocation":          { "type": "string", "maxLength": 4 }
  }
}
```

### DDL
```sql
CREATE TABLE outbound_delivery_items (
    delivery_document          VARCHAR(10)   NOT NULL,
    delivery_document_item     VARCHAR(6)    NOT NULL,
    actual_delivery_quantity   NUMERIC(15, 3),
    batch                      VARCHAR(10),
    delivery_quantity_unit     VARCHAR(3),
    item_billing_block_reason  VARCHAR(2),
    last_change_date           DATE,
    plant                      VARCHAR(4),
    reference_sd_document      VARCHAR(10),
    reference_sd_document_item VARCHAR(6),
    storage_location           VARCHAR(4),
    PRIMARY KEY (delivery_document, delivery_document_item)
);
```

---

## 11. `payments_accounts_receivable`

### JSON Sample
```json
{
  "companyCode": "ABCD",
  "fiscalYear": "2025",
  "accountingDocument": "9400000220",
  "accountingDocumentItem": "1",
  "clearingDate": "2025-04-02T00:00:00.000Z",
  "clearingAccountingDocument": "9400635977",
  "clearingDocFiscalYear": "2025",
  "amountInTransactionCurrency": "897.03",
  "transactionCurrency": "INR",
  "amountInCompanyCodeCurrency": "897.03",
  "companyCodeCurrency": "INR",
  "customer": "320000083",
  "invoiceReference": null,
  "invoiceReferenceFiscalYear": null,
  "salesDocument": null,
  "salesDocumentItem": null,
  "postingDate": "2025-04-02T00:00:00.000Z",
  "documentDate": "2025-04-02T00:00:00.000Z",
  "assignmentReference": null,
  "glAccount": "15500020",
  "financialAccountType": "D",
  "profitCenter": "ABC001",
  "costCenter": null
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "payments_accounts_receivable",
  "type": "object",
  "required": ["companyCode", "fiscalYear", "accountingDocument", "accountingDocumentItem"],
  "properties": {
    "companyCode":                    { "type": "string", "maxLength": 4 },
    "fiscalYear":                     { "type": "string", "maxLength": 4 },
    "accountingDocument":             { "type": "string", "maxLength": 10 },
    "accountingDocumentItem":         { "type": "string", "maxLength": 3 },
    "clearingDate":                   { "type": ["string", "null"], "format": "date-time" },
    "clearingAccountingDocument":     { "type": ["string", "null"], "maxLength": 10 },
    "clearingDocFiscalYear":          { "type": ["string", "null"], "maxLength": 4 },
    "amountInTransactionCurrency":    { "type": "string" },
    "transactionCurrency":            { "type": "string", "maxLength": 5 },
    "amountInCompanyCodeCurrency":    { "type": "string" },
    "companyCodeCurrency":            { "type": "string", "maxLength": 5 },
    "customer":                       { "type": "string", "maxLength": 10 },
    "invoiceReference":               { "type": ["string", "null"], "maxLength": 10 },
    "invoiceReferenceFiscalYear":     { "type": ["string", "null"], "maxLength": 4 },
    "salesDocument":                  { "type": ["string", "null"], "maxLength": 10 },
    "salesDocumentItem":              { "type": ["string", "null"], "maxLength": 6 },
    "postingDate":                    { "type": "string", "format": "date-time" },
    "documentDate":                   { "type": "string", "format": "date-time" },
    "assignmentReference":            { "type": ["string", "null"], "maxLength": 18 },
    "glAccount":                      { "type": "string", "maxLength": 10 },
    "financialAccountType":           { "type": "string", "maxLength": 1 },
    "profitCenter":                   { "type": "string", "maxLength": 10 },
    "costCenter":                     { "type": ["string", "null"], "maxLength": 10 }
  }
}
```

### DDL
```sql
CREATE TABLE payments_accounts_receivable (
    company_code                    VARCHAR(4)    NOT NULL,
    fiscal_year                     VARCHAR(4)    NOT NULL,
    accounting_document             VARCHAR(10)   NOT NULL,
    accounting_document_item        VARCHAR(3)    NOT NULL,
    clearing_date                   DATE,
    clearing_accounting_document    VARCHAR(10),
    clearing_doc_fiscal_year        VARCHAR(4),
    amount_in_transaction_currency  NUMERIC(23, 2),
    transaction_currency            VARCHAR(5),
    amount_in_company_code_currency NUMERIC(23, 2),
    company_code_currency           VARCHAR(5),
    customer                        VARCHAR(10),
    invoice_reference               VARCHAR(10),
    invoice_reference_fiscal_year   VARCHAR(4),
    sales_document                  VARCHAR(10),
    sales_document_item             VARCHAR(6),
    posting_date                    DATE,
    document_date                   DATE,
    assignment_reference            VARCHAR(18),
    gl_account                      VARCHAR(10),
    financial_account_type          VARCHAR(1),
    profit_center                   VARCHAR(10),
    cost_center                     VARCHAR(10),
    PRIMARY KEY (company_code, fiscal_year, accounting_document, accounting_document_item)
);
```

---

## 12. `plants`

### JSON Sample
```json
{
  "plant": "1001",
  "plantName": "Lake Christopher Plant",
  "valuationArea": "1001",
  "plantCustomer": "1001",
  "plantSupplier": "1001",
  "factoryCalendar": "IN",
  "defaultPurchasingOrganization": "",
  "salesOrganization": "ABCD",
  "addressId": "93",
  "plantCategory": "",
  "distributionChannel": "80",
  "division": "99",
  "language": "EN",
  "isMarkedForArchiving": false
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "plants",
  "type": "object",
  "required": ["plant"],
  "properties": {
    "plant":                          { "type": "string", "maxLength": 4 },
    "plantName":                      { "type": "string", "maxLength": 30 },
    "valuationArea":                  { "type": "string", "maxLength": 4 },
    "plantCustomer":                  { "type": "string", "maxLength": 10 },
    "plantSupplier":                  { "type": "string", "maxLength": 10 },
    "factoryCalendar":                { "type": "string", "maxLength": 2 },
    "defaultPurchasingOrganization":  { "type": "string", "maxLength": 4 },
    "salesOrganization":              { "type": "string", "maxLength": 4 },
    "addressId":                      { "type": "string", "maxLength": 10 },
    "plantCategory":                  { "type": "string", "maxLength": 1 },
    "distributionChannel":            { "type": "string", "maxLength": 2 },
    "division":                       { "type": "string", "maxLength": 2 },
    "language":                       { "type": "string", "maxLength": 2 },
    "isMarkedForArchiving":           { "type": "boolean" }
  }
}
```

### DDL
```sql
CREATE TABLE plants (
    plant                             VARCHAR(4)    NOT NULL PRIMARY KEY,
    plant_name                        VARCHAR(30),
    valuation_area                    VARCHAR(4),
    plant_customer                    VARCHAR(10),
    plant_supplier                    VARCHAR(10),
    factory_calendar                  VARCHAR(2),
    default_purchasing_organization   VARCHAR(4),
    sales_organization                VARCHAR(4),
    address_id                        VARCHAR(10),
    plant_category                    VARCHAR(1),
    distribution_channel              VARCHAR(2),
    division                          VARCHAR(2),
    language                          VARCHAR(2),
    is_marked_for_archiving           BOOLEAN       DEFAULT FALSE
);
```

---

## 13. `product_descriptions`

### JSON Sample
```json
{
  "product": "3001456",
  "language": "EN",
  "productDescription": "WB-CG CHARCOAL GANG"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "product_descriptions",
  "type": "object",
  "required": ["product", "language"],
  "properties": {
    "product":            { "type": "string", "maxLength": 40 },
    "language":           { "type": "string", "maxLength": 2 },
    "productDescription": { "type": "string", "maxLength": 40 }
  }
}
```

### DDL
```sql
CREATE TABLE product_descriptions (
    product             VARCHAR(40)   NOT NULL,
    language            VARCHAR(2)    NOT NULL,
    product_description VARCHAR(40),
    PRIMARY KEY (product, language)
);
```

---

## 14. `product_plants`

### JSON Sample
```json
{
  "product": "S8907367010814",
  "plant": "MP07",
  "countryOfOrigin": "",
  "regionOfOrigin": "",
  "productionInvtryManagedLoc": "",
  "availabilityCheckType": "NC",
  "fiscalYearVariant": "",
  "profitCenter": "ABC001",
  "mrpType": "ND"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "product_plants",
  "type": "object",
  "required": ["product", "plant"],
  "properties": {
    "product":                    { "type": "string", "maxLength": 40 },
    "plant":                      { "type": "string", "maxLength": 4 },
    "countryOfOrigin":            { "type": "string", "maxLength": 3 },
    "regionOfOrigin":             { "type": "string", "maxLength": 3 },
    "productionInvtryManagedLoc": { "type": "string", "maxLength": 4 },
    "availabilityCheckType":      { "type": "string", "maxLength": 2 },
    "fiscalYearVariant":          { "type": "string", "maxLength": 2 },
    "profitCenter":               { "type": "string", "maxLength": 10 },
    "mrpType":                    { "type": "string", "maxLength": 2 }
  }
}
```

### DDL
```sql
CREATE TABLE product_plants (
    product                      VARCHAR(40)   NOT NULL,
    plant                        VARCHAR(4)    NOT NULL,
    country_of_origin            VARCHAR(3),
    region_of_origin             VARCHAR(3),
    production_invtry_managed_loc VARCHAR(4),
    availability_check_type      VARCHAR(2),
    fiscal_year_variant          VARCHAR(2),
    profit_center                VARCHAR(10),
    mrp_type                     VARCHAR(2),
    PRIMARY KEY (product, plant)
);
```

---

## 15. `product_storage_locations`

### JSON Sample
```json
{
  "product": "B8907367022152",
  "plant": "HR05",
  "storageLocation": "5066",
  "physicalInventoryBlockInd": "",
  "dateOfLastPostedCntUnRstrcdStk": null
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "product_storage_locations",
  "type": "object",
  "required": ["product", "plant", "storageLocation"],
  "properties": {
    "product":                        { "type": "string", "maxLength": 40 },
    "plant":                          { "type": "string", "maxLength": 4 },
    "storageLocation":                { "type": "string", "maxLength": 4 },
    "physicalInventoryBlockInd":      { "type": "string", "maxLength": 1 },
    "dateOfLastPostedCntUnRstrcdStk": { "type": ["string", "null"], "format": "date-time" }
  }
}
```

### DDL
```sql
CREATE TABLE product_storage_locations (
    product                           VARCHAR(40)   NOT NULL,
    plant                             VARCHAR(4)    NOT NULL,
    storage_location                  VARCHAR(4)    NOT NULL,
    physical_inventory_block_ind      VARCHAR(1),
    date_of_last_posted_cnt_un_rstrcd_stk DATE,
    PRIMARY KEY (product, plant, storage_location)
);
```

---

## 16. `products`

### JSON Sample
```json
{
  "product": "B8907367002246",
  "productType": "ZF01",
  "crossPlantStatus": "",
  "crossPlantStatusValidityDate": null,
  "creationDate": "2024-12-12T00:00:00.000Z",
  "createdByUser": "USER108",
  "lastChangeDate": "2025-09-16T00:00:00.000Z",
  "lastChangeDateTime": "2025-09-16T13:12:08.000Z",
  "isMarkedForDeletion": false,
  "productOldId": "ABC-WEB-225",
  "grossWeight": "0.11",
  "weightUnit": "KG",
  "netWeight": "0.1",
  "productGroup": "ZFG1001",
  "baseUnit": "PC",
  "division": "01",
  "industrySector": "M"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "products",
  "type": "object",
  "required": ["product"],
  "properties": {
    "product":                     { "type": "string", "maxLength": 40 },
    "productType":                 { "type": "string", "maxLength": 4 },
    "crossPlantStatus":            { "type": "string", "maxLength": 2 },
    "crossPlantStatusValidityDate":{ "type": ["string", "null"], "format": "date-time" },
    "creationDate":                { "type": "string", "format": "date-time" },
    "createdByUser":               { "type": "string", "maxLength": 12 },
    "lastChangeDate":              { "type": "string", "format": "date-time" },
    "lastChangeDateTime":          { "type": "string", "format": "date-time" },
    "isMarkedForDeletion":         { "type": "boolean" },
    "productOldId":                { "type": "string", "maxLength": 40 },
    "grossWeight":                 { "type": "string" },
    "weightUnit":                  { "type": "string", "maxLength": 3 },
    "netWeight":                   { "type": "string" },
    "productGroup":                { "type": "string", "maxLength": 9 },
    "baseUnit":                    { "type": "string", "maxLength": 3 },
    "division":                    { "type": "string", "maxLength": 2 },
    "industrySector":              { "type": "string", "maxLength": 1 }
  }
}
```

### DDL
```sql
CREATE TABLE products (
    product                        VARCHAR(40)   NOT NULL PRIMARY KEY,
    product_type                   VARCHAR(4),
    cross_plant_status             VARCHAR(2),
    cross_plant_status_validity_date DATE,
    creation_date                  DATE,
    created_by_user                VARCHAR(12),
    last_change_date               DATE,
    last_change_datetime           TIMESTAMPTZ,
    is_marked_for_deletion         BOOLEAN       DEFAULT FALSE,
    product_old_id                 VARCHAR(40),
    gross_weight                   NUMERIC(13, 3),
    weight_unit                    VARCHAR(3),
    net_weight                     NUMERIC(13, 3),
    product_group                  VARCHAR(9),
    base_unit                      VARCHAR(3),
    division                       VARCHAR(2),
    industry_sector                VARCHAR(1)
);
```

---

## 17. `sales_order_headers`

### JSON Sample
```json
{
  "salesOrder": "740506",
  "salesOrderType": "OR",
  "salesOrganization": "ABCD",
  "distributionChannel": "05",
  "organizationDivision": "99",
  "salesGroup": "",
  "salesOffice": "",
  "soldToParty": "310000108",
  "creationDate": "2025-03-31T00:00:00.000Z",
  "createdByUser": "USER786",
  "lastChangeDateTime": "2025-03-31T06:42:38.786Z",
  "totalNetAmount": "17108.25",
  "overallDeliveryStatus": "C",
  "overallOrdReltdBillgStatus": "",
  "overallSdDocReferenceStatus": "",
  "transactionCurrency": "INR",
  "pricingDate": "2025-03-31T00:00:00.000Z",
  "requestedDeliveryDate": "2025-03-31T00:00:00.000Z",
  "headerBillingBlockReason": "",
  "deliveryBlockReason": "",
  "incotermsClassification": "FOR",
  "incotermsLocation1": "Millerborough",
  "customerPaymentTerms": "Z009",
  "totalCreditCheckStatus": ""
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "sales_order_headers",
  "type": "object",
  "required": ["salesOrder"],
  "properties": {
    "salesOrder":                   { "type": "string", "maxLength": 10 },
    "salesOrderType":               { "type": "string", "maxLength": 4 },
    "salesOrganization":            { "type": "string", "maxLength": 4 },
    "distributionChannel":          { "type": "string", "maxLength": 2 },
    "organizationDivision":         { "type": "string", "maxLength": 2 },
    "salesGroup":                   { "type": "string", "maxLength": 3 },
    "salesOffice":                  { "type": "string", "maxLength": 4 },
    "soldToParty":                  { "type": "string", "maxLength": 10 },
    "creationDate":                 { "type": "string", "format": "date-time" },
    "createdByUser":                { "type": "string", "maxLength": 12 },
    "lastChangeDateTime":           { "type": "string", "format": "date-time" },
    "totalNetAmount":               { "type": "string" },
    "overallDeliveryStatus":        { "type": "string", "maxLength": 1 },
    "overallOrdReltdBillgStatus":   { "type": "string", "maxLength": 1 },
    "overallSdDocReferenceStatus":  { "type": "string", "maxLength": 1 },
    "transactionCurrency":          { "type": "string", "maxLength": 5 },
    "pricingDate":                  { "type": "string", "format": "date-time" },
    "requestedDeliveryDate":        { "type": "string", "format": "date-time" },
    "headerBillingBlockReason":     { "type": "string", "maxLength": 2 },
    "deliveryBlockReason":          { "type": "string", "maxLength": 2 },
    "incotermsClassification":      { "type": "string", "maxLength": 3 },
    "incotermsLocation1":           { "type": "string", "maxLength": 70 },
    "customerPaymentTerms":         { "type": "string", "maxLength": 4 },
    "totalCreditCheckStatus":       { "type": "string", "maxLength": 1 }
  }
}
```

### DDL
```sql
CREATE TABLE sales_order_headers (
    sales_order                    VARCHAR(10)   NOT NULL PRIMARY KEY,
    sales_order_type               VARCHAR(4),
    sales_organization             VARCHAR(4),
    distribution_channel           VARCHAR(2),
    organization_division          VARCHAR(2),
    sales_group                    VARCHAR(3),
    sales_office                   VARCHAR(4),
    sold_to_party                  VARCHAR(10),
    creation_date                  DATE,
    created_by_user                VARCHAR(12),
    last_change_datetime           TIMESTAMPTZ,
    total_net_amount               NUMERIC(15, 2),
    overall_delivery_status        VARCHAR(1),
    overall_ord_reltd_billg_status VARCHAR(1),
    overall_sd_doc_reference_status VARCHAR(1),
    transaction_currency           VARCHAR(5),
    pricing_date                   DATE,
    requested_delivery_date        DATE,
    header_billing_block_reason    VARCHAR(2),
    delivery_block_reason          VARCHAR(2),
    incoterms_classification       VARCHAR(3),
    incoterms_location1            VARCHAR(70),
    customer_payment_terms         VARCHAR(4),
    total_credit_check_status      VARCHAR(1)
);
```

---

## 18. `sales_order_items`

### JSON Sample
```json
{
  "salesOrder": "740506",
  "salesOrderItem": "10",
  "salesOrderItemCategory": "TAN",
  "material": "S8907367001003",
  "requestedQuantity": "48",
  "requestedQuantityUnit": "PC",
  "transactionCurrency": "INR",
  "netAmount": "9966.1",
  "materialGroup": "ZFG1001",
  "productionPlant": "1920",
  "storageLocation": "V2S2",
  "salesDocumentRjcnReason": "",
  "itemBillingBlockReason": ""
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "sales_order_items",
  "type": "object",
  "required": ["salesOrder", "salesOrderItem"],
  "properties": {
    "salesOrder":               { "type": "string", "maxLength": 10 },
    "salesOrderItem":           { "type": "string", "maxLength": 6 },
    "salesOrderItemCategory":   { "type": "string", "maxLength": 4 },
    "material":                 { "type": "string", "maxLength": 40 },
    "requestedQuantity":        { "type": "string" },
    "requestedQuantityUnit":    { "type": "string", "maxLength": 3 },
    "transactionCurrency":      { "type": "string", "maxLength": 5 },
    "netAmount":                { "type": "string" },
    "materialGroup":            { "type": "string", "maxLength": 9 },
    "productionPlant":          { "type": "string", "maxLength": 4 },
    "storageLocation":          { "type": "string", "maxLength": 4 },
    "salesDocumentRjcnReason":  { "type": "string", "maxLength": 2 },
    "itemBillingBlockReason":   { "type": "string", "maxLength": 2 }
  }
}
```

### DDL
```sql
CREATE TABLE sales_order_items (
    sales_order                VARCHAR(10)   NOT NULL,
    sales_order_item           VARCHAR(6)    NOT NULL,
    sales_order_item_category  VARCHAR(4),
    material                   VARCHAR(40),
    requested_quantity         NUMERIC(15, 3),
    requested_quantity_unit    VARCHAR(3),
    transaction_currency       VARCHAR(5),
    net_amount                 NUMERIC(15, 2),
    material_group             VARCHAR(9),
    production_plant           VARCHAR(4),
    storage_location           VARCHAR(4),
    sales_document_rjcn_reason VARCHAR(2),
    item_billing_block_reason  VARCHAR(2),
    PRIMARY KEY (sales_order, sales_order_item)
);
```

---

## 19. `sales_order_schedule_lines`

### JSON Sample
```json
{
  "salesOrder": "740506",
  "salesOrderItem": "10",
  "scheduleLine": "1",
  "confirmedDeliveryDate": "2025-03-31T00:00:00.000Z",
  "orderQuantityUnit": "PC",
  "confdOrderQtyByMatlAvailCheck": "48"
}
```

### JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "sales_order_schedule_lines",
  "type": "object",
  "required": ["salesOrder", "salesOrderItem", "scheduleLine"],
  "properties": {
    "salesOrder":                    { "type": "string", "maxLength": 10 },
    "salesOrderItem":                { "type": "string", "maxLength": 6 },
    "scheduleLine":                  { "type": "string", "maxLength": 4 },
    "confirmedDeliveryDate":         { "type": "string", "format": "date-time" },
    "orderQuantityUnit":             { "type": "string", "maxLength": 3 },
    "confdOrderQtyByMatlAvailCheck": { "type": "string" }
  }
}
```

### DDL
```sql
CREATE TABLE sales_order_schedule_lines (
    sales_order                       VARCHAR(10)   NOT NULL,
    sales_order_item                  VARCHAR(6)    NOT NULL,
    schedule_line                     VARCHAR(4)    NOT NULL,
    confirmed_delivery_date           DATE,
    order_quantity_unit               VARCHAR(3),
    confd_order_qty_by_matl_avail_check NUMERIC(15, 3),
    PRIMARY KEY (sales_order, sales_order_item, schedule_line)
);
```

---

## Summary

| # | Table | Primary Key | Notable Fields |
|---|-------|-------------|----------------|
| 1 | `billing_document_headers` | `billing_document` | `billing_document_is_cancelled`, `total_net_amount` |
| 2 | `billing_document_cancellations` | `billing_document` | `billing_document_is_cancelled`, `cancelled_billing_document` |
| 3 | `billing_document_items` | `(billing_document, billing_document_item)` | `material`, `net_amount` |
| 4 | `business_partner_addresses` | `(business_partner, address_id)` | `address_uuid`, `city_name`, `country` |
| 5 | `business_partners` | `business_partner` | `business_partner_category`, `business_partner_is_blocked` |
| 6 | `customer_company_assignments` | `(customer, company_code)` | `reconciliation_account`, `payment_terms` |
| 7 | `customer_sales_area_assignments` | `(customer, sales_organization, distribution_channel, division)` | `incoterms_classification`, `customer_payment_terms` |
| 8 | `journal_entry_items_accounts_receivable` | `(company_code, fiscal_year, accounting_document, accounting_document_item)` | `amount_in_transaction_currency`, `clearing_date` |
| 9 | `outbound_delivery_headers` | `delivery_document` | `overall_goods_movement_status`, `overall_picking_status` |
| 10 | `outbound_delivery_items` | `(delivery_document, delivery_document_item)` | `plant`, `storage_location` |
| 11 | `payments_accounts_receivable` | `(company_code, fiscal_year, accounting_document, accounting_document_item)` | `clearing_accounting_document`, `invoice_reference` |
| 12 | `plants` | `plant` | `plant_name`, `sales_organization` |
| 13 | `product_descriptions` | `(product, language)` | `product_description` |
| 14 | `product_plants` | `(product, plant)` | `availability_check_type`, `mrp_type`, `profit_center` |
| 15 | `product_storage_locations` | `(product, plant, storage_location)` | `physical_inventory_block_ind` |
| 16 | `products` | `product` | `product_type`, `gross_weight`, `net_weight`, `product_group` |
| 17 | `sales_order_headers` | `sales_order` | `sold_to_party`, `total_net_amount`, `overall_delivery_status` |
| 18 | `sales_order_items` | `(sales_order, sales_order_item)` | `material`, `net_amount`, `production_plant` |
| 19 | `sales_order_schedule_lines` | `(sales_order, sales_order_item, schedule_line)` | `confirmed_delivery_date`, `confd_order_qty_by_matl_avail_check` |
