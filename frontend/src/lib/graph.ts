import type { GraphData, GraphEdge, GraphNode } from './api/schemas';

/** Combine graphs, keeping the first copy of each record and relationship. */
export function mergeGraphs(...graphs: (GraphData | undefined | null)[]): GraphData {
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, GraphEdge>();
  for (const graph of graphs) {
    if (!graph) continue;
    for (const node of graph.nodes) {
      const existing = nodes.get(node.id);
      // Prefer the copy that carries properties.
      if (!existing || (Object.keys(existing.properties).length === 0 && Object.keys(node.properties).length > 0)) {
        nodes.set(node.id, node);
      }
    }
    for (const edge of graph.edges) {
      if (!edges.has(edge.id)) edges.set(edge.id, edge);
    }
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** Keep only records of the allowed types, and relationships whose ends both survive. */
export function filterGraphByTypes(graph: GraphData, allowed: Set<string>, alwaysKeep: Set<string> = new Set()): GraphData {
  const nodes = graph.nodes.filter((node) => allowed.has(node.type) || alwaysKeep.has(node.id));
  const ids = new Set(nodes.map((node) => node.id));
  return { nodes, edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)) };
}

export function countByType(nodes: GraphNode[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const node of nodes) out[node.type] = (out[node.type] ?? 0) + 1;
  return out;
}

export interface Neighbour {
  node: GraphNode;
  edge: GraphEdge;
  /** "out" when the focus record is the source of the relationship. */
  direction: 'out' | 'in';
}

/** All direct neighbours of one record in a graph. */
export function neighboursOf(graph: GraphData, recordId: string): Neighbour[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const out: Neighbour[] = [];
  for (const edge of graph.edges) {
    if (edge.source === recordId) {
      const node = byId.get(edge.target);
      if (node) out.push({ node, edge, direction: 'out' });
    } else if (edge.target === recordId) {
      const node = byId.get(edge.source);
      if (node) out.push({ node, edge, direction: 'in' });
    }
  }
  return out;
}

/**
 * A human name for a record, when the server has one. Records without a natural name come back labelled
 * "<Type> <id>", which says nothing the id does not, so that counts as no name.
 */
export function naturalLabel(type: string, value: string, label: string | null | undefined): string | null {
  const text = label?.trim();
  if (!text || text === value || text === `${type} ${value}`) return null;
  return text;
}

/** The part of a record id after the type, e.g. "Type:123" → "123". */
export function recordValue(node: Pick<GraphNode, 'id' | 'type'>): string {
  const prefix = `${node.type}:`;
  return node.id.startsWith(prefix) ? node.id.slice(prefix.length) : node.id.slice(node.id.indexOf(':') + 1);
}
