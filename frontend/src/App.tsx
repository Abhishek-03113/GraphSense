import { useState } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { api } from './services/api';
import { GraphExplorer } from './components/graph/GraphExplorer';
import { InspectorPanel } from './components/graph/InspectorPanel';
import { Dashboard } from './components/ui/Dashboard';
import { EntitySelector } from './components/ui/EntitySelector';
import { FlowExplorer } from './components/flows/FlowExplorer';
import { DocumentTracer } from './components/trace/DocumentTracer';
import { KnowledgeGraph } from './components/knowledge/KnowledgeGraph';
import './index.css';

const queryClient = new QueryClient();

function GraphDashboard() {
  const [view, setView] = useState<'dashboard' | 'selector' | 'graph' | 'flows' | 'trace' | 'knowledge-graph'>('dashboard');
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // 1. Fetch Summary for Dashboard
  const { data: summary, isLoading: loadingSummary } = useQuery({
    queryKey: ['summary'],
    queryFn: () => api.getGraphSummary(),
    enabled: view === 'dashboard',
  });

  // 2. Fetch Subgraph for Graph View
  const { data: graphData, isLoading: loadingGraph, error: graphError } = useQuery({
    queryKey: ['subgraph', selectedType, selectedId],
    queryFn: () => api.getSubgraph(selectedType!, selectedId!, 2),
    enabled: view === 'graph' && !!selectedType && !!selectedId,
  });

  const handleSelectType = (type: string) => {
    setSelectedType(type);
    setView('selector');
  };

  const handleSelectEntity = (type: string, id: string) => {
    setSelectedType(type);
    setSelectedId(id);
    setView('graph');
  };

  const handleBackToDashboard = () => {
    setSelectedType(null);
    setSelectedId(null);
    setView('dashboard');
  };

  if (view === 'flows') return <FlowExplorer onBack={handleBackToDashboard} />;
  if (view === 'trace') return <DocumentTracer onBack={handleBackToDashboard} />;
  if (view === 'knowledge-graph') return <KnowledgeGraph onBack={handleBackToDashboard} />;

  if (view === 'dashboard') {
    if (loadingSummary) return <div className="loading-screen">Loading dataset summary...</div>;
    return (
      <Dashboard
        summary={summary!}
        onSelectType={handleSelectType}
        onExploreFlows={() => setView('flows')}
        onTraceDocument={() => setView('trace')}
        onKnowledgeGraph={() => setView('knowledge-graph')}
      />
    );
  }

  if (view === 'selector') {
    return (
      <EntitySelector 
        selectedType={selectedType} 
        onSelectEntity={handleSelectEntity} 
        onBack={handleBackToDashboard} 
      />
    );
  }

  if (view === 'graph') {
    if (loadingGraph) return <div className="loading-screen">Traversing graph relationships...</div>;
    if (graphError) return (
      <div className="error-screen">
        <h3>Graph Traversal Failed</h3>
        <p>{(graphError as Error).message}</p>
        <button onClick={handleBackToDashboard}>Return to Dashboard</button>
      </div>
    );

    return (
      <>
        <div style={{ position: 'absolute', top: '1.5rem', left: '1.5rem', zIndex: 1000, display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <button 
            onClick={handleBackToDashboard}
            style={{ 
              background: 'var(--bg-secondary)', 
              color: 'var(--text-primary)', 
              border: '1px solid var(--border-color)',
              padding: '0.6rem 1.2rem',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)'
            }}
          >
            ← Dashboard
          </button>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Viewing: <span style={{ color: 'var(--accent-color)', fontWeight: 600 }}>{selectedType} {selectedId}</span>
          </div>
        </div>
        <GraphExplorer data={graphData!} />
        <InspectorPanel />
      </>
    );
  }

  return null;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <GraphDashboard />
    </QueryClientProvider>
  );
}

export default App;
