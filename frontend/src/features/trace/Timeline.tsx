import { Flag } from 'lucide-react';
import { useMemo } from 'react';
import { Badge } from '../../components/ui/Badge';
import { TypeBadge, TypeDot } from '../../components/ui/TypeBadge';
import type { GraphNode } from '../../lib/api/schemas';
import { formatInteger, lowerFirst } from '../../lib/format';
import { recordValue } from '../../lib/graph';
import { orderTypesByFlow, useSchema } from '../../lib/schema';
import styles from './Trace.module.css';

interface TimelineProps {
  nodes: GraphNode[];
  startId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const PER_STEP = 8;

/** The traced records grouped by type, in the order work flows through them. */
export function Timeline({ nodes, startId, selectedId, onSelect }: TimelineProps) {
  const { schema, typeLabel } = useSchema();

  const steps = useMemo(() => {
    const byType = new Map<string, GraphNode[]>();
    for (const node of nodes) byType.set(node.type, [...(byType.get(node.type) ?? []), node]);
    const ordered = orderTypesByFlow([...byType.keys()], schema);
    return ordered.map((type) => ({
      type,
      records: [...(byType.get(type) ?? [])].sort((a, b) => (a.id === startId ? -1 : b.id === startId ? 1 : a.id.localeCompare(b.id, undefined, { numeric: true }))),
    }));
  }, [nodes, schema, startId]);

  return (
    <ol className={styles.steps} aria-label="Lifecycle steps">
      {steps.map((step, index) => (
        <li key={step.type} className={styles.step}>
          <div className={styles.rail}>
            <span className={styles.number} aria-hidden="true">{index + 1}</span>
          </div>
          <div className={styles.stepBody}>
            <div className={styles.stepHeading}>
              <TypeBadge type={step.type} />
              <span className={styles.stepCount}>
                {formatInteger(step.records.length)} {lowerFirst(typeLabel(step.type, step.records.length))}
              </span>
            </div>
            <div className={styles.records}>
              {step.records.slice(0, PER_STEP).map((record) => (
                <button
                  key={record.id}
                  type="button"
                  className={[styles.record, record.id === selectedId ? styles.recordSelected : ''].filter(Boolean).join(' ')}
                  aria-pressed={record.id === selectedId}
                  aria-label={`${typeLabel(record.type)} ${recordValue(record)}${record.id === startId ? ', starting point' : ''}`}
                  onClick={() => onSelect(record.id)}
                >
                  <TypeDot type={record.type} size={8} />
                  {recordValue(record)}
                  {record.id === startId && (
                    <span className={styles.start}>
                      <Flag size={11} aria-hidden="true" />
                    </span>
                  )}
                </button>
              ))}
              {step.records.length > PER_STEP && <span className={styles.more}>+{step.records.length - PER_STEP} more</span>}
            </div>
            {step.records.some((record) => record.id === startId) && (
              <div>
                <Badge tone="accent" icon={<Flag size={11} />}>Starting point</Badge>
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
