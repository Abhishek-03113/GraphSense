import React from 'react';
import { useGraphStore } from '../../store/useGraphStore';
import { NODE_TYPE_COLORS, DEFAULT_NODE_COLOR } from '../../constants/graph';
import { X, Info, Tag, Hash, Calendar } from 'lucide-react';

export const InspectorPanel: React.FC = () => {
  const { selectedNode, setSelectedNode, isInspectorOpen } = useGraphStore();

  if (!isInspectorOpen || !selectedNode) return null;

  const getIcon = (key: string) => {
    const k = key.toLowerCase();
    if (k.includes('date') || k.includes('time')) return <Calendar size={13} />;
    if (k.includes('amount') || k.includes('price')) return <Hash size={13} />;
    if (k.includes('type') || k.includes('category')) return <Tag size={13} />;
    return <Info size={13} />;
  };

  const headerColor = NODE_TYPE_COLORS[selectedNode.type] ?? DEFAULT_NODE_COLOR;

  return (
    <aside className="inspector-panel">
      <div
        className="panel-header"
        style={{ borderBottom: `2px solid ${headerColor}` }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div
              className="node-chip"
              style={{ backgroundColor: headerColor, color: '#0b0f18' }}
            >
              {selectedNode.type}
            </div>
            <h2 style={{ fontSize: '1.1rem', margin: '0.25rem 0 0', fontWeight: 600, letterSpacing: '-0.01em' }}>
              {selectedNode.label}
            </h2>
          </div>
          <button
            onClick={() => setSelectedNode(null)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '4px',
              borderRadius: '4px',
              transition: 'color 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--text-primary)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--text-muted)'; }}
          >
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="panel-content">
        <div className="property-group">
          <div className="property-label">Entity ID</div>
          <div className="property-value" style={{ color: 'var(--highlight)' }}>
            {selectedNode.id}
          </div>
        </div>

        {Object.entries(selectedNode.properties || {}).map(([key, value]) => (
          <div className="property-group" key={key}>
            <div className="property-label" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              {getIcon(key)}
              {key.replace(/([A-Z])/g, ' $1').toUpperCase()}
            </div>
            <div className="property-value">
              {typeof value === 'object' ? JSON.stringify(value) : String(value)}
            </div>
          </div>
        ))}

        {(!selectedNode.properties || Object.keys(selectedNode.properties).length === 0) && (
          <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '0.82rem' }}>
            No additional metadata available.
          </div>
        )}
      </div>
    </aside>
  );
};
