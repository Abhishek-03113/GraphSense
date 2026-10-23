import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import {
  ChatResponseSchema,
  EntityListSchema,
  FlowListSchema,
  GraphDataSchema,
  HealthSchema,
  IngestResponseSchema,
  SchemaPayloadSchema,
  SummarySchema,
} from './schemas';

export const queryKeys = {
  health: ['health'] as const,
  summary: ['summary'] as const,
  schema: ['schema'] as const,
  flows: ['flows'] as const,
  full: (nodeLimit: number) => ['graph', 'full', nodeLimit] as const,
  subgraph: (type: string, id: string, depth: number) => ['graph', 'subgraph', type, id, depth] as const,
  flow: (flowId: string, limit: number) => ['graph', 'flow', flowId, limit] as const,
  entities: (type: string, limit: number) => ['entities', type, limit] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => apiGet('/health', HealthSchema, undefined, signal),
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: ({ signal }) => apiGet('/graph/summary', SummarySchema, undefined, signal),
  });
}

/** Dataset description. Missing on older servers, so a failure here is expected and not retried. */
export function useSchemaPayload() {
  return useQuery({
    queryKey: queryKeys.schema,
    queryFn: ({ signal }) => apiGet('/graph/schema', SchemaPayloadSchema, undefined, signal),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useFlowList() {
  return useQuery({
    queryKey: queryKeys.flows,
    queryFn: ({ signal }) => apiGet('/graph/flows', FlowListSchema, undefined, signal),
    staleTime: 5 * 60_000,
  });
}

export function useFullGraph(nodeLimit: number) {
  return useQuery({
    queryKey: queryKeys.full(nodeLimit),
    queryFn: ({ signal }) => apiGet('/graph/full', GraphDataSchema, { node_limit: nodeLimit }, signal),
    placeholderData: keepPreviousData,
  });
}

/** Query options for one record's neighbourhood. Shared so every screen hits the same cache entry. */
export function subgraphOptions(type: string | null | undefined, id: string | null | undefined, depth = 1) {
  return queryOptions({
    queryKey: queryKeys.subgraph(type ?? '', id ?? '', depth),
    queryFn: ({ signal }) =>
      apiGet('/graph/subgraph', GraphDataSchema, { root_type: type, root_id: id, depth }, signal),
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
    queryFn: ({ signal }) =>
      apiGet('/graph/trace', GraphDataSchema, { doc_type: type, doc_id: id, depth }, signal),
    enabled: Boolean(type && id),
    staleTime: 60_000,
  });
}

export function useFlowGraph(flowId: string | undefined, limit: number) {
  return useQuery({
    queryKey: queryKeys.flow(flowId ?? '', limit),
    queryFn: ({ signal }) => apiGet('/graph/flow', GraphDataSchema, { flow_id: flowId, limit }, signal),
    enabled: Boolean(flowId),
    placeholderData: keepPreviousData,
  });
}

export function useEntities(type: string | undefined, limit = 100) {
  return useQuery({
    queryKey: queryKeys.entities(type ?? '', limit),
    queryFn: ({ signal }) =>
      apiGet(`/graph/entities/${encodeURIComponent(type ?? '')}`, EntityListSchema, { limit }, signal),
    enabled: Boolean(type),
    staleTime: 60_000,
  });
}

export function useIngest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dataDir?: string) =>
      apiPost('/ingest', IngestResponseSchema, dataDir ? { data_dir: dataDir } : {}),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.summary });
    },
  });
}

export const sendChatMessage = (message: string, signal?: AbortSignal) =>
  apiPost('/chat', ChatResponseSchema, { message }, signal);
