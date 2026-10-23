import { Check, Copy, MessageSquareText, Network, Route } from 'lucide-react';
import { Fragment, useMemo, useState } from 'react';
import { Button, IconButton, LinkButton } from '../../components/ui/Button';
import { Disclosure } from '../../components/ui/Disclosure';
import { ErrorState } from '../../components/ui/EmptyState';
import { Sheet } from '../../components/ui/Sheet';
import { Skeleton } from '../../components/ui/Skeleton';
import { TypeBadge, TypeDot } from '../../components/ui/TypeBadge';
import { ValueText } from '../../components/ui/ValueText';
import { useSubgraph } from '../../lib/api/queries';
import type { GraphNode } from '../../lib/api/schemas';
import { currencyFor, formatValue, humanize, lowerFirst, parseRecordId, pluralize } from '../../lib/format';
import { naturalLabel, neighboursOf, recordValue, type Neighbour } from '../../lib/graph';
import { useSchema } from '../../lib/schema';
import styles from './RecordInspector.module.css';

interface RecordInspectorProps {
  /** Record id in "Type:value" form. */
  recordId: string;
  /** The record as already loaded by the caller, if any. May carry properties. */
  node?: GraphNode;
  onClose: () => void;
  onOpenRecord: (recordId: string) => void;
  onAsk: (prompt: string) => void;
  placement?: 'inline' | 'overlay';
  /** Offer a link to open this record in Explore (for pages other than Explore). */
  showExploreAction?: boolean;
}

interface Group {
  key: string;
  direction: 'in' | 'out';
  edgeKey: string;
  otherType: string;
  neighbours: Neighbour[];
}

const INITIAL_VISIBLE = 5;

function PropertyList({
  entries,
  siblings,
  valueLabels,
}: {
  entries: [string, unknown][];
  siblings: Record<string, unknown>;
  /** Meanings of coded properties: property → { code → label }. */
  valueLabels: Record<string, Record<string, string>>;
}) {
  return (
    <dl className={styles.facts}>
      {entries.map(([key, value]) => {
        const formatted = formatValue(key, value, { currency: currencyFor(key, siblings), valueLabels: valueLabels[key] });
        return (
          <Fragment key={key}>
            <dt>{humanize(key)}</dt>
            <dd
              className={[formatted.mono ? styles.mono : '', formatted.numeric ? styles.numeric : '', formatted.kind === 'empty' ? styles.empty : '']
                .filter(Boolean)
                .join(' ')}
            >
              <ValueText value={formatted} />
            </dd>
          </Fragment>
        );
      })}
    </dl>
  );
}

