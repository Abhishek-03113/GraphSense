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
    })
    .nullish(),
  node_types: z.array(NodeTypeSchema).default([]),
  edge_types: z.array(EdgeTypeSchema).default([]),
  flows: z.array(FlowSchema).default([]),
});

/* ── Conversational query (POST /api/chat) ───────────────── */

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
});

export const IngestResponseSchema = z.object({ message: z.string().optional() }).passthrough();

export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphEdge = z.infer<typeof GraphEdgeSchema>;
export type GraphData = z.infer<typeof GraphDataSchema>;
export type Summary = z.infer<typeof SummarySchema>;
export type EntityList = z.infer<typeof EntityListSchema>;
export type FlowPayload = z.infer<typeof FlowSchema>;
export type SchemaPayload = z.infer<typeof SchemaPayloadSchema>;
export type ChatResponse = z.infer<typeof ChatResponseSchema>;
