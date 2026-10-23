import { ChevronDown, ChevronUp } from 'lucide-react';
import { useId, useState } from 'react';
import { useSchema } from '../../lib/schema';
import { TypeDot } from '../ui/TypeBadge';
import styles from './Legend.module.css';

interface LegendProps {
  /** Type keys present in the view, in the order to list them. */
  types: string[];
  /** Show the "reading the graph" note. */
  note?: boolean;
  defaultOpen?: boolean;
}

/** Colour key for the record types on screen. Collapsible so it never gets in the way. */
export function Legend({ types, note = true, defaultOpen = true }: LegendProps) {
  const { typeLabel } = useSchema();
  // Start collapsed on small screens, where the canvas needs the room.
  const [open, setOpen] = useState(() => defaultOpen && window.matchMedia('(min-width: 721px)').matches);
  const id = useId();
  if (types.length === 0) return null;
  return (
    <div className={styles.legend}>
      <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        Legend
        {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronUp size={16} aria-hidden="true" />}
      </button>
      {open && (
        <ul id={id} className={styles.list}>
          {types.map((type) => (
            <li key={type} className={styles.item}>
              <TypeDot type={type} size={12} />
              <span>{typeLabel(type)}</span>
            </li>
          ))}
          {note && <li className={styles.note}>Larger dots have more relationships. Arrows point from one record to the one it relates to.</li>}
        </ul>
      )}
    </div>
  );
}
