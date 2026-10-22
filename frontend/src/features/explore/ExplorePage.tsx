import { useQueries } from '@tanstack/react-query';
import { MessageSquareText, SlidersHorizontal, X } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { CanvasLoading, CanvasMessage } from '../../components/graph/CanvasOverlay';
import { CanvasToolbar } from '../../components/graph/CanvasToolbar';
import { GraphCanvas, type GraphCanvasHandle } from '../../components/graph/GraphCanvas';
import type { LayoutName } from '../../components/graph/layouts';
import { Legend } from '../../components/graph/Legend';
import { Button, IconButton } from '../../components/ui/Button';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { useFullGraph, subgraphOptions } from '../../lib/api/queries';
import { formatInteger, parseRecordId, pluralize } from '../../lib/format';
import { filterGraphByTypes, mergeGraphs, recordValue } from '../../lib/graph';
import { useDebouncedValue, useMediaQuery } from '../../lib/hooks';
import { useSchema } from '../../lib/schema';
import { useAsk, type RecordRef } from '../../store/ask';
import { useWorkspace } from '../../store/workspace';
import { AskPanel } from '../ask/AskPanel';
import { RecordInspector } from '../inspector/RecordInspector';
import { LoadDataEmpty } from '../onboarding/LoadDataEmpty';
import styles from './ExplorePage.module.css';
import { FilterPanel } from './FilterPanel';

const DEFAULT_SAMPLE = 12;

