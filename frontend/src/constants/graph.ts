// Canonical node type → color map. Used by GraphExplorer, InspectorPanel,
// and KnowledgeGraphControls. Keep in one place to avoid drift.
export const NODE_TYPE_COLORS: Record<string, string> = {
  Customer:       '#56d364',
  SalesOrder:     '#79c0ff',
  SalesOrderItem: '#4d9de0',
  Delivery:       '#d2a8ff',
  DeliveryItem:   '#a371f7',
  Invoice:        '#ffa657',
  InvoiceItem:    '#e07b2a',
  JournalEntry:   '#f0883e',
  Payment:        '#7ee787',
  Product:        '#ff9580',
  Address:        '#8b949e',
};

export const ALL_NODE_TYPES = Object.keys(NODE_TYPE_COLORS);

export const DEFAULT_NODE_COLOR = '#8b949e';
