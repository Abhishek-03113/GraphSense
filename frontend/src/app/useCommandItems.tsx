import { useQueryClient } from '@tanstack/react-query';
import { Route, Workflow } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { PaletteItem } from '../components/ui/CommandPalette';
import { TypeDot } from '../components/ui/TypeBadge';
import { subgraphOptions } from '../lib/api/queries';
import { makeRecordId } from '../lib/format';
import { useDebouncedValue } from '../lib/hooks';
import { useSchema } from '../lib/schema';
import { NAV } from './nav';

/**
 * Builds the command palette's entries: pages, record types, flows, and, when
 * the query looks like a record ID, any record with that ID (checked against
 * the types worth starting from).
 */
export function useCommandItems(query: string, open: boolean) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const { schema, headlineTypes, getTypeMeta } = useSchema();
  const [found, setFound] = useState<{ query: string; types: string[] }>({ query: '', types: [] });
  const [lookingUp, setLookingUp] = useState(false);

  const trimmed = query.trim();
  const debounced = useDebouncedValue(trimmed, 300);
  const lookupKeys = headlineTypes.slice(0, 8).map((type) => type.key).join('|');

  useEffect(() => {
    if (!open || debounced.length < 2 || /\s/.test(debounced)) return undefined;
    let cancelled = false;
    const keys = lookupKeys.split('|').filter(Boolean);
    void Promise.resolve().then(() => !cancelled && setLookingUp(true));
    Promise.all(
      keys.map(async (type) => {
        try {
          const graph = await client.fetchQuery(subgraphOptions(type, debounced, 1));
          // The server always echoes the root record, so only count it as found when it has relationships.
          return graph.edges.length > 0 ? type : null;
        } catch {
          return null;
        }
      }),
    ).then((types) => {
      if (cancelled) return;
      setFound({ query: debounced, types: types.filter((t): t is string => t !== null) });
      setLookingUp(false);
    });
    return () => {
      cancelled = true;
    };
  }, [debounced, open, lookupKeys, client]);

  const items = useMemo<PaletteItem[]>(() => {
    const list: PaletteItem[] = [];

    if (found.query === trimmed && trimmed.length >= 2) {
      for (const type of found.types) {
        const meta = getTypeMeta(type);
        list.push({
          id: `record-open-${type}`,
          group: 'Records',
          label: `${meta.label} ${trimmed}`,
          hint: 'Show in Explore',
          icon: <TypeDot type={type} />,
          alwaysShow: true,
          run: () => navigate(`/explore?focus=${encodeURIComponent(makeRecordId(type, trimmed))}`),
        });
        list.push({
          id: `record-trace-${type}`,
          group: 'Records',
          label: `Trace ${meta.label.toLowerCase()} ${trimmed}`,
          hint: 'Follow its lifecycle',
          icon: <Route size={16} />,
          alwaysShow: true,
          run: () => navigate(`/trace?type=${encodeURIComponent(type)}&id=${encodeURIComponent(trimmed)}`),
        });
      }
    }

    for (const entry of NAV) {
      const Icon = entry.icon;
      list.push({
        id: `page-${entry.to}`,
        group: 'Pages',
        label: entry.label,
        hint: entry.description,
        icon: <Icon size={16} />,
        keywords: 'go open page',
        run: () => navigate(entry.to),
      });
    }

    for (const type of schema.nodeTypes) {
      list.push({
        id: `type-${type.key}`,
        group: 'Record types',
        label: type.plural,
        hint: 'Browse records',
        icon: <TypeDot type={type.key} />,
        keywords: `${type.label} ${type.key} records browse`,
        run: () => navigate(`/records/${encodeURIComponent(type.key)}`),
      });
    }

    for (const flow of schema.flows) {
      list.push({
        id: `flow-${flow.id}`,
        group: 'Flows',
        label: flow.label,
        hint: 'Open flow',
        icon: <Workflow size={16} />,
        keywords: `${flow.description} flow process`,
        run: () => navigate(`/flows/${encodeURIComponent(flow.id)}`),
      });
    }

    return list;
  }, [found, trimmed, schema, navigate, getTypeMeta]);

  const busy = open && lookingUp && trimmed.length >= 2 ? 'Looking up records…' : undefined;
  return { items, busy };
}
