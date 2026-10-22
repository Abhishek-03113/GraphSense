import type { ResolvedSchema } from './types';

/**
 * Where each record type sits in the process, as a type → position map.
 * Flows list their record types in the order work moves through them, so the
 * broadest flow gives the main sequence and narrower flows fill in anything it
 * leaves out. Empty when the dataset defines no flows.
 */
export function flowRank(schema: ResolvedSchema): Map<string, number> {
  const rank = new Map<string, number>();
  const flows = [...schema.flows].sort((a, b) => b.nodeTypes.length - a.nodeTypes.length);
  for (const flow of flows) {
    for (const key of flow.nodeTypes) {
      if (!rank.has(key)) rank.set(key, rank.size);
    }
  }
  return rank;
}

/** Order record types the way work flows through them; types no flow mentions keep their given order at the end. */
export function orderTypesByFlow(typeKeys: string[], schema: ResolvedSchema): string[] {
  const rank = flowRank(schema);
  const position = (key: string) => rank.get(key) ?? 1000 + typeKeys.indexOf(key);
  return [...typeKeys].sort((a, b) => position(a) - position(b));
}
