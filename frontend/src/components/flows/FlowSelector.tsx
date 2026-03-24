import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../services/api';
import type { FlowDefinition } from '../../types/graph';

const FLOW_ICONS: Record<string, string> = {
  sales: '🛒',
  fulfillment: '📦',
  billing: '🧾',
  financial: '💰',
  full_o2c: '🔄',
};

const FLOW_COLORS: Record<string, string> = {
  sales: '#79c0ff',
  fulfillment: '#d2a8ff',
  billing: '#ffa657',
  financial: '#7ee787',
  full_o2c: '#58a6ff',
};

interface FlowSelectorProps {
  onSelectFlow: (flow: FlowDefinition) => void;
  onBack: () => void;
}

export const FlowSelector: React.FC<FlowSelectorProps> = ({ onSelectFlow, onBack }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['flows'],
    queryFn: () => api.getFlows(),
  });

  return (
    <div style={{ padding: '3rem', maxWidth: '900px', margin: '0 auto', color: 'var(--text-primary)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <button
          onClick={onBack}
          style={{
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 1rem',
            borderRadius: '8px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          ← Back
        </button>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.8rem' }}>O2C Process Flows</h2>
          <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Select a predefined flow to visualize the process graph
          </p>
        </div>
      </div>

      {isLoading && (
        <div style={{ color: 'var(--text-secondary)', textAlign: 'center', paddingTop: '4rem' }}>
          Loading flows...
        </div>
      )}

      {error && (
        <div style={{ color: '#f85149', textAlign: 'center', paddingTop: '4rem' }}>
          Failed to load flows. Is the backend running?
        </div>
      )}

      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1.25rem' }}>
          {data.flows.map((flow) => {
            const color = FLOW_COLORS[flow.id] || '#8b949e';
            const icon = FLOW_ICONS[flow.id] || '→';
            return (
              <button
                key={flow.id}
                onClick={() => onSelectFlow(flow)}
                style={{
                  background: 'var(--bg-secondary)',
                  border: `1px solid var(--border-color)`,
                  borderRadius: '12px',
                  padding: '1.5rem',
                  textAlign: 'left',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.75rem',
                  width: '100%',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.borderColor = color;
                  (e.currentTarget as HTMLElement).style.background = `${color}18`;
                  (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-color)';
                  (e.currentTarget as HTMLElement).style.background = 'var(--bg-secondary)';
                  (e.currentTarget as HTMLElement).style.transform = 'translateY(0)';
                }}
              >
                <div style={{ fontSize: '2rem' }}>{icon}</div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '1.1rem', color, marginBottom: '0.35rem' }}>
                    {flow.label}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.5 }}>
                    {flow.description}
                  </div>
                </div>
                <div style={{ marginTop: 'auto', display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                  {flow.node_types.map((nt) => (
                    <span
                      key={nt}
                      style={{
                        fontSize: '0.72rem',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '999px',
                        background: `${color}22`,
                        color,
                        border: `1px solid ${color}44`,
                        fontWeight: 600,
                      }}
                    >
                      {nt}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
