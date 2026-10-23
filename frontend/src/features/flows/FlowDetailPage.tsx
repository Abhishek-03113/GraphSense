import { ArrowLeft, Info } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Page } from '../../app/Page';
import { CanvasLoading, CanvasMessage } from '../../components/graph/CanvasOverlay';
import { CanvasToolbar } from '../../components/graph/CanvasToolbar';
import { GraphCanvas, type GraphCanvasHandle } from '../../components/graph/GraphCanvas';
import type { LayoutName } from '../../components/graph/layouts';
import { Legend } from '../../components/graph/Legend';
import { IconButton, LinkButton } from '../../components/ui/Button';
import { EmptyState, ErrorState } from '../../components/ui/EmptyState';
import { Select } from '../../components/ui/Field';
import { TypeDot } from '../../components/ui/TypeBadge';
import { useFlowGraph } from '../../lib/api/queries';
import { formatInteger } from '../../lib/format';
import { useMediaQuery } from '../../lib/hooks';
import { useSchema } from '../../lib/schema';
import { RecordInspector } from '../inspector/RecordInspector';
import { DatasetState } from '../onboarding/DatasetState';
import styles from './Flows.module.css';

const SAMPLE_SIZES = [
  { value: 20, label: 'Small · about 20 per link' },
  { value: 50, label: 'Medium · about 50 per link' },
  { value: 100, label: 'Large · about 100 per link' },
];

export default function FlowDetailPage() {
  const { flowId } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('focus');
  const { schema, status, typeLabel, isEmpty } = useSchema();
  const flow = schema.flows.find((candidate) => candidate.id === flowId);
  const order = flow?.nodeTypes ?? [];

  const canvasRef = useRef<GraphCanvasHandle>(null);
  const [layout, setLayout] = useState<LayoutName>('leftToRight');
  const [limit, setLimit] = useState(20);
  const wide = useMediaQuery('(min-width: 1001px)');
  const [aboutPref, setAboutPref] = useState<boolean | null>(null);
  const aboutOpen = aboutPref ?? wide;

  const graphQuery = useFlowGraph(flow && !isEmpty ? flow.id : undefined, limit);
  const graph = graphQuery.data;

  const select = useCallback(
    (id: string | null) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (id) next.set('focus', id);
          else next.delete('focus');
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const node of graph?.nodes ?? []) out[node.type] = (out[node.type] ?? 0) + 1;
    return out;
  }, [graph]);

  const title = flow?.label ?? 'Flow';
  const back = (
    <LinkButton to="/flows" icon={<ArrowLeft size={16} />}>
      All flows
    </LinkButton>
  );

  if (status === 'ready' && !flow) {
    return (
      <Page title="Flow not found" actions={back}>
        <EmptyState
          icon={<Info size={22} />}
          title="We couldn’t find that flow"
          description="It may have been renamed or removed. Pick one from the list of flows."
          actions={<LinkButton variant="primary" to="/flows">See all flows</LinkButton>}
        />
      </Page>
    );
  }

  if (isEmpty) {
    return (
      <Page title={title} subtitle={flow?.description || 'Records in this flow, laid out step by step.'} actions={back}>
        <DatasetState />
      </Page>
    );
  }

  const selectedNode = graph?.nodes.find((node) => node.id === selectedId);
  const hasRecords = (graph?.nodes.length ?? 0) > 0;
  const loading = status === 'loading' || graphQuery.isPending;

  return (
    <Page title={title} subtitle={flow?.description || 'Records in this flow, laid out step by step.'} flush actions={back}>
      {aboutOpen && (
        <aside className={[styles.panel, wide ? '' : styles.floating].filter(Boolean).join(' ')} aria-label="About this flow">
          <h2 className={styles.panelTitle}>About this flow</h2>
          <div className={styles.panelSection}>
            <p className={styles.hint}>
              Each dot is a record, drawn from your data and arranged in the order the work moves. Lines connect records that relate to each other. Select a record to see its details, or follow it from start to finish with Trace.
            </p>
          </div>
          <div className={styles.panelSection}>
            <h3 className={styles.sectionLabel}>Steps in order</h3>
            <ol className={styles.order}>
              {order.map((type) => (
                <li key={type}>
                  <TypeDot type={type} />
                  <span>{typeLabel(type)}</span>
                  <span className={styles.orderCount}>{counts[type] ? formatInteger(counts[type]) : '–'}</span>
                </li>
              ))}
            </ol>
          </div>
          <Select label="Sample size" value={limit} onChange={(event) => setLimit(Number(event.target.value))} hint="A larger sample shows more records but takes longer to read.">
            {SAMPLE_SIZES.map((size) => (
              <option key={size.value} value={size.value}>
                {size.label}
              </option>
            ))}
          </Select>
        </aside>
      )}

      <div className={styles.stage}>
        <GraphCanvas
          ref={canvasRef}
          nodes={graph?.nodes ?? []}
          edges={graph?.edges ?? []}
          layout={layout}
          selectedId={selectedId}
          onSelect={select}
          insetRight={selectedId && wide ? 440 : 0}
          label={`${title}: ${graph?.nodes.length ?? 0} records and ${graph?.edges.length ?? 0} relationships, arranged in flow order.`}
        />
        <CanvasToolbar
          canvas={canvasRef}
          layout={layout}
          onLayout={setLayout}
          leading={
            <IconButton
              label={aboutOpen ? 'Hide flow details' : 'Show flow details'}
              tooltipSide="bottom"
              icon={<Info size={18} />}
              pressed={aboutOpen}
              onClick={() => setAboutPref(!aboutOpen)}
            />
          }
        />
        <Legend types={order} note={false} />

        {loading && <CanvasLoading message="Loading this flow…" />}
        {!loading && graphQuery.isError && !hasRecords && (
          <CanvasMessage>
            <ErrorState title="This flow didn’t load" error={graphQuery.error} onRetry={() => void graphQuery.refetch()} retrying={graphQuery.isFetching} />
          </CanvasMessage>
        )}
        {!loading && !graphQuery.isError && !hasRecords && (
          <CanvasMessage>
            <EmptyState compact title="No records in this flow yet" description="Records will appear here once data for these steps has been loaded." />
          </CanvasMessage>
        )}

        {selectedId && (
          <RecordInspector
            key={selectedId}
            recordId={selectedId}
            node={selectedNode}
            showExploreAction
            onClose={() => select(null)}
            onOpenRecord={(id) => navigate(`/explore?focus=${encodeURIComponent(id)}`)}
            onAsk={(prompt) => navigate(`/ask?q=${encodeURIComponent(prompt)}`)}
          />
        )}
      </div>
    </Page>
  );
}
