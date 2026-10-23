import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Input } from './Field';
import styles from './Combobox.module.css';

export interface ComboboxOption {
  value: string;
  hint?: string;
}

interface ComboboxProps {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  /** Called when an option is chosen from the list. */
  onSelect?: (option: ComboboxOption) => void;
  options: ComboboxOption[];
  loading?: boolean;
  placeholder?: string;
  mono?: boolean;
  emptyText?: string;
}

/** Text input with a suggestion list. Follows the ARIA combobox pattern (arrow keys, Enter, Escape). */
export function Combobox({ label, hint, value, onChange, onSelect, options, loading, placeholder, mono, emptyText = 'No matching records' }: ComboboxProps) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  const choose = (option: ComboboxOption) => {
    onChange(option.value);
    onSelect?.(option);
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, Math.max(options.length - 1, 0)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter' && open && options[active]) {
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false);
    }
  };

  const activeId = open && options[active] ? `${listId}-${active}` : undefined;

  return (
    <div className={styles.root} ref={rootRef}>
      <Input
        label={label}
        hint={hint}
        value={value}
        mono={mono}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        onChange={(event) => {
          onChange(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul id={listId} role="listbox" aria-label={`${label} suggestions`} className={styles.list}>
          {loading && <li className={styles.note}>Loading suggestions…</li>}
          {!loading && options.length === 0 && <li className={styles.note}>{emptyText}</li>}
          {options.map((option, index) => (
            <li
              key={option.value}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className={[styles.option, index === active ? styles.active : ''].filter(Boolean).join(' ')}
              onMouseEnter={() => setActive(index)}
              onPointerDown={(event) => {
                event.preventDefault();
                choose(option);
              }}
            >
              <span className={styles.optionValue}>{option.value}</span>
              {option.hint && <span className={styles.optionHint}>{option.hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
