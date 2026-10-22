// Realistic order-to-cash style fixtures used by the screenshot script.
// They mirror the API contracts (summary, graph, flows, schema, entities, chat)
// so the whole UI can be exercised without a backend.

const TYPES = [
  { key: 'Customer', label: 'Customer', plural: 'Customers', description: 'A business that buys from you.', category: 'party', accent: 'blue', icon: 'users', is_primary: true, display_properties: ['name', 'country', 'credit_limit'] },
  { key: 'SalesOrder', label: 'Sales order', plural: 'Sales orders', description: 'A customer’s request to buy products.', category: 'document', accent: 'indigo', icon: 'file-text', is_primary: true, display_properties: ['creation_date', 'total_net_amount', 'transaction_currency'] },
  { key: 'Delivery', label: 'Delivery', plural: 'Deliveries', description: 'Goods shipped to a customer.', category: 'document', accent: 'teal', icon: 'truck', is_primary: true, display_properties: ['shipping_date', 'shipping_point'] },
  { key: 'Invoice', label: 'Invoice', plural: 'Invoices', description: 'A bill sent to a customer.', category: 'finance', accent: 'orange', icon: 'receipt', is_primary: true, display_properties: ['billing_date', 'total_net_amount', 'transaction_currency'] },
  { key: 'Payment', label: 'Payment', plural: 'Payments', description: 'Money received against an invoice.', category: 'finance', accent: 'green', icon: 'banknote', is_primary: true, display_properties: ['posting_date', 'amount', 'transaction_currency'] },
  { key: 'SalesOrderItem', label: 'Sales order item', plural: 'Sales order items', description: 'One product line on a sales order.', category: 'item', accent: 'purple', icon: null, is_primary: false, display_properties: ['quantity', 'net_amount'] },
  { key: 'DeliveryItem', label: 'Delivery item', plural: 'Delivery items', description: 'One product line on a delivery.', category: 'item', accent: 'cyan', icon: null, is_primary: false, display_properties: ['quantity'] },
  { key: 'InvoiceItem', label: 'Invoice item', plural: 'Invoice items', description: 'One product line on an invoice.', category: 'item', accent: 'yellow', icon: null, is_primary: false, display_properties: ['quantity', 'net_amount'] },
  { key: 'JournalEntry', label: 'Journal entry', plural: 'Journal entries', description: 'An accounting posting for an invoice or payment.', category: 'finance', accent: 'brown', icon: null, is_primary: false, display_properties: ['posting_date', 'amount'] },
  { key: 'Product', label: 'Product', plural: 'Products', description: 'Something you sell.', category: 'master', accent: 'pink', icon: 'package', is_primary: false, display_properties: ['description', 'product_group'] },
  // No accent supplied: exercises the stable-hash colour fallback.
  { key: 'Address', label: 'Address', plural: 'Addresses', description: 'Where a customer is located.', category: 'master', accent: null, icon: null, is_primary: false, display_properties: ['city', 'country'] },
];

const EDGES = [
  { key: 'PLACED', label: 'placed', source: 'Customer', target: 'SalesOrder', description: 'Customer placed the sales order.' },
  { key: 'HAS_ITEM', label: 'contains', source: 'SalesOrder', target: 'SalesOrderItem', description: 'Sales order contains the item.' },
  { key: 'HAS_ITEM', label: 'contains', source: 'Delivery', target: 'DeliveryItem', description: 'Delivery contains the item.' },
  { key: 'HAS_ITEM', label: 'contains', source: 'Invoice', target: 'InvoiceItem', description: 'Invoice contains the item.' },
  { key: 'INCLUDES', label: 'is for', source: 'SalesOrderItem', target: 'Product', description: 'Order line is for the product.' },
  { key: 'FULFILLS', label: 'fulfils', source: 'DeliveryItem', target: 'SalesOrderItem', description: 'Delivery line fulfils the order line.' },
  { key: 'BILLS_FOR', label: 'bills for', source: 'InvoiceItem', target: 'DeliveryItem', description: 'Invoice line bills for the delivery line.' },
  { key: 'BILLED_TO', label: 'is billed to', source: 'Invoice', target: 'Customer', description: 'Invoice is billed to the customer.' },
  { key: 'GENERATES', label: 'generates', source: 'Invoice', target: 'JournalEntry', description: 'Invoice posts the journal entry.' },
  { key: 'CLEARS', label: 'clears', source: 'Payment', target: 'JournalEntry', description: 'Payment clears the journal entry.' },
  { key: 'HAS_ADDRESS', label: 'is located at', source: 'Customer', target: 'Address', description: 'Customer is located at the address.' },
];

