import type { GraphData } from '../types/graph';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export interface ChatApiResponse {
  answer: string;
  sql: string | null;
  data: Record<string, unknown>[] | null;
  entities: { id: string; type: string; value: string }[];
  error: string | null;
  row_count: number;
  summary: string;
}

export const api = {
  getFullGraph: async (): Promise<GraphData> => {
    const params = new URLSearchParams({ node_limit: '500' });
    const response = await fetch(`${API_BASE_URL}/graph/full?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch graph: ${response.statusText}`);
    }
    const data = await response.json();
    console.log(`[API] /full → ${data.nodes?.length ?? 0} nodes, ${data.edges?.length ?? 0} edges`);
    return data;
  },

  chat: async (message: string): Promise<ChatApiResponse> => {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Chat request failed: ${response.statusText}`);
    }
    return response.json();
  },
};
