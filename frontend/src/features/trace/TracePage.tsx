import { Route, SearchX } from 'lucide-react';
import { useCallback, useMemo, useRef, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { CanvasLoading, CanvasMessage } from '../../components/graph/CanvasOverlay';
import { CanvasToolbar } from '../../components/graph/CanvasToolbar';
import { GraphCanvas, type GraphCanvasHandle } from '../../components/graph/GraphCanvas';
import type { LayoutName } from '../../components/graph/layouts';
import { Legend } from '../../components/graph/Legend';
import { Button } from '../../components/ui/Button';
import { Combobox } from '../../components/ui/Combobox';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { Select } from '../../components/ui/Field';
import { Skeleton } from '../../components/ui/Skeleton';
import { TypeDot } from '../../components/ui/TypeBadge';
import { useEntities, useTraceGraph } from '../../lib/api/queries';
import { makeRecordId, pluralize } from '../../lib/format';
import { useMediaQuery } from '../../lib/hooks';
import { orderTypesByFlow, useSchema } from '../../lib/schema';
import { RecordInspector } from '../inspector/RecordInspector';
import { LoadDataEmpty } from '../onboarding/LoadDataEmpty';
import { Timeline } from './Timeline';
import styles from './Trace.module.css';

const DEFAULT_DEPTH = 4;

export default function TracePage() {
  const { schema, isEmpty, getTypeMeta, typeLabel } = useSchema();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const urlType = params.get('type') ?? '';
  const urlId = params.get('id') ?? '';
  const urlDepth = Number(params.get('depth')) || DEFAULT_DEPTH;
  const selectedId = params.get('focus');

  const startTypes = useMemo(() => {
    const primary = schema.nodeTypes.filter((type) => type.isPrimary);
    return primary.length > 0 ? primary : schema.nodeTypes;
  }, [schema.nodeTypes]);
  const otherTypes = useMemo(() => schema.nodeTypes.filter((type) => !startTypes.includes(type)), [schema.nodeTypes, startTypes]);

  const [typeDraft, setTypeDraft] = useState<string | null>(null);
  const [idDraft, setIdDraft] = useState<string | null>(null);
  const [depthDraft, setDepthDraft] = useState<number | null>(null);
  const type = typeDraft ?? (urlType || startTypes[0]?.key || '');
  const id = idDraft ?? urlId;
  const depth = depthDraft ?? urlDepth;

  const entities = useEntities(type || undefined, 100);
  const options = useMemo(() => {
    const needle = id.trim().toLowerCase();
    const all = entities.data?.entities ?? [];
    return all
      .map((entity) => ({ value: String(entity.id ?? ''), hint: typeof entity.label === 'string' && entity.label !== String(entity.id) ? entity.label : undefined }))
      .filter((option) => option.value && option.value.toLowerCase().includes(needle))
      .slice(0, 20);
  }, [entities.data, id]);

  const canvasRef = useRef<GraphCanvasHandle>(null);
  const [layout, setLayout] = useState<LayoutName>('leftToRight');
  const wide = useMediaQuery('(min-width: 961px)');

  const trace = useTraceGraph(urlType || undefined, urlId || undefined, urlDepth);
  const graph = trace.data;
  const startId = urlType && urlId ? makeRecordId(urlType, urlId) : '';

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = id.trim();
    if (!type || !trimmed) return;
    const next = new URLSearchParams({ type, id: trimmed });
    if (depth !== DEFAULT_DEPTH) next.set('depth', String(depth));
    setParams(next);
    setIdDraft(null);
    setTypeDraft(null);
    setDepthDraft(null);
  };

  const select = useCallback(
    (recordId: string | null) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (recordId) next.set('focus', recordId);
          else next.delete('focus');
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  const legendTypes = useMemo(() => orderTypesByFlow([...new Set(graph?.nodes.map((node) => node.type) ?? [])], schema), [graph, schema]);

  if (isEmpty) {
    return (
      <Page title="Trace" subtitle="Follow one record from start to finish.">
        <LoadDataEmpty />
      </Page>
    );
  }

  const hasTrace = Boolean(urlType && urlId);
  const connected = (graph?.edges.length ?? 0) > 0;
  const selectedNode = graph?.nodes.find((node) => node.id === selectedId);
  const startMeta = urlType ? getTypeMeta(urlType) : null;
  const records = graph?.nodes.length ?? 0;

  return (
    <Page
      title="Trace"
      subtitle={hasTrace && startMeta ? `Everything connected to ${startMeta.label.toLowerCase()} ${urlId}, from start to finish.` : 'Follow one record through every step it touches.'}
      flush
    >
      <div className={styles.root}>
        <form className={styles.formBar} onSubmit={submit} aria-label="Choose a record to trace">
          <div className={`${styles.field} ${styles.fieldNarrow}`}>
            <Select
              label="Record type"
              value={type}
              onChange={(event) => {
                setTypeDraft(event.target.value);
                setIdDraft('');
              }}
            >
              {startTypes.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
              {otherTypes.length > 0 && (
                <optgroup label="Other record types">
                  {otherTypes.map((option) => (
                    <option key={option.key} value={option.key}>{option.label}</option>
                  ))}
                </optgroup>
              )}
            </Select>
          </div>
          <div className={styles.field}>
            <Combobox
              label="Record ID"
              value={id}
              mono
              placeholder={entities.data?.entities[0] ? `For example ${String(entities.data.entities[0].id)}` : 'Enter an ID'}
              onChange={(value) => setIdDraft(value)}
              options={options}
              loading={entities.isPending && Boolean(type)}
              emptyText={entities.isError ? 'Suggestions are unavailable. You can still type an ID.' : 'No matching records. Press Trace to try this ID anyway.'}
            />
          </div>
          <div className={`${styles.field} ${styles.fieldNarrow}`}>
            <Select label="How far to follow" value={depth} onChange={(event) => setDepthDraft(Number(event.target.value))}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} {pluralize(n, 'step')}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" variant="primary" icon={<Route size={16} />} disabled={!type || !id.trim()}>
            Trace
          </Button>
        </form>

        {!hasTrace && (
          <div className={styles.intro}>
            <EmptyState
              icon={<Route size={22} />}
              title="Pick a record to trace"
              description={`Choose a record type and enter an ID to see every record connected to it, grouped step by step. The link stays in your address bar, so you can share the trace.`}
            />
            {(entities.data?.entities.length ?? 0) > 0 && (
              <div className={styles.samples} role="group" aria-label={`Example ${typeLabel(type, 2).toLowerCase()} IDs`}>
                <span style={{ color: 'var(--gs-color-label-secondary)', fontSize: 'var(--gs-fs-small)' }}>Try one of these:</span>
                {entities.data?.entities.slice(0, 5).map((entity) => (
                  <button
                    key={String(entity.id)}
                    type="button"
                    className={styles.sample}
                    onClick={() => setParams(new URLSearchParams({ type, id: String(entity.id) }))}
                  >
                    {String(entity.id)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {hasTrace && (
          <div className={styles.results}>
            <div className={styles.graph}>
              <GraphCanvas
                ref={canvasRef}
                nodes={graph?.nodes ?? []}
                edges={graph?.edges ?? []}
                layout={layout}
                selectedId={selectedId}
                markedId={startId}
                onSelect={(recordId) => select(recordId)}
                insetRight={selectedId && wide ? 440 : 0}
                label={`Lifecycle of ${startMeta?.label ?? 'record'} ${urlId}: ${records} records.`}
              />
              <CanvasToolbar canvas={canvasRef} layout={layout} onLayout={setLayout} />
              {connected && <Legend types={legendTypes} note={false} />}
              {trace.isPending && <CanvasLoading message="Tracing…" />}
              {trace.isError && (
                <CanvasMessage>
                  <ErrorState title="The trace didn’t load" error={trace.error} onRetry={() => void trace.refetch()} retrying={trace.isFetching} />
                </CanvasMessage>
              )}
              {trace.isSuccess && !connected && (
                <CanvasMessage>
                  <EmptyState
                    compact
                    icon={<SearchX size={22} />}
                    title="No connected records found"
                    description={`We couldn’t find ${startMeta ? startMeta.label.toLowerCase() : 'a record'} “${urlId}” with any relationships. Check the ID and the record type, or browse the list of records to find a valid one.`}
                    actions={<Button onClick={() => navigate(`/records/${encodeURIComponent(urlType)}`)}>Browse {startMeta ? startMeta.plural.toLowerCase() : 'records'}</Button>}
                  />
                </CanvasMessage>
              )}
              {selectedId && (
                <RecordInspector
                  key={selectedId}
                  recordId={selectedId}
                  node={selectedNode}
                  showExploreAction
                  onClose={() => select(null)}
                  onOpenRecord={(recordId) => select(recordId)}
                  onAsk={(prompt) => navigate(`/ask?q=${encodeURIComponent(prompt)}`)}
                />
              )}
            </div>

            <aside className={styles.timeline} aria-label="Lifecycle timeline" aria-busy={trace.isPending}>
              <div className={styles.timelineHeader}>
                <h2 className={styles.timelineTitle}>Lifecycle</h2>
                <p className={styles.timelineSub}>Records grouped by step, in the order the work flows.</p>
              </div>
              {trace.isPending && (
                <div className={styles.timelineSkeleton} role="status" aria-label="Loading timeline">
                  {[0, 1, 2, 3].map((n) => (
                    <div key={n} style={{ display: 'flex', gap: 12 }}>
                      <Skeleton width={24} height={24} radius="999px" />
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <Skeleton width="45%" height={18} />
                        <Skeleton height={26} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {trace.isSuccess && connected && graph && (
                <Timeline nodes={graph.nodes} startId={startId} selectedId={selectedId} onSelect={(recordId) => select(recordId)} />
              )}
              {trace.isSuccess && !connected && (
                <p className={styles.timelineSub} style={{ padding: '0 var(--gs-space-5)' }}>
                  Nothing to list yet. Once a record with relationships is traced, its steps appear here.
                </p>
              )}
              {trace.isSuccess && connected && (
                <p className={styles.timelineSub} style={{ padding: '0 var(--gs-space-5) var(--gs-space-5)' }}>
                  <TypeDot type={urlType} size={8} /> Following up to {depth} {pluralize(depth, 'step')} from the starting point.
                </p>
              )}
            </aside>
          </div>
        )}
      </div>
    </Page>
  );
}
