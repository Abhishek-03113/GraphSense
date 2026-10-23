import { useMemo } from 'react';
import { Button } from '../../components/ui/Button';
import { Checkbox } from '../../components/ui/Checkbox';
import { SearchInput } from '../../components/ui/Field';
import { Slider } from '../../components/ui/Slider';
import { TypeDot } from '../../components/ui/TypeBadge';
import type { GraphNode } from '../../lib/api/schemas';
import { formatCompact, formatInteger, pluralize } from '../../lib/format';
import { recordValue } from '../../lib/graph';
import { useSchema } from '../../lib/schema';
import styles from './FilterPanel.module.css';

interface FilterPanelProps {
  /** Records currently loaded, before type filtering. */
  nodes: GraphNode[];
  hiddenTypes: Set<string>;
  onToggleType: (type: string) => void;
  onShowAll: () => void;
  sampleSize: number;
  onSampleSize: (value: number) => void;
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  onPick: (recordId: string) => void;
  visibleRecords: number;
  visibleRelationships: number;
  floating?: boolean;
}

export function FilterPanel({
  nodes,
  hiddenTypes,
  onToggleType,
  onShowAll,
  sampleSize,
  onSampleSize,
  search,
  onSearch,
  selectedId,
  onPick,
  visibleRecords,
  visibleRelationships,
  floating,
}: FilterPanelProps) {
  const { schema, countFor, typeLabel } = useSchema();

  const inView = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const node of nodes) counts[node.type] = (counts[node.type] ?? 0) + 1;
    return counts;
  }, [nodes]);

  const types = useMemo(() => schema.nodeTypes.filter((type) => (inView[type.key] ?? 0) > 0 || (countFor(type.key) ?? 0) > 0), [schema, inView, countFor]);

  const query = search.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!query) return [];
    return nodes
      .filter((node) => !hiddenTypes.has(node.type))
      .filter((node) => recordValue(node).toLowerCase().includes(query) || (node.label ?? '').toLowerCase().includes(query))
      .slice(0, 8);
  }, [nodes, query, hiddenTypes]);

  const allVisible = hiddenTypes.size === 0;

  return (
    <aside className={[styles.panel, floating ? styles.floating : ''].filter(Boolean).join(' ')} aria-label="Filters">
      <div className={styles.section}>
        <SearchInput
          label="Find a record"
          placeholder="Type an ID…"
          value={search}
          mono
          onChange={(event) => onSearch(event.target.value)}
          onClear={() => onSearch('')}
        />
        {query && (
          <div aria-live="polite">
            {matches.length > 0 && (
              <ul className={styles.results} aria-label="Matching records">
                {matches.map((node) => (
                  <li key={node.id}>
                    <button
                      type="button"
                      className={[styles.result, node.id === selectedId ? styles.resultActive : ''].filter(Boolean).join(' ')}
                      onClick={() => onPick(node.id)}
                    >
                      <TypeDot type={node.type} />
                      <span className={styles.resultId}>{recordValue(node)}</span>
                      <span className={styles.resultType}>{typeLabel(node.type)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {matches.length === 0 && (
              <p className={styles.hint}>No records in view match “{search}”. To look up any record by ID, open search with the shortcut.</p>
            )}
          </div>
        )}
      </div>

      <div className={styles.section}>
        <div className={styles.heading}>
          <h2 className={styles.title}>Record types</h2>
          <div className={styles.links}>
            <Button size="sm" variant="accentGhost" disabled={allVisible} onClick={onShowAll}>
              Show all
            </Button>
          </div>
        </div>
        <div className={styles.types} role="group" aria-label="Record types to show">
          {types.map((type) => {
            const shown = inView[type.key] ?? 0;
            const total = countFor(type.key);
            return (
              <Checkbox
                key={type.key}
                label={type.plural}
                checked={!hiddenTypes.has(type.key)}
                onChange={() => onToggleType(type.key)}
                leading={<TypeDot type={type.key} />}
                trailing={total !== undefined && total > shown ? `${formatInteger(shown)} of ${formatCompact(total)}` : formatInteger(shown)}
              />
            );
          })}
        </div>
      </div>

      <div className={styles.section}>
        <Slider
          label="Records per type"
          value={sampleSize}
          min={5}
          max={100}
          step={5}
          onChange={onSampleSize}
          valueText={`${sampleSize}`}
        />
        <p className={styles.hint}>Each type shows a sample. Raise this to see more of the dataset; lower it for a clearer picture.</p>
      </div>

      <div className={styles.footer} aria-live="polite">
        <strong>{formatInteger(visibleRecords)}</strong> {pluralize(visibleRecords, 'record')} and{' '}
        <strong>{formatInteger(visibleRelationships)}</strong> {pluralize(visibleRelationships, 'relationship')} in view
      </div>
    </aside>
  );
}