const FLOWS = [
  { id: 'sales', label: 'Sales flow', description: 'A customer places an order and its lines reference products.', node_types: ['Customer', 'SalesOrder', 'SalesOrderItem', 'Product'], edge_types: ['PLACED', 'HAS_ITEM', 'INCLUDES'] },
  { id: 'fulfillment', label: 'Fulfilment flow', description: 'Order lines are fulfilled by outbound deliveries.', node_types: ['SalesOrder', 'SalesOrderItem', 'Delivery', 'DeliveryItem', 'Product'], edge_types: ['HAS_ITEM', 'FULFILLS', 'INCLUDES'] },
  { id: 'billing', label: 'Billing flow', description: 'Deliveries are billed to customers through invoices.', node_types: ['Delivery', 'DeliveryItem', 'Invoice', 'InvoiceItem', 'Customer'], edge_types: ['HAS_ITEM', 'BILLS_FOR', 'BILLED_TO'] },
  { id: 'financial', label: 'Financial flow', description: 'Invoices post journal entries that payments then clear.', node_types: ['Invoice', 'JournalEntry', 'Payment', 'Customer'], edge_types: ['GENERATES', 'CLEARS', 'BILLED_TO'] },
  { id: 'customer_master', label: 'Customer profile', description: 'A customer together with its addresses.', node_types: ['Customer', 'Address'], edge_types: ['HAS_ADDRESS'] },
  { id: 'full_o2c', label: 'End to end', description: 'From customer order through delivery, invoice and payment.', node_types: ['Customer', 'Address', 'SalesOrder', 'SalesOrderItem', 'Delivery', 'DeliveryItem', 'Invoice', 'InvoiceItem', 'JournalEntry', 'Payment', 'Product'], edge_types: ['PLACED', 'HAS_ITEM', 'INCLUDES', 'FULFILLS', 'BILLS_FOR', 'BILLED_TO', 'GENERATES', 'CLEARS', 'HAS_ADDRESS'] },
];

export const SCHEMA = {
  domain: { id: 'o2c', name: 'Order to Cash', description: 'Sales orders through delivery, billing and payment, with the customers and products behind them.' },
  node_types: TYPES,
  edge_types: EDGES,
  flows: FLOWS,
};

// ── Records ────────────────────────────────────────────────
const nodes = [];
const edges = [];
const byType = {};

function addNode(type, value, properties = {}) {
  const node = { id: `${type}:${value}`, type, label: `${type} ${value}`, properties };
  nodes.push(node);
  (byType[type] ??= []).push(node);
  return node;
}
function link(type, from, to) {
  edges.push({ id: `${from.id}-${to.id}-${type}`, source: from.id, target: to.id, type, properties: {} });
}

const customerNames = ['Northwind Traders', 'Contoso Retail', 'Fabrikam Industries', 'Adventure Works'];
const countries = ['US', 'DE', 'GB', 'FR'];
const cities = ['Chicago', 'Munich', 'Leeds', 'Lyon'];
const products = [
  ['TG11', 'Trail running shoes', 'Footwear'],
  ['TG12', 'Waterproof jacket', 'Outerwear'],
  ['TG13', 'Merino base layer', 'Apparel'],
  ['TG14', 'Hydration pack', 'Equipment'],
  ['TG15', 'Trekking poles', 'Equipment'],
  ['TG16', 'Headlamp', 'Equipment'],
];

