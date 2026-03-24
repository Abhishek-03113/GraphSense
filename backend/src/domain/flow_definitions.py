from typing import Dict, Any

# ---------------------------------------------------------------------------
# O2C Flow Definitions
# ---------------------------------------------------------------------------
# Each entry maps a flow_id to:
#   label       : human-readable name
#   description : short summary of the flow
#   node_types  : node types included in this flow
#   edge_types  : edge types to include when querying this flow
# ---------------------------------------------------------------------------

FLOW_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "sales": {
        "id": "sales",
        "label": "Sales Flow",
        "description": "Customer places a sales order and its line items reference products",
        "node_types": ["Customer", "SalesOrder", "SalesOrderItem", "Product"],
        "edge_types": ["PLACED", "HAS_ITEM", "INCLUDES"],
    },
    "fulfillment": {
        "id": "fulfillment",
        "label": "Fulfillment Flow",
        "description": "Sales order items are fulfilled via delivery documents",
        "node_types": ["SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Product"],
        "edge_types": ["HAS_ITEM", "FULFILLS", "INCLUDES"],
    },
    "billing": {
        "id": "billing",
        "label": "Billing Flow",
        "description": "Deliveries are billed to customers via invoice documents",
        "node_types": ["Delivery", "DeliveryItem", "Invoice", "InvoiceItem", "Customer"],
        "edge_types": ["HAS_ITEM", "BILLS_FOR", "BILLED_TO"],
    },
    "financial": {
        "id": "financial",
        "label": "Financial Flow",
        "description": "Invoices generate journal entries that are cleared by payments",
        "node_types": ["Invoice", "JournalEntry", "Payment"],
        "edge_types": ["GENERATES", "CLEARS"],
    },
    "full_o2c": {
        "id": "full_o2c",
        "label": "Full O2C Flow",
        "description": "End-to-end: Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment",
        "node_types": [
            "Customer", "SalesOrder", "SalesOrderItem",
            "Delivery", "DeliveryItem",
            "Invoice", "InvoiceItem",
            "JournalEntry", "Payment",
            "Product",
        ],
        "edge_types": ["PLACED", "HAS_ITEM", "INCLUDES", "FULFILLS", "BILLS_FOR", "BILLED_TO", "GENERATES", "CLEARS"],
    },
}
