// Realistic order-to-cash style fixtures used by the screenshot script.
// They mirror the API contracts (summary, graph, flows, schema, entities, chat)
// so the whole UI can be exercised without a backend.
//
// SCHEMA is a copy of what GET /api/graph/schema returns for the bundled O2C dataset (same keys,
// labels, accents and display_properties), and record properties use the real column names and
// JSON shapes (ISO dates, numeric amounts). Check for drift against a running backend with
//   node e2e/check-schema.mjs [http://localhost:8000/api]

const TYPES = [
  {"key": "SalesOrder", "label": "Sales order", "plural": "Sales orders", "description": "A customer's request to buy products.", "category": "document", "accent": "blue", "icon": "file-text", "is_primary": true, "display_properties": ["sold_to_party", "creation_date", "total_net_amount", "transaction_currency", "overall_delivery_status"]},
  {"key": "SalesOrderItem", "label": "Sales order item", "plural": "Sales order items", "description": "One product line on a sales order.", "category": "item", "accent": "cyan", "icon": "list", "is_primary": false, "display_properties": ["material", "requested_quantity", "requested_quantity_unit", "net_amount", "transaction_currency"]},
  {"key": "Delivery", "label": "Delivery", "plural": "Deliveries", "description": "An outbound shipment of goods to a customer.", "category": "document", "accent": "orange", "icon": "truck", "is_primary": true, "display_properties": ["creation_date", "overall_goods_movement_status", "overall_picking_status", "shipping_point"]},
  {"key": "DeliveryItem", "label": "Delivery item", "plural": "Delivery items", "description": "One product line on a delivery.", "category": "item", "accent": "yellow", "icon": "package", "is_primary": false, "display_properties": ["actual_delivery_quantity", "delivery_quantity_unit", "plant", "storage_location"]},
  {"key": "Invoice", "label": "Invoice", "plural": "Invoices", "description": "A billing document charging a customer for delivered goods.", "category": "document", "accent": "green", "icon": "receipt", "is_primary": true, "display_properties": ["billing_document_date", "total_net_amount", "transaction_currency", "billing_document_is_cancelled", "accounting_document"]},
  {"key": "InvoiceItem", "label": "Invoice item", "plural": "Invoice items", "description": "One billed line on an invoice.", "category": "item", "accent": "mint", "icon": "list", "is_primary": false, "display_properties": ["material", "billing_quantity", "billing_quantity_unit", "net_amount", "transaction_currency"]},
  {"key": "JournalEntry", "label": "Journal entry", "plural": "Journal entries", "description": "The accounting document posted when an invoice is booked.", "category": "finance", "accent": "purple", "icon": "book-open", "is_primary": true, "display_properties": ["posting_date", "amount_in_transaction_currency", "transaction_currency", "gl_account", "clearing_date"]},
  {"key": "Payment", "label": "Payment", "plural": "Payments", "description": "A customer payment that clears an open receivable.", "category": "finance", "accent": "pink", "icon": "credit-card", "is_primary": true, "display_properties": ["posting_date", "amount_in_transaction_currency", "transaction_currency", "clearing_date", "customer"]},
  {"key": "Product", "label": "Product", "plural": "Products", "description": "A material or product that can be sold.", "category": "master", "accent": "teal", "icon": "box", "is_primary": true, "display_properties": ["product_description", "product_type", "product_group", "base_unit", "gross_weight"]},
  {"key": "Customer", "label": "Customer", "plural": "Customers", "description": "A business partner who buys from you.", "category": "party", "accent": "indigo", "icon": "user", "is_primary": true, "display_properties": ["business_partner_full_name", "business_partner_category", "creation_date", "business_partner_is_blocked"]},
  {"key": "Address", "label": "Address", "plural": "Addresses", "description": "A postal address on file for a customer.", "category": "master", "accent": "gray", "icon": "map-pin", "is_primary": false, "display_properties": ["street_name", "city_name", "postal_code", "country"]},
];