const customers = customerNames.map((name, index) =>
  addNode('Customer', `${1001 + index}`, { name, country: countries[index], credit_limit: 50000 + index * 25000, business_partner: `${1001 + index}` }),
);
const addresses = customers.map((customer, index) => {
  const address = addNode('Address', `${1001 + index}-1`, { city: cities[index], country: countries[index], street: `${10 + index} Market Street` });
  link('HAS_ADDRESS', customer, address);
  return address;
});
void addresses;
const productNodes = products.map(([code, description, group]) => addNode('Product', code, { description, product_group: group }));

let soNumber = 740500;
let diNumber = 80738000;
let invNumber = 90504200;
let jeNumber = 9400000;
const soItems = [];
const deliveries = [];
const invoices = [];

for (let index = 0; index < 8; index += 1) {
  const customer = customers[index % customers.length];
  const so = addNode('SalesOrder', `${(soNumber += 3)}`, {
    creation_date: `2025-0${1 + (index % 6)}-${10 + index}`,
    total_net_amount: `${(1200 + index * 345.5).toFixed(2)}`,
    transaction_currency: 'USD',
    sales_order_type: 'OR',
    delivery_status: index % 3 === 0 ? 'C' : 'A',
  });
  link('PLACED', customer, so);
  const lines = index % 2 === 0 ? 2 : 1;
  for (let line = 0; line < lines; line += 1) {
    const item = addNode('SalesOrderItem', `${so.id.split(':')[1]}-${(line + 1) * 10}`, {
      quantity: `${2 + line * 3}`,
      net_amount: `${(300 + index * 80 + line * 120).toFixed(2)}`,
    });
    link('HAS_ITEM', so, item);
    link('INCLUDES', item, productNodes[(index + line) % productNodes.length]);
    soItems.push({ so, item, customer });
  }
}

soItems.slice(0, 6).forEach(({ item, customer }, index) => {
  if (index % 2 === 0) {
    const delivery = addNode('Delivery', `${(diNumber += 2)}`, { shipping_date: `2025-02-${10 + index}`, shipping_point: 'N100' });
    deliveries.push({ delivery, customer });
    const deliveryItem = addNode('DeliveryItem', `${delivery.id.split(':')[1]}-10`, { quantity: '2' });
    link('HAS_ITEM', delivery, deliveryItem);
    link('FULFILLS', deliveryItem, item);
    deliveries[deliveries.length - 1].deliveryItem = deliveryItem;
  }
});

deliveries.slice(0, 3).forEach(({ delivery, customer, deliveryItem }, index) => {
  const invoice = addNode('Invoice', `${(invNumber += 1)}`, {
    billing_date: `2025-03-0${index + 2}`,
    total_net_amount: `${(980 + index * 210).toFixed(2)}`,
    transaction_currency: 'USD',
    billing_document_is_cancelled: false,
  });
  invoices.push(invoice);
  link('BILLED_TO', invoice, customer);
  const invoiceItem = addNode('InvoiceItem', `${invoice.id.split(':')[1]}-10`, { quantity: '2', net_amount: `${(980 + index * 210).toFixed(2)}` });
  link('HAS_ITEM', invoice, invoiceItem);
  link('BILLS_FOR', invoiceItem, deliveryItem);
  void delivery;
  const journal = addNode('JournalEntry', `${(jeNumber += 7)}`, { posting_date: `2025-03-0${index + 2}`, amount: `${(980 + index * 210).toFixed(2)}` });
  link('GENERATES', invoice, journal);
  if (index < 2) {
    const payment = addNode('Payment', `${(jeNumber += 3)}`, { posting_date: `2025-04-0${index + 1}`, amount: `${(980 + index * 210).toFixed(2)}`, transaction_currency: 'USD' });
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

export function entities(type, limit) {
  return { type, entities: (byType[type] ?? []).slice(0, limit).map((node) => ({ id: node.id.split(':')[1], label: node.label })) };
}

export const SAMPLE_IDS = {
  customer: '1001',
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
    return { customer: customer.id.split(':')[1], name: customer.properties.name, sales_orders: orders, total_net_amount: (orders * 1840.25).toFixed(2) };
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
