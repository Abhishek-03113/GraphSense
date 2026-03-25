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

export type GraphNode = z.infer<typeof GraphNodeSchema>;
export type GraphEdge = z.infer<typeof GraphEdgeSchema>;
export type GraphData = z.infer<typeof GraphDataSchema>;