const EDGES = [
  {"key": "PLACED", "label": "placed", "source": "Customer", "target": "SalesOrder", "description": "Customer placed the sales order."},
  {"key": "HAS_ITEM", "label": "has item", "source": "SalesOrder", "target": "SalesOrderItem", "description": "Sales order contains the line item."},
  {"key": "INCLUDES", "label": "includes", "source": "SalesOrderItem", "target": "Product", "description": "Sales order item is for the product."},
  {"key": "HAS_ITEM", "label": "has item", "source": "Delivery", "target": "DeliveryItem", "description": "Delivery contains the line item."},
  {"key": "FULFILLS", "label": "fulfills", "source": "DeliveryItem", "target": "SalesOrderItem", "description": "Delivery item fulfills the sales order item."},
  {"key": "HAS_ITEM", "label": "has item", "source": "Invoice", "target": "InvoiceItem", "description": "Invoice contains the billed line."},
  {"key": "BILLS_FOR", "label": "bills for", "source": "InvoiceItem", "target": "DeliveryItem", "description": "Invoice item bills for the delivery item."},
  {"key": "BILLED_TO", "label": "billed to", "source": "Invoice", "target": "Customer", "description": "Invoice was billed to the customer."},
  {"key": "GENERATES", "label": "generates", "source": "Invoice", "target": "JournalEntry", "description": "Invoice generates the journal entry when posted."},
  {"key": "CLEARS", "label": "clears", "source": "Payment", "target": "JournalEntry", "description": "Payment clears the open journal entry."},
  {"key": "HAS_ADDRESS", "label": "has address", "source": "Customer", "target": "Address", "description": "Customer has the address on file."},
];

const FLOWS = [
  {"id": "sales", "label": "Sales Flow", "description": "Customer places a sales order; line items reference products", "node_types": ["Customer", "SalesOrder", "SalesOrderItem", "Product"], "edge_types": ["PLACED", "HAS_ITEM", "INCLUDES"]},
  {"id": "fulfillment", "label": "Fulfillment Flow", "description": "Sales order items fulfilled via outbound delivery documents", "node_types": ["SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Product"], "edge_types": ["HAS_ITEM", "FULFILLS", "INCLUDES"]},
  {"id": "billing", "label": "Billing Flow", "description": "Deliveries billed to customers via billing documents", "node_types": ["Delivery", "DeliveryItem", "Invoice", "InvoiceItem", "Customer"], "edge_types": ["HAS_ITEM", "BILLS_FOR", "BILLED_TO"]},
  {"id": "financial", "label": "Financial Flow", "description": "Billing documents post journal entries cleared by payments", "node_types": ["Invoice", "JournalEntry", "Payment", "Customer"], "edge_types": ["GENERATES", "CLEARS", "BILLED_TO"]},
  {"id": "customer_master", "label": "Customer Master", "description": "Customer profile with address and account configuration", "node_types": ["Customer", "Address"], "edge_types": ["HAS_ADDRESS"]},
  {"id": "full_o2c", "label": "Full O2C Flow", "description": "End-to-end: Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment", "node_types": ["Customer", "Address", "SalesOrder", "SalesOrderItem", "Delivery", "DeliveryItem", "Invoice", "InvoiceItem", "JournalEntry", "Payment", "Product"], "edge_types": ["PLACED", "HAS_ITEM", "INCLUDES", "FULFILLS", "BILLS_FOR", "BILLED_TO", "GENERATES", "CLEARS", "HAS_ADDRESS"]},
];

export const SCHEMA = {
  domain: {"id": "o2c", "name": "Order to Cash", "description": "Sales orders through delivery, billing and payment."},
  node_types: TYPES,
  edge_types: EDGES,
  flows: FLOWS,
};

const TYPE_BY_KEY = Object.fromEntries(TYPES.map((type) => [type.key, type]));

// ── Records ────────────────────────────────────────────────
const nodes = [];
const edges = [];
const byType = {};

// Like the backend, a record with a natural name is labelled with it, and every other record "<Type> <id>".
function addNode(type, value, properties = {}, name = null) {
  const node = { id: `${type}:${value}`, type, label: name ?? `${type} ${value}`, properties };
  nodes.push(node);
  (byType[type] ??= []).push(node);
  return node;
}
function link(type, from, to) {
  edges.push({ id: `${from.id}-${to.id}-${type}`, source: from.id, target: to.id, type, properties: {} });
}

