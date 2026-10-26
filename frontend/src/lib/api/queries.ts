import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import {
  ChatResponseSchema,
  EntityListSchema,
  FlowListSchema,
  GraphDataSchema,
  DatasetStatusSchema,
  HealthSchema,
  SchemaPayloadSchema,
  SuggestedQuestionsSchema,
  SummarySchema,
} from './schemas';

// Query functions deliberately ignore TanStack's abort `signal`. Using it makes the query cancel its fetch when
// the last component reading it unmounts (StrictMode's double mount, a quick route change), and the next mount
// sends the same request again. The server finishes the work either way, so aborting only throws the answer away.
// Without the signal, a remount picks up the request already in flight.
export const queryKeys = {
  health: ['health'] as const,
  summary: ['summary'] as const,
  schema: ['schema'] as const,
  flows: ['flows'] as const,
  full: (nodeLimit: number) => ['graph', 'full', nodeLimit] as const,
  subgraph: (type: string, id: string, depth: number) => ['graph', 'subgraph', type, id, depth] as const,
  flow: (flowId: string, limit: number) => ['graph', 'flow', flowId, limit] as const,
  entities: (type: string, limit: number) => ['entities', type, limit] as const,
  datasetStatus: (datasetId: string) => ['dataset', datasetId, 'status'] as const,
  suggestedQuestions: (datasetId: string) => ['dataset', datasetId, 'suggested-questions'] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => apiGet('/health', HealthSchema),
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: () => apiGet('/graph/summary', SummarySchema),
  });
}

/** Dataset description. Missing on older servers, so a failure here is expected and not retried. */
export function useSchemaPayload() {
  return useQuery({
    queryKey: queryKeys.schema,
    queryFn: () => apiGet('/graph/schema', SchemaPayloadSchema),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useFlowList() {
  return useQuery({
    queryKey: queryKeys.flows,
    queryFn: () => apiGet('/graph/flows', FlowListSchema),
    staleTime: 5 * 60_000,
  });
}

export function useFullGraph(nodeLimit: number) {
  return useQuery({
    queryKey: queryKeys.full(nodeLimit),
    queryFn: () => apiGet('/graph/samples', GraphDataSchema, { node_limit: nodeLimit }),
    placeholderData: keepPreviousData,
  });
}

/** Query options for one record's neighbourhood. Shared so every screen hits the same cache entry. */
export function subgraphOptions(type: string | null | undefined, id: string | null | undefined, depth = 1) {
  return queryOptions({
    queryKey: queryKeys.subgraph(type ?? '', id ?? '', depth),
    queryFn: () =>
      apiGet('/graph/subgraphs', GraphDataSchema, { root_type: type, root_id: id, depth }),
    enabled: Boolean(type && id),
    staleTime: 60_000,
  });
}

export function useSubgraph(type: string | null | undefined, id: string | null | undefined, depth = 1) {
  return useQuery(subgraphOptions(type, id, depth));
}

export function useTraceGraph(type: string | null | undefined, id: string | null | undefined, depth = 4) {
  return useQuery({
    queryKey: ['graph', 'trace', type ?? '', id ?? '', depth],
    queryFn: () =>
      apiGet('/graph/traces', GraphDataSchema, { doc_type: type, doc_id: id, depth }),
    enabled: Boolean(type && id),
    staleTime: 60_000,
  });
}

export function useFlowGraph(flowId: string | undefined, limit: number) {
  return useQuery({
    queryKey: queryKeys.flow(flowId ?? '', limit),
    queryFn: () => apiGet(`/graph/flows/${encodeURIComponent(flowId ?? '')}/subgraph`, GraphDataSchema, { limit }),
    enabled: Boolean(flowId),
    placeholderData: keepPreviousData,
  });
}

export function useEntities(type: string | undefined, limit = 100) {
  return useQuery({
    queryKey: queryKeys.entities(type ?? '', limit),
    queryFn: () =>
      apiGet(`/graph/node-types/${encodeURIComponent(type ?? '')}/entities`, EntityListSchema, { limit }),
    enabled: Boolean(type),
    staleTime: 60_000,
  });
}

/** How often to look again while a dataset is not ready, in milliseconds. */
export const STATUS_POLL_LOADING_MS = 3000;
export const STATUS_POLL_WAITING_MS = 15_000;

/**
 * Load state of a dataset and what the AI layer can do for it. Polls while a load is running (and,
 * more slowly, while nothing is loaded yet) so the screen updates by itself. Older servers do not
 * have this endpoint; the failure is expected and not retried.
 */
export function useDatasetStatus(datasetId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.datasetStatus(datasetId ?? ''),
    queryFn: () => apiGet(`/datasets/${encodeURIComponent(datasetId ?? '')}/status`, DatasetStatusSchema),
    enabled: Boolean(datasetId),
    retry: false,
    staleTime: 20_000,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === 'loading') return STATUS_POLL_LOADING_MS;
      if (status === 'empty' || status === 'failed') return STATUS_POLL_WAITING_MS;
      return false;
    },
  });
}

/** Starter questions written for the dataset. Older servers do not have them, so a failure is quiet. */
export function useSuggestedQuestions(datasetId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.suggestedQuestions(datasetId ?? ''),
    queryFn: () =>
      apiGet(`/datasets/${encodeURIComponent(datasetId ?? '')}/suggested-questions`, SuggestedQuestionsSchema),
    enabled: Boolean(datasetId) && enabled,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export const sendChatMessage = (message: string, signal?: AbortSignal) =>
  apiPost('/chat/messages', ChatResponseSchema, { message }, signal);
