import type { GraphData, GraphSummary, GraphEntity } from '../types/graph';

const API_BASE_URL = 'http://localhost:8000/api/graph';

export const api = {
  getGraphSummary: async (): Promise<GraphSummary> => {
    const response = await fetch(`${API_BASE_URL}/summary`);
    if (!response.ok) {
      throw new Error(`Failed to fetch graph summary: ${response.statusText}`);
    }
    return response.json();
  },
  
  getSubgraph: async (rootType: string, rootId: string, depth: number = 2): Promise<GraphData> => {
    const params = new URLSearchParams({
      root_type: rootType,
      root_id: rootId,
      depth: depth.toString(),
    });
    
    const response = await fetch(`${API_BASE_URL}/subgraph?${params.toString()}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to fetch subgraph: ${response.statusText}`);
    }
    return response.json();
  },

  getEntities: async (nodeType: string, limit: number = 50): Promise<GraphEntity> => {
    const response = await fetch(`${API_BASE_URL}/entities/${nodeType}?limit=${limit}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `Failed to fetch entities for ${nodeType}`);
    }
    return response.json();
  },

  getNodeDetails: async (_type: string, id: string): Promise<Record<string, unknown>> => {
    const params = new URLSearchParams({
      root_type: _type,
      root_id: id,
      depth: '0',
    });
    const response = await fetch(`${API_BASE_URL}/subgraph?${params.toString()}`);
    if (!response.ok) return {};
    const data = await response.json();
    return data.nodes?.[0]?.properties || {};
  }
};
