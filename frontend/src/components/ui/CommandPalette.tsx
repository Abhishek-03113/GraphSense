import { CornerDownLeft, Search } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '../../lib/hooks';
import { Kbd } from './Kbd';
import styles from './CommandPalette.module.css';

export interface PaletteItem {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  /** Extra words that should match the search. */
  keywords?: string;
  /** Skip text filtering (used for results that were already looked up for the query). */
  alwaysShow?: boolean;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  items: PaletteItem[];
  query: string;
  onQueryChange: (query: string) => void;
  busyText?: string;
  placeholder?: string;
}

function matches(item: PaletteItem, query: string): boolean {
  if (item.alwaysShow) return true;
  const haystack = `${item.label} ${item.keywords ?? ''} ${item.group}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => haystack.includes(token));
}

/** Global jump menu. Arrow keys move, Enter runs, Escape closes. */
export function CommandPalette({ open, onClose, items, query, onQueryChange, busyText, placeholder = 'Search pages, record types, flows, or enter a record ID' }: CommandPaletteProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [activeIndex, setActiveIndex] = useState(0);

  useFocusTrap(dialogRef, open);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const visible = useMemo(() => items.filter((item) => matches(item, query)), [items, query]);

  // Keep the highlighted row in range and in view.
  const active = Math.min(activeIndex, Math.max(visible.length - 1, 0));
  useEffect(() => {
    const element = document.getElementById(`${listId}-${active}`);
    element?.scrollIntoView?.({ block: 'nearest' });
  }, [active, listId, visible.length]);

  if (!open) return null;

  const run = (item: PaletteItem) => {
    onClose();
    item.run();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex(Math.min(active + 1, visible.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex(Math.max(active - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (visible[active]) run(visible[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  };

  return createPortal(
    <div className={styles.backdrop} onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={onKeyDown}>
        <div className={styles.searchRow}>
          <Search size={18} aria-hidden="true" />
          <input
            ref={inputRef}
            className={styles.search}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={visible[active] ? `${listId}-${active}` : undefined}
            aria-label="Search"
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => {
              onQueryChange(event.target.value);
              setActiveIndex(0);
            }}
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className={styles.results}>
          {visible.map((item, index) => {
            const header = index === 0 || visible[index - 1].group !== item.group ? item.group : null;
            return (
              <li key={item.id} role="presentation">
                {header && <div className={styles.group} role="presentation">{header}</div>}
                <div
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={[styles.item, index === active ? styles.active : ''].filter(Boolean).join(' ')}
                  onMouseMove={() => index !== active && setActiveIndex(index)}
                  onClick={() => run(item)}
                >
                  {item.icon && <span className={styles.itemIcon} aria-hidden="true">{item.icon}</span>}
                  <span className={styles.itemLabel}>{item.label}</span>
                  {item.hint && <span className={styles.itemHint}>{item.hint}</span>}
                </div>
              </li>
            );
          })}
          {visible.length === 0 && (
            <li role="presentation" className={styles.note}>
              {busyText ?? `Nothing matches “${query}”. Try a page name, a record type, or a record ID.`}
            </li>
          )}
          {busyText && visible.length > 0 && (
            <li role="presentation" className={styles.note}>{busyText}</li>
          )}
        </ul>
        <div className={styles.footer} aria-hidden="true">
          <span><Kbd>↑</Kbd><Kbd>↓</Kbd> to move</span>
          <span><Kbd><CornerDownLeft size={12} /></Kbd> to open</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
