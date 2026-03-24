import { z } from 'zod';

export const NodePropertySchema = z.record(z.string(), z.any());

export const GraphNodeSchema = z.object({
  id: z.string(),
  type: z.string(),
  label: z.string().optional(),
  properties: NodePropertySchema.default({}),
});

export const GraphEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  type: z.string(),
  properties: NodePropertySchema.default({}),
});

export const GraphDataSchema = z.object({
  nodes: z.array(GraphNodeSchema),
  edges: z.array(GraphEdgeSchema),
});

export const GraphSummarySchema = z.object({
  nodes: z.record(z.string(), z.number()),
  edges: z.record(z.string(), z.number()),
});

export const GraphEntitySchema = z.object({
  type: z.string(),
  entities: z.array(z.object({
    id: z.string(),
    label: z.string()
  })),
});

export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphEdge = z.infer<typeof GraphEdgeSchema>;
export type GraphData = z.infer<typeof GraphDataSchema>;
export type GraphSummary = z.infer<typeof GraphSummarySchema>;
export type GraphEntity = z.infer<typeof GraphEntitySchema>;

export const FlowDefinitionSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string(),
  node_types: z.array(z.string()),
  edge_types: z.array(z.string()),
});

export const FlowListResponseSchema = z.object({
  flows: z.array(FlowDefinitionSchema),
});

export type FlowDefinition = z.infer<typeof FlowDefinitionSchema>;
export type FlowListResponse = z.infer<typeof FlowListResponseSchema>;
