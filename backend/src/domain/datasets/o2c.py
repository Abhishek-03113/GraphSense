"""SAP Order-to-Cash (O2C) graph definition.

NODE TYPES (11)
  Core flow  : Customer, SalesOrder, SalesOrderItem, Delivery, DeliveryItem,
               Invoice, InvoiceItem, JournalEntry, Payment
  Supporting : Product, Address

EDGE TYPES (11) - direction follows business causality
  Customer       --[PLACED]-----> SalesOrder
  SalesOrder     --[HAS_ITEM]---> SalesOrderItem
  SalesOrderItem --[INCLUDES]---> Product
  Delivery       --[HAS_ITEM]---> DeliveryItem
  DeliveryItem   --[FULFILLS]---> SalesOrderItem   (cross-document link)
  Invoice        --[HAS_ITEM]---> InvoiceItem
  InvoiceItem    --[BILLS_FOR]--> DeliveryItem     (cross-document link)
  Invoice        --[BILLED_TO]--> Customer
  Invoice        --[GENERATES]--> JournalEntry
  Payment        --[CLEARS]-----> JournalEntry
  Customer       --[HAS_ADDRESS]-> Address

Full trace (Sales Order -> Delivery -> Billing -> Journal Entry), starting at
any Invoice node with depth >= 2:
  Invoice -> HAS_ITEM -> InvoiceItem -> BILLS_FOR -> DeliveryItem
          <- HAS_ITEM <- Delivery
  DeliveryItem -> FULFILLS -> SalesOrderItem <- HAS_ITEM <- SalesOrder
  Invoice -> GENERATES -> JournalEntry <- CLEARS <- Payment

Composite item ids ("doc-item") strip leading zeros from the item number.
Cross-document references use short item numbers (e.g. '10') while the item
tables use zero-padded ones (e.g. '000010'), so every composite id goes through
the same normalisation and matches regardless of which table it came from.

EDA-validated join paths (data/sap-o2c-data):
  sold_to_party -> business_partners.customer                      (100%)
  sales_order_items.sales_order -> sales_order_headers              (100%)
  outbound_delivery_items.reference_sd_document
      -> sales_order_headers.sales_order                            (100% -> 86%)
  outbound_delivery_items.delivery_document
      -> outbound_delivery_headers                                  (100%)
  billing_document_items.reference_sd_document
      -> outbound_delivery_headers.delivery_document                (100% -> 97%)
  billing_document_headers.accounting_document
      ~ journal_entries_AR.accounting_document                      (75% -> 100%)
  journal_entries_AR.accounting_document
      ~ payments_AR.accounting_document                             (98% -> 100%)
  NOTE: the direct billing -> payment link is broken (invoice_reference is
        100% NULL); the bridge goes via accounting_document through journal
        entries.
"""

from src.domain.graph_models import FlowDefinition
from src.domain.graph_schema import EdgeTypeDef, GraphDataset, NodeTypeDef

# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------
# Order matters: it is the order of the keys in /api/graph/summary and of the
# default type list used by the full-graph sampler.

