from typing import Dict, Any

# ---------------------------------------------------------------------------
# O2C Flow Definitions
# ---------------------------------------------------------------------------
# Each entry maps a flow_id to:
#   label       : human-readable name
#   description : short summary of the flow
#   node_types  : node types included in this flow
#   edge_types  : edge types to include when querying this flow
#
# EDA-validated join paths (data/sap-o2c-data):
#   sold_to_party → business_partners.customer         (100%)
#   sales_order_items.sales_order → sales_order_headers (100%)
#   outbound_delivery_items.reference_sd_document → sales_order_headers.sales_order (100% → 86%)
#   outbound_delivery_items.delivery_document → outbound_delivery_headers (100%)
#   billing_document_items.reference_sd_document → outbound_delivery_headers.delivery_document (100% → 97%)
#   billing_document_headers.accounting_document ≈ journal_entries_AR.accounting_document (75% → 100%)
#   journal_entries_AR.accounting_document ≈ payments_AR.accounting_document (98% → 100%)
#   NOTE: Direct billing→payment link broken (invoice_reference 100% NULL);
#         bridge via accounting_document through journal entries.
# ---------------------------------------------------------------------------

FLOW_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "sales": {
        "id": "sales",
        "label": "Sales Flow",
        "description": "Customer places a sales order; line items reference products",
        "node_types": ["Customer", "SalesOrder", "SalesOrderItem", "Product"],
        "edge_types": ["PLACED", "HAS_ITEM", "INCLUDES"],
    },
    "fulfillment": {
        "id": "fulfillment",
        "label": "Fulfillment Flow",
        "description": "Sales order items fulfilled via outbound delivery documents",
        # FULFILLS: (delivery_doc, delivery_item) → (so, so_item) cross-doc link
        "node_types": ["SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Product"],
        "edge_types": ["HAS_ITEM", "FULFILLS", "INCLUDES"],
    },
    "billing": {
        "id": "billing",
        "label": "Billing Flow",
        "description": "Deliveries billed to customers via billing documents",
        # BILLS_FOR: (billing_doc, billing_item) → (delivery_doc, delivery_item) cross-doc link
        "node_types": ["Delivery", "DeliveryItem", "Invoice", "InvoiceItem", "Customer"],
        "edge_types": ["HAS_ITEM", "BILLS_FOR", "BILLED_TO"],
    },
    "financial": {
        "id": "financial",
        "label": "Financial Flow",
        "description": "Billing documents post journal entries cleared by payments",
        # Includes Customer because journal_entries_AR.customer → business_partners.customer (25% match)
        # Direct billing→payment link broken; traversal goes Invoice → JournalEntry ← Payment
        "node_types": ["Invoice", "JournalEntry", "Payment", "Customer"],
        "edge_types": ["GENERATES", "CLEARS", "BILLED_TO"],
    },
    "customer_master": {
        "id": "customer_master",
        "label": "Customer Master",
        "description": "Customer profile with address and account configuration",
        # business_partner_addresses.business_partner → business_partners (100%)
        "node_types": ["Customer", "Address"],
        "edge_types": ["HAS_ADDRESS"],
    },
    "full_o2c": {
        "id": "full_o2c",
        "label": "Full O2C Flow",
        "description": "End-to-end: Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment",
        # 9-hop EDA path:
        #   Customer → SO → SO Items → Delivery Items → Delivery Header
        #            → Billing Items → Billing Header → Journal Entry → Payment
        "node_types": [
            "Customer", "Address",
            "SalesOrder", "SalesOrderItem",
            "Delivery", "DeliveryItem",
            "Invoice", "InvoiceItem",
            "JournalEntry", "Payment",
            "Product",
        ],
        "edge_types": [
            "PLACED", "HAS_ITEM", "INCLUDES",
            "FULFILLS",
            "BILLS_FOR", "BILLED_TO",
            "GENERATES", "CLEARS",
            "HAS_ADDRESS",
        ],
    },
}
