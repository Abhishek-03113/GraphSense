import React from 'react';
import { useGraphStore } from '../../store/useGraphStore';
import { NODE_TYPE_COLORS, DEFAULT_NODE_COLOR } from '../../constants/graph';
import { X, Info, Tag, Hash, Calendar } from 'lucide-react';

export const InspectorPanel: React.FC = () => {
  const { selectedNode, setSelectedNode, isInspectorOpen } = useGraphStore();

  if (!isInspectorOpen || !selectedNode) return null;

  const getIcon = (key: string) => {
    if (key.toLowerCase().includes('date') || key.toLowerCase().includes('time')) return <Calendar size={14} />;
    if (key.toLowerCase().includes('amount') || key.toLowerCase().includes('price')) return <Hash size={14} />;
    if (key.toLowerCase().includes('type') || key.toLowerCase().includes('category')) return <Tag size={14} />;
    return <Info size={14} />;
  };

  const headerColor = NODE_TYPE_COLORS[selectedNode.type] ?? DEFAULT_NODE_COLOR;

  return (
    <aside className="inspector-panel animate-fade-in">
      <div
        className="panel-header"
        style={{ borderBottom: `2px solid ${headerColor}` }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div
              className="node-chip"
              style={{ backgroundColor: headerColor, color: '#000' }}
            >
              {selectedNode.type}
            </div>
            <h2 style={{ fontSize: '1.25rem', margin: '0.25rem 0', fontWeight: 'bold' }}>
              {selectedNode.label}
            </h2>
          </div>
          <button
            onClick={() => setSelectedNode(null)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '4px',
            }}
          >
            <X size={20} />
          </button>
        </div>
      </div>

      <div className="panel-content">
        <div className="property-group">
          <div className="property-label">Entity ID</div>
          <div className="property-value" style={{ fontSize: '1rem', color: 'var(--accent-color)' }}>
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
          <div style={{ color: 'var(--text-secondary)', fontStyle: 'italic', fontSize: '0.9rem' }}>
            No additional metadata available for this node.
          </div>
        )}
      </div>
    </aside>
  );
};