NODE_TYPES = (
    NodeTypeDef(
        key="SalesOrder",
        label="Sales order",
        plural="Sales orders",
        description="A customer's request to buy products.",
        category="document",
        accent="blue",
        icon="file-text",
        is_primary=True,
        display_properties=(
            "sold_to_party",
            "creation_date",
            "total_net_amount",
            "transaction_currency",
            "overall_delivery_status",
        ),
        table="sales_order_headers",
        id_columns=("sales_order",),
    ),
    NodeTypeDef(
        key="SalesOrderItem",
        label="Sales order item",
        plural="Sales order items",
        description="One product line on a sales order.",
        category="item",
        accent="cyan",
        icon="list",
        display_properties=(
            "material",
            "requested_quantity",
            "requested_quantity_unit",
            "net_amount",
            "transaction_currency",
        ),
        table="sales_order_items",
        id_columns=("sales_order", "sales_order_item"),
    ),
    NodeTypeDef(
        key="Delivery",
        label="Delivery",
        plural="Deliveries",
        description="An outbound shipment of goods to a customer.",
        category="document",
        accent="orange",
        icon="truck",
        is_primary=True,
        display_properties=(
            "creation_date",
            "overall_goods_movement_status",
            "overall_picking_status",
            "shipping_point",
        ),
        table="outbound_delivery_headers",
        id_columns=("delivery_document",),
    ),
    NodeTypeDef(
        key="DeliveryItem",
        label="Delivery item",
        plural="Delivery items",
        description="One product line on a delivery.",
        category="item",
        accent="yellow",
        icon="package",
        display_properties=(
            "actual_delivery_quantity",
            "delivery_quantity_unit",
            "plant",
            "storage_location",
        ),
        table="outbound_delivery_items",
        id_columns=("delivery_document", "delivery_document_item"),
    ),
    NodeTypeDef(
        key="Invoice",
        label="Invoice",
        plural="Invoices",
        description="A billing document charging a customer for delivered goods.",
        category="document",
        accent="green",
        icon="receipt",
        is_primary=True,
        display_properties=(
            "billing_document_date",
            "total_net_amount",
            "transaction_currency",
            "billing_document_is_cancelled",
            "accounting_document",
        ),
        table="billing_document_headers",
        id_columns=("billing_document",),
    ),
    NodeTypeDef(
        key="InvoiceItem",
        label="Invoice item",
        plural="Invoice items",
        description="One billed line on an invoice.",
        category="item",
        accent="mint",
        icon="list",
        display_properties=(
            "material",
            "billing_quantity",
            "billing_quantity_unit",
            "net_amount",
            "transaction_currency",
        ),
        table="billing_document_items",
        id_columns=("billing_document", "billing_document_item"),
    ),
    NodeTypeDef(
        key="JournalEntry",
        label="Journal entry",
        plural="Journal entries",
        description="The accounting document posted when an invoice is booked.",
        category="finance",
        accent="purple",
        icon="book-open",
        is_primary=True,
        display_properties=(
            "posting_date",
            "amount_in_transaction_currency",
            "transaction_currency",
            "gl_account",
            "clearing_date",
        ),
        table="journal_entry_items_accounts_receivable",
        id_columns=("accounting_document",),
        # One row per line item: count unique documents, not rows.
        count_distinct=True,
    ),
    NodeTypeDef(
        key="Payment",
        label="Payment",
        plural="Payments",
        description="A customer payment that clears an open receivable.",
        category="finance",
        accent="pink",
        icon="credit-card",
        is_primary=True,
        display_properties=(
            "posting_date",
            "amount_in_transaction_currency",
            "transaction_currency",
            "clearing_date",
            "customer",
        ),
        table="payments_accounts_receivable",
        id_columns=("accounting_document",),
        count_distinct=True,
    ),
    NodeTypeDef(
        key="Product",
        label="Product",
        plural="Products",
        description="A material or product that can be sold.",
        category="master",
        accent="teal",
        icon="box",
        is_primary=True,
        display_properties=("product_type", "product_group", "base_unit", "gross_weight"),
        table="products",
        id_columns=("product",),
    ),
    NodeTypeDef(
        key="Customer",
        label="Customer",
        plural="Customers",
        description="A business partner who buys from you.",
        category="party",
        accent="indigo",
        icon="user",
        is_primary=True,
        display_properties=(
            "business_partner_full_name",
            "business_partner_category",
            "creation_date",
            "business_partner_is_blocked",
        ),
        table="business_partners",
        id_columns=("business_partner",),
    ),
    NodeTypeDef(
        key="Address",
        label="Address",
        plural="Addresses",
        description="A postal address on file for a customer.",
        category="master",
        accent="gray",
        icon="map-pin",
        display_properties=("street_name", "city_name", "postal_code", "country"),
        table="business_partner_addresses",
        id_columns=("business_partner", "address_id"),
    ),
)

# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------
# Order matters: it is the order of the UNION ALL blocks in the edge query.

