import React, { useMemo } from 'react';
import { MessageCircle } from 'lucide-react';
import { GraphExplorer } from '../graph/GraphExplorer';
import { InspectorPanel } from '../graph/InspectorPanel';
import { ChatPanel } from '../chat/ChatPanel';
import { useGraphStore } from '../../store/useGraphStore';
import { NODE_TYPE_COLORS, DEFAULT_NODE_COLOR } from '../../constants/graph';
import type { GraphData } from '../../types/graph';

interface KnowledgeGraphProps {
  data: GraphData;
}

export const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({ data }) => {
  const { searchQuery, setSearchQuery, isChatOpen, setChatOpen } = useGraphStore();

  const graphData: GraphData = useMemo(() => {
    if (!searchQuery.trim()) return data;

    const q = searchQuery.toLowerCase();
    const matchingIds = new Set(
      data.nodes
        .filter(
          (n) =>
            n.id.toLowerCase().includes(q) ||
            (n.label || '').toLowerCase().includes(q) ||
            n.type.toLowerCase().includes(q),
        )
        .map((n) => n.id),
    );

    const connectedIds = new Set<string>(matchingIds);
    data.edges.forEach((e) => {
      if (matchingIds.has(e.source)) connectedIds.add(e.target);
      if (matchingIds.has(e.target)) connectedIds.add(e.source);
    });

    return {
      nodes: data.nodes.filter((n) => connectedIds.has(n.id)),
      edges: data.edges.filter((e) => connectedIds.has(e.source) && connectedIds.has(e.target)),
    };
  }, [data, searchQuery]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    graphData.nodes.forEach((n) => counts.set(n.type, (counts.get(n.type) || 0) + 1));
    return counts;
  }, [graphData]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex' }}>
      <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <div className="graph-header">
          <div className="graph-title">
            <h1>DodgeAI</h1>
            <span className="subtitle">Knowledge Graph</span>
          </div>
          <div className="graph-stats">
            <span><span className="stat-accent">{graphData.nodes.length}</span> nodes</span>
            <span className="stat-divider" />
            <span><span className="stat-accent">{graphData.edges.length}</span> edges</span>
          </div>
        </div>

        {/* Search */}
        <div className="search-container">
          <span className="search-icon">&#x2315;</span>
          <input
            className="search-input"
            type="text"
            placeholder="Search nodes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        {/* Graph */}
        {graphData.nodes.length > 0 ? (
          <GraphExplorer data={graphData} />
        ) : (
          <div className="empty-state">
            <h3>No matches</h3>
            <p>No nodes match "{searchQuery}"</p>
          </div>
        )}

        {/* Legend */}
        <div className="graph-legend">
          {Array.from(typeCounts.entries())
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <div key={type} className="legend-item">
                <span
                  className="legend-dot"
                  style={{ background: NODE_TYPE_COLORS[type] || DEFAULT_NODE_COLOR }}
                />
                {type} ({count})
              </div>
            ))}
        </div>

        {/* Chat toggle button */}
        {!isChatOpen && (
          <button
            className="chat-toggle-btn"
            onClick={() => setChatOpen(true)}
            title="Open Query Assistant"
            aria-label="Open chat"
          >
            <MessageCircle size={20} />
          </button>
        )}
      </div>

      {/* Chat Panel */}
      <ChatPanel isOpen={isChatOpen} onClose={() => setChatOpen(false)} />

      {/* Inspector Panel */}
      {!isChatOpen && <InspectorPanel />}
    </div>
  );
};
