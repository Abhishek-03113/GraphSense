import React, { useState, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../services/api';
import { GraphExplorer } from '../graph/GraphExplorer';
import { InspectorPanel } from '../graph/InspectorPanel';
import { KnowledgeGraphControls } from './KnowledgeGraphControls';
import { useGraphStore } from '../../store/useGraphStore';
import type { GraphData } from '../../types/graph';

interface KnowledgeGraphProps {
  onBack: () => void;
}

export const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({ onBack }) => {
  const { typeFilter, nodeLimit, searchQuery, setLayoutMode } = useGraphStore();
  const [fetchParams, setFetchParams] = useState({ nodeLimit, typeFilter: typeFilter.slice() });

  // Use cose-bilkent for the knowledge graph (force layout reveals clusters)
  useEffect(() => {
    setLayoutMode('cose-bilkent');
  }, [setLayoutMode]);

  const { data: rawData, isLoading, error, refetch } = useQuery({
    queryKey: ['full-graph', fetchParams.nodeLimit, fetchParams.typeFilter.join(',')],
    queryFn: () =>
      api.getFullGraph(
        fetchParams.nodeLimit,
        fetchParams.typeFilter.length > 0 ? fetchParams.typeFilter : undefined
      ),
  });

  const handleRefetch = useCallback(() => {
    setFetchParams({ nodeLimit, typeFilter: typeFilter.slice() });
    // refetch is triggered automatically because queryKey changed
  }, [nodeLimit, typeFilter]);

  // Client-side search filter: highlight matching nodes by filtering the graph data
  const graphData: GraphData | undefined = React.useMemo(() => {
    if (!rawData) return undefined;
    if (!searchQuery.trim()) return rawData;

    const q = searchQuery.toLowerCase();
    const matchingIds = new Set(
      rawData.nodes
        .filter((n) => n.id.toLowerCase().includes(q) || (n.label || '').toLowerCase().includes(q) || n.type.toLowerCase().includes(q))
        .map((n) => n.id)
    );

    // Keep all nodes but dim non-matches by injecting a property (used by GraphExplorer via class)
    // For simplicity: just filter to matching nodes + their directly connected neighbours
    const connectedIds = new Set<string>(matchingIds);
    rawData.edges.forEach((e) => {
      if (matchingIds.has(e.source)) connectedIds.add(e.target);
      if (matchingIds.has(e.target)) connectedIds.add(e.source);
    });

    const filteredNodes = rawData.nodes.filter((n) => connectedIds.has(n.id));
    const filteredEdges = rawData.edges.filter((e) => connectedIds.has(e.source) && connectedIds.has(e.target));
    return { nodes: filteredNodes, edges: filteredEdges };
  }, [rawData, searchQuery]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex' }}>
      {/* Top-left back button */}
      <div style={{
        position: 'absolute', top: '1.5rem', left: '1.5rem', zIndex: 1000,
        display: 'flex', gap: '1rem', alignItems: 'center',
      }}>
        <button
          onClick={onBack}
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
          ← Dashboard
        </button>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Knowledge Graph
          {graphData && (
            <span style={{ color: 'var(--accent-color)', marginLeft: '0.5rem' }}>
              · {graphData.nodes.length} nodes, {graphData.edges.length} edges
            </span>
          )}
        </div>
      </div>

      {/* Right-side controls panel */}
      <KnowledgeGraphControls onRefetch={handleRefetch} />

      {isLoading && <div className="loading-screen">Building knowledge graph...</div>}

      {error && (
        <div className="error-screen">
          <h3>Failed to Load Graph</h3>
          <p>{(error as Error).message}</p>
          <button onClick={() => refetch()}>Retry</button>
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
          <p>The knowledge graph returned no nodes. Data may not be ingested yet.</p>
        </div>
      )}

      {!graphData && !isLoading && !error && (
        <div className="empty-state">
          <h3>Waiting for data&hellip;</h3>
          <p>If this persists, check the browser console for API errors.</p>
        </div>
      )}
    </div>
  );
};