const customerNames = ['Cardenas, Parker and Avila', 'Nelson, Fitzpatrick and Jordan', 'Melton, Bender and Sanchez', 'Bernard Horn'];
const countries = ['US', 'DE', 'GB', 'FR'];
const cities = ['Chicago', 'Munich', 'Leeds', 'Lyon'];
const regions = ['IL', 'BY', 'ENG', 'ARA'];
const products = [
  ['S8907367000001', 'Trail running shoes', 'Footwear'],
  ['S8907367000002', 'Waterproof jacket', 'Outerwear'],
  ['S8907367000003', 'Merino base layer', 'Apparel'],
  ['S8907367000004', 'Hydration pack', 'Equipment'],
  ['S8907367000005', 'Trekking poles', 'Equipment'],
  ['S8907367000006', 'Headlamp', 'Equipment'],
];

const customers = customerNames.map((name, index) => {
  const partner = `${310000100 + index}`;
  return addNode(
    'Customer',
    partner,
    {
      business_partner_full_name: name,
      business_partner_category: '2',
      creation_date: `2023-1${index}-0${3 + index}`,
      business_partner_is_blocked: false,
      customer: partner,
      business_partner_name: name,
      business_partner_grouping: 'BP02',
    },
    name,
  );
});
customers.forEach((customer, index) => {
  const address = addNode('Address', `${customer.id.split(':')[1]}-${1000 + index * 7}`, {
    street_name: `${10 + index * 3} Market Street`,
    city_name: cities[index],
    postal_code: `${10000 + index * 1234}`,
    country: countries[index],
    region: regions[index],
  });
  link('HAS_ADDRESS', customer, address);
});
const productNodes = products.map(([code, description, group], index) =>
  addNode(
    'Product',
    code,
    { product_description: description, product_type: index % 3 ? 'ZPRD' : 'FERT', product_group: group, base_unit: 'PC', gross_weight: 0.4 + index * 0.55 },
    description,
  ),
);

let soNumber = 740500;
let diNumber = 80738000;
let invNumber = 90504200;
let jeNumber = 9400000000;
const soItems = [];
const deliveries = [];
const invoices = [];

for (let index = 0; index < 8; index += 1) {
  const customer = customers[index % customers.length];
  const so = addNode('SalesOrder', `${(soNumber += 3)}`, {
    sold_to_party: customer.id.split(':')[1],
    creation_date: `2025-0${1 + (index % 6)}-${10 + index}`,
    total_net_amount: 1200 + index * 345.5,
    transaction_currency: ['USD', 'USD', 'EUR'][index % 3],
    overall_delivery_status: index % 3 === 0 ? 'C' : 'A',
    sales_order_type: 'OR',
    sales_organization: '1710',
  });
  link('PLACED', customer, so);
  const lines = index % 2 === 0 ? 2 : 1;
  for (let line = 0; line < lines; line += 1) {
    const item = addNode('SalesOrderItem', `${so.id.split(':')[1]}-${(line + 1) * 10}`, {
      material: productNodes[(index + line) % productNodes.length].id.split(':')[1],
      requested_quantity: 2 + line * 3,
      requested_quantity_unit: 'PC',
      net_amount: 300 + index * 80 + line * 120 + 0.5,
      transaction_currency: so.properties.transaction_currency,
    });
    link('HAS_ITEM', so, item);
    link('INCLUDES', item, productNodes[(index + line) % productNodes.length]);
    soItems.push({ so, item, customer });
  }
}

soItems.slice(0, 6).forEach(({ item, customer }, index) => {
  if (index % 2 === 0) {
    const delivery = addNode('Delivery', `${(diNumber += 2)}`, {
      creation_date: `2025-02-${10 + index}`,
      overall_goods_movement_status: 'C',
      overall_picking_status: 'C',
      shipping_point: '1710',
    });
    deliveries.push({ delivery, customer });
    const deliveryItem = addNode('DeliveryItem', `${delivery.id.split(':')[1]}-10`, {
      actual_delivery_quantity: 2,
      delivery_quantity_unit: 'PC',
      plant: '1710',
      storage_location: '171A',
    });
    link('HAS_ITEM', delivery, deliveryItem);
    link('FULFILLS', deliveryItem, item);
    deliveries[deliveries.length - 1].deliveryItem = deliveryItem;
  }
});

