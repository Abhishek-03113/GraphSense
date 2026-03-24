import React from 'react';
import { useGraphStore } from '../../store/useGraphStore';

const ALL_NODE_TYPES = [
  'Customer', 'SalesOrder', 'SalesOrderItem',
  'Delivery', 'DeliveryItem',
  'Invoice', 'InvoiceItem',
  'JournalEntry', 'Payment',
  'Product', 'Address',
];

const NODE_TYPE_COLORS: Record<string, string> = {
  Customer: '#56d364',
  SalesOrder: '#79c0ff',
  SalesOrderItem: '#4d9de0',
  Delivery: '#d2a8ff',
  DeliveryItem: '#a371f7',
  Invoice: '#ffa657',
  InvoiceItem: '#e07b2a',
  JournalEntry: '#f0883e',
  Payment: '#7ee787',
  Product: '#ff9580',
  Address: '#8b949e',
};

interface KnowledgeGraphControlsProps {
  onRefetch: () => void;
}

export const KnowledgeGraphControls: React.FC<KnowledgeGraphControlsProps> = ({ onRefetch }) => {
  const { typeFilter, nodeLimit, searchQuery, setTypeFilter, setNodeLimit, setSearchQuery } = useGraphStore();

  const toggleType = (type: string) => {
    const next = typeFilter.includes(type)
      ? typeFilter.filter((t) => t !== type)
      : [...typeFilter, type];
    setTypeFilter(next);
  };

  const activeTypes = typeFilter.length > 0 ? typeFilter : ALL_NODE_TYPES;

  return (
    <div style={{
      position: 'absolute',
      top: '1.5rem',
      right: '1.5rem',
      zIndex: 1000,
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-color)',
      borderRadius: '12px',
      padding: '1rem',
      width: '220px',
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.85rem',
    }}>
      <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
        Knowledge Graph
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="Search nodes..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        style={{
          padding: '0.45rem 0.7rem',
          background: 'var(--bg-primary)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          fontSize: '0.8rem',
          outline: 'none',
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--accent-color)'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border-color)'; }}
      />

      {/* Node limit slider */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Nodes per type</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--accent-color)', fontWeight: 600 }}>{nodeLimit}</span>
        </div>
        <input
          type="range"
          min={5}
          max={100}
          step={5}
          value={nodeLimit}
          onChange={(e) => setNodeLimit(Number(e.target.value))}
          style={{ width: '100%', cursor: 'pointer', accentColor: 'var(--accent-color)' }}
        />
      </div>

      {/* Type filter */}
      <div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          Entity types
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          {ALL_NODE_TYPES.map((type) => {
            const color = NODE_TYPE_COLORS[type] || '#8b949e';
            const isActive = typeFilter.length === 0 || typeFilter.includes(type);
            return (
              <button
                key={type}
                onClick={() => toggleType(type)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '0.2rem 0',
                  textAlign: 'left',
                  opacity: isActive ? 1 : 0.4,
                  transition: 'opacity 0.15s',
                }}
              >
                <span style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '50%',
                  background: color,
                  flexShrink: 0,
                }} />
                <span style={{ fontSize: '0.78rem', color: 'var(--text-primary)' }}>{type}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Refresh button */}
      <button
        onClick={onRefetch}
        style={{
          padding: '0.5rem',
          background: 'var(--accent-color)',
          color: '#0d1117',
          border: 'none',
          borderRadius: '6px',
          fontWeight: 700,
          fontSize: '0.8rem',
          cursor: 'pointer',
        }}
      >
        Apply & Refresh
      </button>

      <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
        {activeTypes.length} types · {nodeLimit}/type max
      </div>
    </div>
  );
};