EDGE_TYPES = (
    EdgeTypeDef(
        key="PLACED",
        label="placed",
        source="Customer",
        target="SalesOrder",
        description="Customer placed the sales order.",
        table="sales_order_headers",
        alias="soh",
        source_columns=("sold_to_party",),
        target_columns=("sales_order",),
        not_null=("sold_to_party",),
    ),
    EdgeTypeDef(
        key="HAS_ITEM",
        label="has item",
        source="SalesOrder",
        target="SalesOrderItem",
        description="Sales order contains the line item.",
        table="sales_order_items",
        alias="soi",
        source_columns=("sales_order",),
        target_columns=("sales_order", "sales_order_item"),
    ),
    EdgeTypeDef(
        key="INCLUDES",
        label="includes",
        source="SalesOrderItem",
        target="Product",
        description="Sales order item is for the product.",
        table="sales_order_items",
        alias="soi",
        source_columns=("sales_order", "sales_order_item"),
        target_columns=("material",),
        not_null=("material",),
    ),
    EdgeTypeDef(
        key="HAS_ITEM",
        label="has item",
        source="Delivery",
        target="DeliveryItem",
        description="Delivery contains the line item.",
        table="outbound_delivery_items",
        alias="odi",
        source_columns=("delivery_document",),
        target_columns=("delivery_document", "delivery_document_item"),
    ),
    # Cross-document link: ties delivery fulfilment back to the sales order item.
    EdgeTypeDef(
        key="FULFILLS",
        label="fulfills",
        source="DeliveryItem",
        target="SalesOrderItem",
        description="Delivery item fulfills the sales order item.",
        table="outbound_delivery_items",
        alias="odi",
        source_columns=("delivery_document", "delivery_document_item"),
        target_columns=("reference_sd_document", "reference_sd_document_item"),
        not_null=("reference_sd_document",),
    ),
    EdgeTypeDef(
        key="HAS_ITEM",
        label="has item",
        source="Invoice",
        target="InvoiceItem",
        description="Invoice contains the billed line.",
        table="billing_document_items",
        alias="bdi",
        source_columns=("billing_document",),
        target_columns=("billing_document", "billing_document_item"),
    ),
    # Cross-document link: ties a billing line back to the delivery item it covers.
    EdgeTypeDef(
        key="BILLS_FOR",
        label="bills for",
        source="InvoiceItem",
        target="DeliveryItem",
        description="Invoice item bills for the delivery item.",
        table="billing_document_items",
        alias="bdi",
        source_columns=("billing_document", "billing_document_item"),
        target_columns=("reference_sd_document", "reference_sd_document_item"),
        not_null=("reference_sd_document",),
    ),
    EdgeTypeDef(
        key="BILLED_TO",
        label="billed to",
        source="Invoice",
        target="Customer",
        description="Invoice was billed to the customer.",
        table="billing_document_headers",
        alias="bdh",
        source_columns=("billing_document",),
        target_columns=("sold_to_party",),
        not_null=("sold_to_party",),
    ),
    # The accounting document created when a billing document is posted.
    EdgeTypeDef(
        key="GENERATES",
        label="generates",
        source="Invoice",
        target="JournalEntry",
        description="Invoice generates the journal entry when posted.",
        table="billing_document_headers",
        alias="bdh",
        source_columns=("billing_document",),
        target_columns=("accounting_document",),
        not_null=("accounting_document",),
    ),
    # A payment clears the open receivable journal entry.
    EdgeTypeDef(
        key="CLEARS",
        label="clears",
        source="Payment",
        target="JournalEntry",
        description="Payment clears the open journal entry.",
        table="payments_accounts_receivable",
        alias="par",
        source_columns=("accounting_document",),
        target_columns=("clearing_accounting_document",),
        not_null=("clearing_accounting_document",),
        distinct=True,
    ),
    EdgeTypeDef(
        key="HAS_ADDRESS",
        label="has address",
        source="Customer",
        target="Address",
        description="Customer has the address on file.",
        table="business_partner_addresses",
        alias="bpa",
        source_columns=("business_partner",),
        target_columns=("business_partner", "address_id"),
    ),
)

# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