deliveries.slice(0, 3).forEach(({ customer, deliveryItem }, index) => {
  const invoice = addNode('Invoice', `${(invNumber += 1)}`, {
    billing_document_date: `2025-03-0${index + 2}`,
    total_net_amount: 980 + index * 210,
    transaction_currency: 'USD',
    billing_document_is_cancelled: false,
    accounting_document: `${jeNumber + 1}`,
  });
  invoices.push(invoice);
  link('BILLED_TO', invoice, customer);
  const invoiceItem = addNode('InvoiceItem', `${invoice.id.split(':')[1]}-10`, {
    material: productNodes[index].id.split(':')[1],
    billing_quantity: 2,
    billing_quantity_unit: 'PC',
    net_amount: 980 + index * 210,
    transaction_currency: 'USD',
  });
  link('HAS_ITEM', invoice, invoiceItem);
  link('BILLS_FOR', invoiceItem, deliveryItem);
  const journal = addNode('JournalEntry', `${(jeNumber += 7)}`, {
    posting_date: `2025-03-0${index + 2}`,
    amount_in_transaction_currency: 980 + index * 210,
    transaction_currency: 'USD',
    gl_account: '15005000',
    clearing_date: index < 2 ? `2025-04-0${index + 1}` : undefined,
  });
  link('GENERATES', invoice, journal);
  if (index < 2) {
    const payment = addNode('Payment', `${(jeNumber += 3) + 1000000}`, {
      posting_date: `2025-04-0${index + 1}`,
      amount_in_transaction_currency: 980 + index * 210,
      transaction_currency: 'USD',
      clearing_date: `2025-04-0${index + 1}`,
      customer: customer.id.split(':')[1],
    });
    link('CLEARS', payment, journal);
  }
});

export const GRAPH = { nodes, edges };

const countsByType = Object.fromEntries(Object.entries(byType).map(([type, list]) => [type, list.length]));
// Make the headline counts look like a real dataset while the graph itself stays small.
export const SUMMARY = {
  nodes: {
    Customer: 8,
    SalesOrder: 100,
    Delivery: 86,
    Invoice: 163,
    Payment: 120,
    SalesOrderItem: 167,
    DeliveryItem: 137,
    InvoiceItem: 245,
    JournalEntry: 123,
    Product: 69,
    Address: 8,
  },
  edges: {
    PLACED: 100,
    HAS_ITEM: 549,
    INCLUDES: 167,
    FULFILLS: 137,
    BILLS_FOR: 245,
    BILLED_TO: 163,
    GENERATES: 123,
    CLEARS: 120,
    HAS_ADDRESS: 8,
  },
};
export const EMPTY_SUMMARY = { nodes: {}, edges: {} };
export const LOADED_COUNTS = countsByType;

// ── Helpers that behave like the backend ───────────────────
// Like the backend, traversal reaches shared reference records (party and master types) but does not expand through them.
const isTerminal = (nodeId) => ['party', 'master'].includes(TYPE_BY_KEY[nodeId.split(':')[0]]?.category);

export function subgraph(type, id, depth) {
  const rootId = `${type}:${id}`;
  const adjacency = new Map();
  for (const edge of edges) {
    (adjacency.get(edge.source) ?? adjacency.set(edge.source, []).get(edge.source)).push(edge);
    (adjacency.get(edge.target) ?? adjacency.set(edge.target, []).get(edge.target)).push(edge);
  }
  const seen = new Set([rootId]);
  const picked = new Map();
  let frontier = [rootId];
  for (let level = 0; level < depth; level += 1) {
    const next = [];
    for (const current of frontier) {
      if (level > 0 && isTerminal(current)) continue;
      for (const edge of adjacency.get(current) ?? []) {
        picked.set(edge.id, edge);
        for (const end of [edge.source, edge.target]) {
          if (!seen.has(end)) {
            seen.add(end);
            next.push(end);
          }
        }
      }
    }
    frontier = next;
  }
  const result = nodes.filter((node) => seen.has(node.id));
  if (!result.some((node) => node.id === rootId)) {
    result.push({ id: rootId, type, label: `${type} ${id}`, properties: {} });
  }
  return { nodes: result, edges: [...picked.values()] };
}