function RelationshipGroup({ group, ownType, onOpen }: { group: Group; ownType: string; onOpen: (id: string) => void }) {
  const { typeLabel, edgeLabel, getTypeMeta } = useSchema();
  const [expanded, setExpanded] = useState(false);
  const count = group.neighbours.length;
  const other = lowerFirst(typeLabel(group.otherType, count));
  const verb =
    group.direction === 'out'
      ? edgeLabel(group.edgeKey, ownType, group.otherType)
      : edgeLabel(group.edgeKey, group.otherType, ownType);
  const own = lowerFirst(getTypeMeta(ownType).label);
  const visible = expanded ? group.neighbours : group.neighbours.slice(0, INITIAL_VISIBLE);

  return (
    <div className={styles.group}>
      <p className={styles.groupTitle}>
        {group.direction === 'out' ? (
          <>
            {verb} <strong>{count}</strong> {other}
          </>
        ) : (
          <>
            <strong>{count}</strong> {other} {verb} this {own}
          </>
        )}
      </p>
      <ul className={styles.neighbours}>
        {visible.map(({ node }) => {
          const value = recordValue(node);
          const name = naturalLabel(node.type, value, node.label);
          return (
            <li key={node.id}>
              <button type="button" className={styles.neighbour} onClick={() => onOpen(node.id)}>
                <TypeDot type={node.type} />
                <span className={styles.neighbourLabel}>
                  {name ? (
                    <>
                      {name} <span className={styles.neighbourId}>{value}</span>
                    </>
                  ) : (
                    <span className={styles.neighbourId}>{value}</span>
                  )}
                </span>
                <span className={styles.neighbourType}>{typeLabel(node.type)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {count > INITIAL_VISIBLE && (
        <div>
          <Button size="sm" variant="accentGhost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'Show fewer' : `Show all ${count}`}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Details for one record: what it is, what we know about it, and what it connects to. */
export function RecordInspector({ recordId, node, onClose, onOpenRecord, onAsk, placement = 'inline', showExploreAction }: RecordInspectorProps) {
  const { type, value } = parseRecordId(recordId);
  const { getTypeMeta } = useSchema();
  const meta = getTypeMeta(type);
  const subgraph = useSubgraph(type, value, 1);
  const [copied, setCopied] = useState(false);

  // The caller's copy may be a bare reference without details; the neighbourhood query carries them.
  const record = useMemo(() => {
    const loaded = subgraph.data?.nodes.find((candidate) => candidate.id === recordId);
    return node && Object.keys(node.properties).length > 0 ? node : (loaded ?? node);
  }, [node, subgraph.data, recordId]);
  const properties = useMemo(() => record?.properties ?? {}, [record]);
  const name = naturalLabel(type, value, record?.label);

  const { primaryEntries, otherEntries } = useMemo(() => {
    const entries = Object.entries(properties);
    const lookup = new Map(entries);
    const featured = meta.displayProperties.filter((key) => lookup.has(key)).map((key): [string, unknown] => [key, lookup.get(key)]);
    const featuredKeys = new Set(featured.map(([key]) => key));
    const rest = entries.filter(([key, v]) => !featuredKeys.has(key) && v !== null && v !== undefined && v !== '');
    return { primaryEntries: featured, otherEntries: rest };
  }, [properties, meta.displayProperties]);

  const groups = useMemo<Group[]>(() => {
    if (!subgraph.data) return [];
    const map = new Map<string, Group>();
    for (const neighbour of neighboursOf(subgraph.data, recordId)) {
      const key = `${neighbour.direction}:${neighbour.edge.type}:${neighbour.node.type}`;
      const group = map.get(key) ?? { key, direction: neighbour.direction, edgeKey: neighbour.edge.type, otherType: neighbour.node.type, neighbours: [] };
      if (!group.neighbours.some((existing) => existing.node.id === neighbour.node.id)) group.neighbours.push(neighbour);
      map.set(key, group);
    }
    return [...map.values()].sort((a, b) => (a.direction === b.direction ? b.neighbours.length - a.neighbours.length : a.direction === 'out' ? -1 : 1));
  }, [subgraph.data, recordId]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable: nothing to do */
    }
  };

  const title = name ?? `${meta.label} ${value}`;

  return (
    <Sheet
      label={`Details for ${title}`}
      placement={placement}
      onClose={onClose}
      title={title}
      subtitle={
        <div className={styles.subtitle}>
          <TypeBadge type={type} />
          <span className={styles.idRow}>
            {value}
            <IconButton
              size="sm"
              label={copied ? 'Copied' : 'Copy ID'}
              icon={copied ? <Check size={14} /> : <Copy size={14} />}
              onClick={copy}
            />
          </span>
        </div>
      }
    >
      <div className={styles.content}>
        <div className={styles.actions}>
          <LinkButton variant="primary" icon={<Route size={16} />} to={`/trace?type=${encodeURIComponent(type)}&id=${encodeURIComponent(value)}`}>
            Trace lifecycle
          </LinkButton>
          <Button icon={<MessageSquareText size={16} />} onClick={() => onAsk(`Tell me about ${lowerFirst(meta.label)} ${value}`)}>
            Ask about this
          </Button>
          {showExploreAction && (
            <LinkButton icon={<Network size={16} />} to={`/explore?focus=${encodeURIComponent(recordId)}`}>
              Show in Explore
            </LinkButton>
          )}
        </div>

        {meta.description && <p className={styles.note}>{meta.description}</p>}

        {primaryEntries.length > 0 && (
          <section className={styles.section} aria-label="Key details">
            <h3 className={styles.sectionTitle}>Key details</h3>
            <PropertyList entries={primaryEntries} siblings={properties} valueLabels={meta.valueLabels} />
          </section>
        )}

        {otherEntries.length > 0 && (
          <section className={styles.section} aria-label="More details">
            {primaryEntries.length === 0 ? (
              <>
                <h3 className={styles.sectionTitle}>Details</h3>
                <PropertyList entries={otherEntries.slice(0, 8)} siblings={properties} valueLabels={meta.valueLabels} />
                {otherEntries.length > 8 && (
                  <Disclosure label="Show all details" meta={`${otherEntries.length} ${pluralize(otherEntries.length, 'field')}`}>
                    <PropertyList entries={otherEntries.slice(8)} siblings={properties} valueLabels={meta.valueLabels} />
                  </Disclosure>
                )}
              </>
            ) : (
              <Disclosure label="More details" meta={`${otherEntries.length} ${pluralize(otherEntries.length, 'field')}`}>
                <PropertyList entries={otherEntries} siblings={properties} valueLabels={meta.valueLabels} />
              </Disclosure>
            )}
          </section>
        )}

        {primaryEntries.length === 0 && otherEntries.length === 0 && !subgraph.isPending && (
          <p className={styles.note}>No extra details are stored for this record. Its relationships are listed below.</p>
        )}

        <section className={styles.section} aria-label="Relationships" aria-busy={subgraph.isPending}>
          <h3 className={styles.sectionTitle}>Relationships</h3>
          {subgraph.isPending && (
            <div className={styles.skeletons} role="status" aria-label="Loading relationships">
              <Skeleton width="60%" />
              <Skeleton height={32} />
              <Skeleton height={32} />
            </div>
          )}
          {subgraph.isError && <ErrorState compact title="Relationships didn’t load" error={subgraph.error} onRetry={() => void subgraph.refetch()} retrying={subgraph.isFetching} />}
          {subgraph.isSuccess && groups.length === 0 && (
            <p className={styles.note}>This record isn’t connected to any other records yet.</p>
          )}
          {groups.map((group) => (
            <RelationshipGroup key={group.key} group={group} ownType={type} onOpen={onOpenRecord} />
          ))}
        </section>
      </div>
    </Sheet>
  );
}