FLOWS = (
    FlowDefinition(
        id="sales",
        label="Sales Flow",
        description="Customer places a sales order; line items reference products",
        node_types=["Customer", "SalesOrder", "SalesOrderItem", "Product"],
        edge_types=["PLACED", "HAS_ITEM", "INCLUDES"],
    ),
    FlowDefinition(
        id="fulfillment",
        label="Fulfillment Flow",
        description="Sales order items fulfilled via outbound delivery documents",
        # FULFILLS: (delivery_doc, delivery_item) -> (so, so_item) cross-doc link
        node_types=["SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Product"],
        edge_types=["HAS_ITEM", "FULFILLS", "INCLUDES"],
    ),
    FlowDefinition(
        id="billing",
        label="Billing Flow",
        description="Deliveries billed to customers via billing documents",
        # BILLS_FOR: (billing_doc, billing_item) -> (delivery_doc, delivery_item) cross-doc link
        node_types=["Delivery", "DeliveryItem", "Invoice", "InvoiceItem", "Customer"],
        edge_types=["HAS_ITEM", "BILLS_FOR", "BILLED_TO"],
    ),
    FlowDefinition(
        id="financial",
        label="Financial Flow",
        description="Billing documents post journal entries cleared by payments",
        # Includes Customer because journal_entries_AR.customer -> business_partners.customer
        # (25% match). Direct billing->payment link broken; traversal goes
        # Invoice -> JournalEntry <- Payment.
        node_types=["Invoice", "JournalEntry", "Payment", "Customer"],
        edge_types=["GENERATES", "CLEARS", "BILLED_TO"],
    ),
    FlowDefinition(
        id="customer_master",
        label="Customer Master",
        description="Customer profile with address and account configuration",
        # business_partner_addresses.business_partner -> business_partners (100%)
        node_types=["Customer", "Address"],
        edge_types=["HAS_ADDRESS"],
    ),
    FlowDefinition(
        id="full_o2c",
        label="Full O2C Flow",
        description=(
            "End-to-end: Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment"
        ),
        # 9-hop EDA path:
        #   Customer -> SO -> SO Items -> Delivery Items -> Delivery Header
        #            -> Billing Items -> Billing Header -> Journal Entry -> Payment
        node_types=[
            "Customer", "Address",
            "SalesOrder", "SalesOrderItem",
            "Delivery", "DeliveryItem",
            "Invoice", "InvoiceItem",
            "JournalEntry", "Payment",
            "Product",
        ],
        edge_types=[
            "PLACED", "HAS_ITEM", "INCLUDES",
            "FULFILLS",
            "BILLS_FOR", "BILLED_TO",
            "GENERATES", "CLEARS",
            "HAS_ADDRESS",
        ],
    ),
)

# ---------------------------------------------------------------------------
# Entity recognition in query results
# ---------------------------------------------------------------------------
# (column-name substring, node type); first match wins, so more specific
# substrings come first.  Used by the chat pipeline to highlight result rows.

ENTITY_COLUMN_HINTS = (
    ("billing_doc_number", "Invoice"),
    ("billing_document", "Invoice"),
    ("invoice", "Invoice"),
    ("sales_order_id", "SalesOrder"),
    ("sales_order", "SalesOrder"),
    ("delivery_document", "Delivery"),
    ("delivery_id", "Delivery"),
    ("delivery", "Delivery"),
    ("accounting_document", "JournalEntry"),
    ("journal_entry_id", "JournalEntry"),
    ("journal_entry", "JournalEntry"),
    ("payment_document", "Payment"),
    ("payment_id", "Payment"),
    ("customer_id", "Customer"),
    ("customer", "Customer"),
    ("business_partner", "Customer"),
    ("material_id", "Product"),
    ("material", "Product"),
    ("product", "Product"),
)

DATASET = GraphDataset(
    id="o2c",
    name="Order to Cash",
    description="Sales orders through delivery, billing and payment.",
    node_types=NODE_TYPES,
    edge_types=EDGE_TYPES,
    flows=FLOWS,
    entity_column_hints=ENTITY_COLUMN_HINTS,
)
