import { useCallback, useMemo, type ReactNode } from 'react';
import { useFlowList, useSchemaPayload, useSummary } from '../api/queries';
import { lowerFirst } from '../format';
import { SchemaContext, type SchemaContextValue } from './context';
import { emptySchema, fallbackTypeMeta, hashSlot, resolveSchema, toCounts } from './resolve';
import type { PaletteSlot, TypeMeta } from './types';

/** Loads the dataset description once and shares it with every screen. */
export function SchemaProvider({ children }: { children: ReactNode }) {
  const schemaQuery = useSchemaPayload();
  const summaryQuery = useSummary();
  // Flows only matter as a fallback, but fetching them is cheap and shared with the Flows page.
  const flowsQuery = useFlowList();

  const settled = !schemaQuery.isPending && !summaryQuery.isPending && !flowsQuery.isPending;

  const schema = useMemo(
    () =>
      settled
        ? resolveSchema({ payload: schemaQuery.data, summary: summaryQuery.data, flows: flowsQuery.data?.flows })
        : emptySchema(),
    [settled, schemaQuery.data, summaryQuery.data, flowsQuery.data],
  );

  const counts = useMemo(() => toCounts(summaryQuery.data), [summaryQuery.data]);

  const typeIndex = useMemo(() => new Map(schema.nodeTypes.map((type) => [type.key, type])), [schema]);

  const getTypeMeta = useCallback(
    (key: string): TypeMeta => typeIndex.get(key) ?? fallbackTypeMeta(key),
    [typeIndex],
  );

  const value = useMemo<SchemaContextValue>(() => {
    const totalRecords = Object.values(counts.nodes).reduce((sum, n) => sum + n, 0);
    const totalRelationships = Object.values(counts.edges).reduce((sum, n) => sum + n, 0);

    const primary = schema.nodeTypes.filter((type) => type.isPrimary);
    const headline =
      primary.length > 0
        ? primary
        : [...schema.nodeTypes].sort((a, b) => (counts.nodes[b.key] ?? 0) - (counts.nodes[a.key] ?? 0)).slice(0, 6);
    const headlineKeys = new Set(headline.map((type) => type.key));
    const others = schema.nodeTypes.filter((type) => !headlineKeys.has(type.key));

    const slotForType = (key: string): PaletteSlot => typeIndex.get(key)?.accent ?? hashSlot(key);

    const edgeLabel = (key: string, sourceType?: string, targetType?: string): string => {
      const matches = schema.edgeTypes.filter((edge) => edge.key === key);
      const exact = matches.find(
        (edge) => (!sourceType || edge.source === sourceType) && (!targetType || edge.target === targetType),
      );
      const chosen = exact ?? matches[0];
      return chosen ? chosen.label : lowerFirst(fallbackTypeMeta(key).label);
    };

    const status: SchemaContextValue['status'] = !settled
      ? 'loading'
      : summaryQuery.isError
        ? 'error'
        : 'ready';

    return {
      schema,
      status,
      error: summaryQuery.error,
      counts,
      totalRecords,
      totalRelationships,
      isEmpty: Boolean(summaryQuery.data) && totalRecords === 0,
      isDerived: settled && schema.source === 'derived',
      headlineTypes: headline,
      otherTypes: others,
      getTypeMeta,
      colorForType: (key) => `var(--gs-hue-${slotForType(key)})`,
      slotForType,
      typeLabel: (key, count) => {
        const meta = getTypeMeta(key);
        return count === undefined || count === 1 ? meta.label : meta.plural;
      },
      edgeLabel,
      describeEdge: (key, sourceType, targetType) =>
        `${getTypeMeta(sourceType).label} ${edgeLabel(key, sourceType, targetType)} ${lowerFirst(getTypeMeta(targetType).label)}`,
      countFor: (key) => counts.nodes[key],
      refetch: () => {
        void summaryQuery.refetch();
        void schemaQuery.refetch();
        void flowsQuery.refetch();
      },
    };
  }, [schema, counts, settled, summaryQuery, schemaQuery, flowsQuery, getTypeMeta, typeIndex]);

  return <SchemaContext.Provider value={value}>{children}</SchemaContext.Provider>;
}
