import type { GraphData, GraphSummary, GraphEntity, FlowListResponse } from '../types/graph';

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
  },

  getFlows: async (): Promise<FlowListResponse> => {
    const response = await fetch(`${API_BASE_URL}/flows`);
    if (!response.ok) throw new Error(`Failed to fetch flows: ${response.statusText}`);
    return response.json();
  },

  getFlow: async (flowId: string, limit = 50): Promise<GraphData> => {
    const params = new URLSearchParams({ flow_id: flowId, limit: limit.toString() });
    const response = await fetch(`${API_BASE_URL}/flow?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch flow: ${response.statusText}`);
    }
    return response.json();
  },

  getTrace: async (docType: string, docId: string, depth = 4): Promise<GraphData> => {
    const params = new URLSearchParams({ doc_type: docType, doc_id: docId, depth: depth.toString() });
    const response = await fetch(`${API_BASE_URL}/trace?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to trace document: ${response.statusText}`);
    }
    return response.json();
  },

  getFullGraph: async (nodeLimit = 20, typeFilter?: string[]): Promise<GraphData> => {
    const params = new URLSearchParams({ node_limit: nodeLimit.toString() });
    if (typeFilter && typeFilter.length > 0) params.set('type_filter', typeFilter.join(','));
    const response = await fetch(`${API_BASE_URL}/full?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch full graph: ${response.statusText}`);
    }
    return response.json();
  },
};
