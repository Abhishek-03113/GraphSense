import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../services/api';
import { GraphExplorer } from '../graph/GraphExplorer';
import { InspectorPanel } from '../graph/InspectorPanel';
import { FlowSelector } from './FlowSelector';
import { useGraphStore } from '../../store/useGraphStore';
import type { FlowDefinition } from '../../types/graph';

interface FlowExplorerProps {
  onBack: () => void;
}

export const FlowExplorer: React.FC<FlowExplorerProps> = ({ onBack }) => {
  const [selectedFlow, setSelectedFlow] = useState<FlowDefinition | null>(null);
  const { setLayoutMode } = useGraphStore();

  const { data: graphData, isLoading, error } = useQuery({
    queryKey: ['flow', selectedFlow?.id],
    queryFn: () => api.getFlow(selectedFlow!.id),
    enabled: !!selectedFlow,
  });

  const handleSelectFlow = (flow: FlowDefinition) => {
    setSelectedFlow(flow);
    // Dagre hierarchy layout works best for left-to-right process flows
    setLayoutMode('dagre');
  };

  if (!selectedFlow) {
    return <FlowSelector onSelectFlow={handleSelectFlow} onBack={onBack} />;
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex' }}>
      {/* Top bar */}
      <div style={{
        position: 'absolute', top: '1.5rem', left: '1.5rem', zIndex: 1000,
        display: 'flex', gap: '1rem', alignItems: 'center'
      }}>
        <button
          onClick={() => setSelectedFlow(null)}
          style={{
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-color)',
            padding: '0.6rem 1.2rem',
            borderRadius: '8px',
            cursor: 'pointer',
            fontWeight: 600,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          }}
        >
          ← Flows
        </button>
        <button
          onClick={onBack}
          style={{
            background: 'transparent',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border-color)',
            padding: '0.6rem 1.2rem',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '0.875rem',
          }}
        >
          Dashboard
        </button>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Flow:{' '}
          <span style={{ color: 'var(--accent-color)', fontWeight: 600 }}>
            {selectedFlow.label}
          </span>
        </div>
      </div>

      {isLoading && (
        <div className="loading-screen">Loading {selectedFlow.label}...</div>
      )}

      {error && (
        <div className="error-screen">
          <h3>Failed to Load Flow</h3>
          <p>{(error as Error).message}</p>
          <button onClick={() => setSelectedFlow(null)}>Back to Flows</button>
        </div>
      )}

      {graphData && !isLoading && graphData.nodes.length > 0 && (
        <>
          <GraphExplorer data={graphData} />
          <InspectorPanel />
        </>
      )}

      {graphData && !isLoading && graphData.nodes.length === 0 && (
        <div className="empty-state">
          <h3>No Data</h3>
          <p>The flow &ldquo;{selectedFlow.label}&rdquo; returned no nodes. Data may not be ingested yet.</p>
        </div>
      )}

      {!graphData && !isLoading && !error && selectedFlow && (
        <div className="empty-state">
          <h3>Waiting for data&hellip;</h3>
          <p>If this persists, check the browser console for API errors.</p>
        </div>
      )}
    </div>
  );
};
