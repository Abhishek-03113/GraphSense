import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { api } from './services/api';
import { KnowledgeGraph } from './components/knowledge/KnowledgeGraph';
import './index.css';

const queryClient = new QueryClient();

function GraphApp() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['full-graph'],
    queryFn: () => api.getFullGraph(),
  });

  if (isLoading) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner" />
        <div className="loading-text">Loading graph</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-screen">
        <h3>Failed to load graph</h3>
        <p>{(error as Error).message}</p>
        <button onClick={() => refetch()}>Retry</button>
      </div>
    );
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="empty-state">
        <h3>No data</h3>
        <p>The knowledge graph is empty. Ingest data first.</p>
      </div>
    );
  }

  return <KnowledgeGraph data={data} />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <GraphApp />
    </QueryClientProvider>
  );
}

export default App;
