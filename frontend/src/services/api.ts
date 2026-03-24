import type { GraphData, GraphSummary, GraphEntity, FlowListResponse } from '../types/graph';

const API_BASE_URL = 'http://localhost:8000/api/graph';

const logResponse = (endpoint: string, data: unknown): void => {
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.nodes) && Array.isArray(d.edges)) {
      console.log(`[API] ${endpoint} → nodes=${(d.nodes as unknown[]).length} edges=${(d.edges as unknown[]).length}`);
    } else {
      console.log(`[API] ${endpoint} →`, data);
    }
  }
};

export const api = {
  getGraphSummary: async (): Promise<GraphSummary> => {
    console.log('[API] GET /summary');
    const response = await fetch(`${API_BASE_URL}/summary`);
    if (!response.ok) {
      console.error('[API] /summary FAILED:', response.status, response.statusText);
      throw new Error(`Failed to fetch graph summary: ${response.statusText}`);
    }
    const data = await response.json();
    logResponse('/summary', data);
    return data;
  },

  getSubgraph: async (rootType: string, rootId: string, depth: number = 2): Promise<GraphData> => {
    const params = new URLSearchParams({
      root_type: rootType,
      root_id: rootId,
      depth: depth.toString(),
    });

    console.log(`[API] GET /subgraph root=${rootType}:${rootId} depth=${depth}`);
    const response = await fetch(`${API_BASE_URL}/subgraph?${params.toString()}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      console.error('[API] /subgraph FAILED:', response.status, errorData);
      throw new Error(errorData.detail || `Failed to fetch subgraph: ${response.statusText}`);
    }
    const data = await response.json();
    logResponse('/subgraph', data);
    return data;
  },

  getEntities: async (nodeType: string, limit: number = 50): Promise<GraphEntity> => {
    console.log(`[API] GET /entities/${nodeType} limit=${limit}`);
    const response = await fetch(`${API_BASE_URL}/entities/${nodeType}?limit=${limit}`);
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      console.error(`[API] /entities/${nodeType} FAILED:`, response.status, errorData);
      throw new Error(errorData.detail || `Failed to fetch entities for ${nodeType}`);
    }
    const data = await response.json();
    console.log(`[API] /entities/${nodeType} → ${data.entities?.length ?? 0} entities`);
    return data;
  },

  getNodeDetails: async (_type: string, id: string): Promise<Record<string, unknown>> => {
    const params = new URLSearchParams({
      root_type: _type,
      root_id: id,
      depth: '0',
    });
    console.log(`[API] GET /subgraph (nodeDetails) type=${_type} id=${id}`);
    const response = await fetch(`${API_BASE_URL}/subgraph?${params.toString()}`);
    if (!response.ok) return {};
    const data = await response.json();
    return data.nodes?.[0]?.properties || {};
  },

  getFlows: async (): Promise<FlowListResponse> => {
    console.log('[API] GET /flows');
    const response = await fetch(`${API_BASE_URL}/flows`);
    if (!response.ok) {
      console.error('[API] /flows FAILED:', response.status, response.statusText);
      throw new Error(`Failed to fetch flows: ${response.statusText}`);
    }
    const data = await response.json();
    console.log(`[API] /flows → ${data.flows?.length ?? 0} flows`);
    return data;
  },

  getFlow: async (flowId: string, limit = 50): Promise<GraphData> => {
    const params = new URLSearchParams({ flow_id: flowId, limit: limit.toString() });
    console.log(`[API] GET /flow flowId=${flowId} limit=${limit}`);
    const response = await fetch(`${API_BASE_URL}/flow?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      console.error(`[API] /flow FAILED:`, response.status, err);
      throw new Error(err.detail || `Failed to fetch flow: ${response.statusText}`);
    }
    const data = await response.json();
    logResponse(`/flow?flow_id=${flowId}`, data);
    return data;
  },

  getTrace: async (docType: string, docId: string, depth = 4): Promise<GraphData> => {
    const params = new URLSearchParams({ doc_type: docType, doc_id: docId, depth: depth.toString() });
    console.log(`[API] GET /trace docType=${docType} docId=${docId} depth=${depth}`);
    const response = await fetch(`${API_BASE_URL}/trace?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      console.error('[API] /trace FAILED:', response.status, err);
      throw new Error(err.detail || `Failed to trace document: ${response.statusText}`);
    }
    const data = await response.json();
    logResponse('/trace', data);
    return data;
  },

  getFullGraph: async (nodeLimit = 20, typeFilter?: string[]): Promise<GraphData> => {
    const params = new URLSearchParams({ node_limit: nodeLimit.toString() });
    if (typeFilter && typeFilter.length > 0) params.set('type_filter', typeFilter.join(','));
    console.log(`[API] GET /full nodeLimit=${nodeLimit} typeFilter=${typeFilter}`);
    const response = await fetch(`${API_BASE_URL}/full?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      console.error('[API] /full FAILED:', response.status, err);
      throw new Error(err.detail || `Failed to fetch full graph: ${response.statusText}`);
    }
    const data = await response.json();
    logResponse('/full', data);
    return data;
  },
};
