import { ChevronRight } from 'lucide-react';
import { useId, useState, type ReactNode } from 'react';
import styles from './Disclosure.module.css';

interface DisclosureProps {
  label: string;
  /** Text appended to the label, such as a count. */
  meta?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function Disclosure({ label, meta, defaultOpen = false, children }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  return (
    <div className={[styles.root, open ? styles.open : ''].filter(Boolean).join(' ')}>
      <button type="button" className={styles.trigger} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((v) => !v)}>
        <ChevronRight className={styles.chevron} size={16} aria-hidden="true" />
        {label}
        {meta && <span> · {meta}</span>}
      </button>
      {open && (
        <div id={panelId} className={styles.panel}>
          {children}
        </div>
      )}
    </div>
  );
}
