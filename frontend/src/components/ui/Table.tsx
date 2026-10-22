import { ArrowDown, ArrowUp } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react';
import { compareValues } from '../../lib/format';
import styles from './Table.module.css';

export interface Column<T> {
  key: string;
  header: string;
  /** Value used for sorting and as the default cell content. */
  value: (row: T) => unknown;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  align?: 'left' | 'right';
  mono?: boolean;
  numeric?: boolean;
}

interface DataTableProps<T> {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  initialSort?: { key: string; direction: 'asc' | 'desc' };
  maxHeight?: number | string;
  rowLabel?: (row: T) => string;
}

/** A sortable table. Headers are buttons, sort state is announced through `aria-sort`, rows are keyboard-activatable. */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  initialSort,
  maxHeight,
  rowLabel,
}: DataTableProps<T>) {
  const [sort, setSort] = useState(initialSort ?? null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((candidate) => candidate.key === sort.key);
    if (!column) return rows;
    const factor = sort.direction === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => factor * compareValues(column.value(a), column.value(b)));
  }, [rows, columns, sort]);

  const toggle = (key: string) =>
    setSort((current) =>
      current?.key === key ? (current.direction === 'asc' ? { key, direction: 'desc' } : null) : { key, direction: 'asc' },
    );

  const onKeyDown = (event: KeyboardEvent, row: T) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowClick?.(row);
    }
  };

  return (
    <div className={styles.scroll} style={{ maxHeight }} tabIndex={0} role="region" aria-label={caption}>
      <table className={styles.table}>
        <caption className="gs-sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.key === column.key;
              const ariaSort = active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : column.sortable ? 'none' : undefined;
              return (
                <th key={column.key} scope="col" aria-sort={ariaSort} className={column.align === 'right' ? styles.right : undefined}>
                  {column.sortable ? (
                    <button type="button" className={styles.headButton} onClick={() => toggle(column.key)}>
                      {column.header}
                      {active &&
                        (sort.direction === 'asc' ? (
                          <ArrowUp className={styles.sortIcon} size={14} aria-hidden="true" />
                        ) : (
                          <ArrowDown className={styles.sortIcon} size={14} aria-hidden="true" />
                        ))}
                    </button>
                  ) : (
                    <span className={styles.headStatic}>{column.header}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={[onRowClick ? styles.clickable : '', selectedKey === key ? styles.selected : ''].filter(Boolean).join(' ')}
                tabIndex={onRowClick ? 0 : undefined}
                aria-label={onRowClick ? rowLabel?.(row) : undefined}
                aria-selected={onRowClick ? selectedKey === key : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onRowClick ? (event) => onKeyDown(event, row) : undefined}
              >
                {columns.map((column) => {
                  const content = column.render ? column.render(row) : String(column.value(row) ?? '—');
                  return (
                    <td
                      key={column.key}
                      className={[
                        column.align === 'right' ? styles.right : '',
                        column.mono ? styles.mono : '',
                        column.numeric ? styles.numeric : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      title={typeof content === 'string' ? content : undefined}
                    >
                      {content}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