export default function ExplorePage() {
  const { schema, isEmpty, status } = useSchema();
  const [params, setParams] = useSearchParams();
  const focusId = params.get('focus');

  const canvasRef = useRef<GraphCanvasHandle>(null);
  const [layout, setLayout] = useState<LayoutName>('organic');
  const [sampleSize, setSampleSize] = useState(DEFAULT_SAMPLE);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string[]>([]);
  const wide = useMediaQuery('(min-width: 1001px)');
  const [filtersOpenPref, setFiltersOpenPref] = useState<boolean | null>(null);
  const filtersOpen = filtersOpenPref ?? wide;
  const [askOpen, setAskOpen] = useState(false);

  const highlightedIds = useWorkspace((s) => s.highlightedIds);
  const setHighlightedIds = useWorkspace((s) => s.setHighlightedIds);
  const setDraft = useAsk((s) => s.setDraft);

  const debouncedSample = useDebouncedValue(sampleSize, 350);
  const full = useFullGraph(debouncedSample);

  // Records we were pointed at (a deep link, an Ask answer, an expansion) may sit outside the sample; fetch their neighbourhoods.
  const baseIds = useMemo(() => new Set(full.data?.nodes.map((node) => node.id)), [full.data]);
  const extraIds = useMemo(() => {
    if (!full.data) return [];
    const wanted = [focusId, ...highlightedIds.slice(0, 8)].filter((id): id is string => Boolean(id) && !baseIds.has(id as string));
    return [...new Set([...wanted, ...expanded])];
  }, [full.data, baseIds, focusId, highlightedIds, expanded]);

  const extras = useQueries({
    queries: extraIds.map((id) => {
      const { type, value } = parseRecordId(id);
      return subgraphOptions(type, value, 1);
    }),
  });

  const graph = useMemo(() => mergeGraphs(full.data, ...extras.map((query) => query.data)), [full.data, extras]);

  const keep = useMemo(() => new Set([...(focusId ? [focusId] : []), ...highlightedIds]), [focusId, highlightedIds]);
  const visible = useMemo(() => {
    const allowed = new Set(graph.nodes.map((node) => node.type).filter((type) => !hiddenTypes.has(type)));
    return filterGraphByTypes(graph, allowed, keep);
  }, [graph, hiddenTypes, keep]);

  const matchIds = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return null;
    return new Set(
      visible.nodes
        .filter((node) => recordValue(node).toLowerCase().includes(query) || (node.label ?? '').toLowerCase().includes(query))
        .map((node) => node.id),
    );
  }, [visible.nodes, search]);

  const legendTypes = useMemo(() => {
    const present = new Set(visible.nodes.map((node) => node.type));
    const ordered = schema.nodeTypes.map((type) => type.key).filter((key) => present.has(key));
    return [...ordered, ...[...present].filter((key) => !ordered.includes(key))];
  }, [visible.nodes, schema.nodeTypes]);

  const select = useCallback(
    (id: string | null) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (id) next.set('focus', id);
          else next.delete('focus');
          return next;
        },
        { replace: true },
      );
      if (id) setAskOpen(false);
    },
    [setParams],
  );

  const openFromAnswer = useCallback(
    (focus: RecordRef, all: RecordRef[]) => {
      setHighlightedIds(all.map((record) => record.id));
      setParams((previous) => {
        const next = new URLSearchParams(previous);
        next.set('focus', focus.id);
        return next;
      }, { replace: true });
    },
    [setHighlightedIds, setParams],
  );

  const toggleType = (type: string) =>
    setHiddenTypes((previous) => {
      const next = new Set(previous);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });

  const selectedNode = focusId ? graph.nodes.find((node) => node.id === focusId) : undefined;
  const showInspector = Boolean(focusId) && !askOpen;
  const rightOpen = showInspector || askOpen;

  const startAsk = (prompt: string) => {
    setDraft(prompt);
    setAskOpen(true);
  };

  if (isEmpty) {
    return (
      <Page title="Explore" subtitle="A map of your records and how they connect.">
        <LoadDataEmpty />
      </Page>
    );
  }

  const loading = full.isPending || status === 'loading';
  const hasRecords = visible.nodes.length > 0;
  const summaryText = `${formatInteger(visible.nodes.length)} ${pluralize(visible.nodes.length, 'record')} · ${formatInteger(visible.edges.length)} ${pluralize(visible.edges.length, 'relationship')}`;

  return (
    <Page
      title="Explore"
      subtitle="A map of your records and how they connect. Select a record to see its details."
      flush
      actions={
        <Button
          variant={askOpen ? 'primary' : 'secondary'}
          icon={<MessageSquareText size={16} />}
          aria-pressed={askOpen}
          onClick={() => setAskOpen((open) => !open)}
        >
          Ask
        </Button>
      }
    >
      {filtersOpen && (
        <FilterPanel
          floating={!wide}
          nodes={graph.nodes}
          hiddenTypes={hiddenTypes}
          onToggleType={toggleType}
          onShowAll={() => setHiddenTypes(new Set())}
          sampleSize={sampleSize}
          onSampleSize={setSampleSize}
          search={search}
          onSearch={setSearch}
          selectedId={focusId}
          onPick={(id) => select(id)}
          visibleRecords={visible.nodes.length}
          visibleRelationships={visible.edges.length}
        />
      )}

      <div className={styles.stage}>
        <GraphCanvas
          ref={canvasRef}
          nodes={visible.nodes}
          edges={visible.edges}
          layout={layout}
          selectedId={focusId}
          highlightedIds={highlightedIds}
          matchIds={matchIds}
          onSelect={select}
          onExpand={(id) => setExpanded((previous) => (previous.includes(id) ? previous : [...previous, id]))}
          insetRight={rightOpen && wide ? 440 : 0}
          label={`Relationship graph: ${summaryText}. Use the filter panel to find a record, or press plus, minus and zero to zoom.`}
        />

        <CanvasToolbar
          canvas={canvasRef}
          layout={layout}
          onLayout={setLayout}
          leading={
            <IconButton
              label={filtersOpen ? 'Hide filters' : 'Show filters'}
              tooltipSide="bottom"
              icon={<SlidersHorizontal size={18} />}
              pressed={filtersOpen}
              onClick={() => setFiltersOpenPref(!filtersOpen)}
            />
          }
        />

        {highlightedIds.length > 0 && (
          <div className={styles.banner} role="status">
            <span className={styles.bannerText}>
              Highlighting {highlightedIds.length} {pluralize(highlightedIds.length, 'record')} from your question
            </span>
            <IconButton size="sm" label="Clear highlights" icon={<X size={14} />} onClick={() => setHighlightedIds([])} />
          </div>
        )}

        <Legend types={legendTypes} defaultOpen={!filtersOpen} />

        {loading && <CanvasLoading />}
        {!loading && full.isError && graph.nodes.length === 0 && (
          <CanvasMessage>
            <ErrorState title="The graph didn’t load" error={full.error} onRetry={() => void full.refetch()} retrying={full.isFetching} />
          </CanvasMessage>
        )}
        {!loading && !full.isError && !hasRecords && (
          <CanvasMessage>
            <EmptyState
              compact
              title={graph.nodes.length > 0 ? 'Every record type is hidden' : 'No records to show yet'}
              description={graph.nodes.length > 0 ? 'Turn a record type back on in the filters to see it here.' : 'Once records are loaded they will appear here as a connected map.'}
              actions={graph.nodes.length > 0 ? <Button onClick={() => setHiddenTypes(new Set())}>Show all types</Button> : undefined}
            />
          </CanvasMessage>
        )}

        {showInspector && focusId && (
          <RecordInspector
            key={focusId}
            recordId={focusId}
            node={selectedNode}
            onClose={() => select(null)}
            onOpenRecord={(id) => select(id)}
            onAsk={(prompt) => startAsk(prompt)}
          />
        )}
        {askOpen && <AskPanel onClose={() => setAskOpen(false)} onOpenRecord={openFromAnswer} />}
      </div>
    </Page>
  );
}
