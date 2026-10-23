import { z } from 'zod';

/** Runtime validation for every API response the UI reads. */

export const PropertiesSchema = z.record(z.string(), z.unknown());

export const GraphNodeSchema = z.object({
  id: z.string(),
  type: z.string(),
  label: z.string().nullish(),
  properties: PropertiesSchema.nullish().transform((value) => value ?? {}),
});

export const GraphEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  type: z.string(),
  properties: PropertiesSchema.nullish().transform((value) => value ?? {}),
});

export const GraphDataSchema = z.object({
  nodes: z.array(GraphNodeSchema),
  edges: z.array(GraphEdgeSchema),
});

export const SummarySchema = z.object({
  nodes: z.record(z.string(), z.number()),
  edges: z.record(z.string(), z.number()),
});

export const EntityListSchema = z.object({
  type: z.string(),
  entities: z.array(z.record(z.string(), z.unknown())),
});

export const FlowSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string().nullish(),
  node_types: z.array(z.string()).default([]),
  edge_types: z.array(z.string()).default([]),
});

export const FlowListSchema = z.object({ flows: z.array(FlowSchema) });

export const HealthSchema = z.object({ status: z.string() });

/* ── Dataset schema (GET /api/graph/schema) ─────────────────
 * Only `key` is guaranteed. Everything else is optional and the UI
 * falls back to sensible defaults when a field is missing. */

export const NodeTypeSchema = z.object({
  key: z.string(),
  label: z.string().nullish(),
  plural: z.string().nullish(),
  description: z.string().nullish(),
  category: z.string().nullish(),
  accent: z.string().nullish(),
  icon: z.string().nullish(),
  is_primary: z.boolean().nullish(),
  display_properties: z.array(z.string()).nullish(),
  /** Coded properties: property → { code → label }. Absent on older servers. */
  value_labels: z.record(z.string(), z.record(z.string(), z.string())).nullish(),
});

export const EdgeTypeSchema = z.object({
  key: z.string(),
  label: z.string().nullish(),
  source: z.string().nullish(),
  target: z.string().nullish(),
  description: z.string().nullish(),
});

export const SchemaPayloadSchema = z.object({
  domain: z
    .object({
      id: z.string().nullish(),
      name: z.string().nullish(),
      description: z.string().nullish(),
      version: z.string().nullish(),
      /** True only for a placeholder domain that has no name of its own. */
      is_default: z.boolean().nullish(),
    })
    .nullish(),
  node_types: z.array(NodeTypeSchema).default([]),
  edge_types: z.array(EdgeTypeSchema).default([]),
  flows: z.array(FlowSchema).default([]),
});

/* ── Conversational query (POST /api/chat) ───────────────── */

const stringList = z
  .array(z.string())
  .nullish()
  .transform((value) => value ?? []);

export const ChatColumnSchema = z.object({
  name: z.string(),
  label: z.string().nullish(),
  role: z.string().nullish(),
  /** Coded values of this column: code → label. */
  value_labels: z.record(z.string(), z.string()).nullish(),
});

export const ChatResponseSchema = z.object({
  answer: z.string().default(''),
  sql: z.string().nullish(),
  data: z.array(z.record(z.string(), z.unknown())).nullish(),
  entities: z
    .array(z.object({ id: z.string(), type: z.string(), value: z.string().optional() }).passthrough())
    .nullish()
    .transform((value) => value ?? []),
  graph_nodes: z
    .array(z.object({ id: z.string(), type: z.string(), label: z.string().nullish() }))
    .nullish()
    .transform((value) => value ?? []),
  error: z.string().nullish(),
  row_count: z.number().nullish(),
  summary: z.string().nullish(),
  // Additive fields: absent on older servers.
  query_id: z.string().nullish(),
  /** full | degraded | disabled */
  mode: z.string().nullish(),
  columns: z
    .array(ChatColumnSchema)
    .nullish()
    .transform((value) => value ?? []),
  /** True when the server cut the result off at its row limit. */
  truncated: z.boolean().nullish(),
  warnings: stringList,
  assumptions: stringList,
  suggestions: stringList,
});

/* ── Dataset status (GET /api/datasets/{id}/status) ─────────
 * Read-only and safe for every client. `status` is one of
 * empty | loading | ready | failed | legacy; unknown values are kept as text. */

export const AiStatusSchema = z.object({
  /** full | degraded | disabled */
  mode: z.string().nullish(),
  llm_configured: z.boolean().nullish(),
  embeddings_configured: z.boolean().nullish(),
  knowledge: z
    .object({
      /** ready | stale | missing */
      state: z.string().nullish(),
      items: z.number().nullish(),
      embed_model: z.string().nullish(),
      last_refresh: z.string().nullish(),
    })
    .nullish(),
});

export const DatasetStatusSchema = z.object({
  id: z.string(),
  name: z.string().nullish(),
  status: z.string(),
  package_version: z.string().nullish(),
  last_run: z
    .object({
      id: z.string().nullish(),
      kind: z.string().nullish(),
      status: z.string().nullish(),
      phase: z.string().nullish(),
      started_at: z.string().nullish(),
      finished_at: z.string().nullish(),
    })
    .nullish(),
  ai: AiStatusSchema.nullish(),
  record_counts: z.record(z.string(), z.number()).nullish(),
});

/* ── Suggested questions (GET /api/datasets/{id}/suggested-questions) ── */

export const SuggestedQuestionsSchema = z.object({
  dataset_id: z.string().nullish(),
  questions: z
    .array(z.object({ text: z.string(), category: z.string().nullish() }))
    .nullish()
    .transform((value) => value ?? []),
});

export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphEdge = z.infer<typeof GraphEdgeSchema>;
export type GraphData = z.infer<typeof GraphDataSchema>;
export type Summary = z.infer<typeof SummarySchema>;
export type EntityList = z.infer<typeof EntityListSchema>;
export type FlowPayload = z.infer<typeof FlowSchema>;
export type SchemaPayload = z.infer<typeof SchemaPayloadSchema>;
export type ChatResponse = z.infer<typeof ChatResponseSchema>;
export type ChatColumn = z.infer<typeof ChatColumnSchema>;
export type DatasetStatus = z.infer<typeof DatasetStatusSchema>;
export type AiStatus = z.infer<typeof AiStatusSchema>;
export type SuggestedQuestions = z.infer<typeof SuggestedQuestionsSchema>;