export function fullGraph(limit) {
  const keep = new Set();
  for (const list of Object.values(byType)) list.slice(0, limit).forEach((node) => keep.add(node.id));
  return {
    nodes: nodes.filter((node) => keep.has(node.id)),
    edges: edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target)),
  };
}

export function flowGraph(flowId) {
  const flow = FLOWS.find((candidate) => candidate.id === flowId);
  if (!flow) return null;
  const types = new Set(flow.node_types);
  const kinds = new Set(flow.edge_types);
  const keptEdges = edges.filter((edge) => kinds.has(edge.type) && types.has(edge.source.split(':')[0]) && types.has(edge.target.split(':')[0]));
  const ids = new Set(keptEdges.flatMap((edge) => [edge.source, edge.target]));
  return { nodes: nodes.filter((node) => ids.has(node.id)), edges: keptEdges };
}

// Each entity is { id, label } plus the type's display properties (null when a record has none), as the backend returns it.
export function entities(type, limit) {
  const display = TYPE_BY_KEY[type]?.display_properties ?? [];
  return {
    type,
    entities: (byType[type] ?? []).slice(0, limit).map((node) => ({
      id: node.id.split(':')[1],
      label: node.label,
      ...Object.fromEntries(display.map((key) => [key, node.properties[key] ?? null])),
    })),
  };
}

export const SAMPLE_IDS = {
  customer: byType.Customer[0].id.split(':')[1],
  salesOrder: byType.SalesOrder[0].id.split(':')[1],
  invoice: byType.Invoice[0].id.split(':')[1],
};

// ── Chat ───────────────────────────────────────────────────
export function chatReply(message) {
  const text = message.toLowerCase();
  if (/poem|weather|joke|recipe/.test(text)) {
    return {
      answer: 'This system is designed to answer questions about the loaded dataset only. Please ask about customers, orders, deliveries, invoices, payments or products.',
      sql: null,
      data: null,
      entities: [],
      graph_nodes: [],
      error: 'guardrail',
      row_count: 0,
      summary: '',
    };
  }
  const topCustomers = byType.Customer.map((customer) => {
    const orders = edges.filter((edge) => edge.type === 'PLACED' && edge.source === customer.id).length;
    return { customer: customer.id.split(':')[1], name: customer.properties.business_partner_full_name, sales_orders: orders, total_net_amount: (orders * 1840.25).toFixed(2) };
  }).sort((a, b) => b.sales_orders - a.sales_orders);
  return {
    answer: `**${topCustomers[0].name}** has the most sales orders with **${topCustomers[0].sales_orders}**, followed by ${topCustomers[1].name} (${topCustomers[1].sales_orders}) and ${topCustomers[2].name} (${topCustomers[2].sales_orders}).\n\nTogether the four customers placed ${topCustomers.reduce((sum, row) => sum + row.sales_orders, 0)} orders in the sample.`,
    sql: 'SELECT c.business_partner AS customer,\n       c.business_partner_name AS name,\n       COUNT(DISTINCT so.sales_order) AS sales_orders\nFROM business_partners c\nJOIN sales_order_headers so ON so.sold_to_party = c.business_partner\nGROUP BY c.business_partner, c.business_partner_name\nORDER BY sales_orders DESC\nLIMIT 10;',
    data: topCustomers,
    entities: [],
    graph_nodes: topCustomers.slice(0, 3).map((row) => ({ id: `Customer:${row.customer}`, type: 'Customer', label: row.customer })),
    error: null,
    row_count: topCustomers.length,
    summary: 'Customers ranked by number of sales orders.',
  };
}
