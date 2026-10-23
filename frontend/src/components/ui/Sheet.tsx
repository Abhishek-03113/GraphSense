import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '../../lib/hooks';
import { useWorkspace } from '../../store/workspace';
import { IconButton } from './Button';
import styles from './Sheet.module.css';

interface SheetProps {
  /** Accessible name when the visible title is custom content. */
  label: string;
  title: ReactNode;
  subtitle?: ReactNode;
  headerActions?: ReactNode;
  /** Let the content manage its own scrolling (for example a pinned composer). */
  fill?: boolean;
  onClose: () => void;
  /**
   * `inline` floats over the nearest positioned ancestor and leaves the page usable.
   * `overlay` covers the viewport with a backdrop and traps focus.
   */
  placement?: 'inline' | 'overlay';
  children: ReactNode;
}

/** A right-hand panel for details. Escape and the close button both dismiss it. */
export function Sheet({ label, title, subtitle, headerActions, fill, onClose, placement = 'inline', children }: SheetProps) {
  const ref = useRef<HTMLElement>(null);
  const modal = placement === 'overlay';
  useFocusTrap(ref, modal);

  useEffect(() => {
    if (modal) ref.current?.focus();
  }, [modal]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (useWorkspace.getState().paletteOpen) return;
      const target = event.target as HTMLElement | null;
      // Leave Escape to text fields, which use it to clear themselves.
      if (!modal && target && /^(input|textarea|select)$/i.test(target.tagName) && !ref.current?.contains(target)) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [modal, onClose]);

  const sheet = (
    <aside
      ref={ref}
      role={modal ? 'dialog' : 'complementary'}
      aria-modal={modal || undefined}
      aria-label={label}
      tabIndex={-1}
      className={[styles.sheet, modal ? styles.overlay : styles.inline].join(' ')}
    >
      <header className={styles.header}>
        <div className={styles.heading}>
          <h2 className={styles.title}>{title}</h2>
          {subtitle && <div className={styles.subtitle}>{subtitle}</div>}
        </div>
        {headerActions}
        <IconButton label="Close panel" icon={<X size={18} />} onClick={onClose} />
      </header>
      <div className={[styles.body, fill ? styles.fill : ''].filter(Boolean).join(' ')}>{children}</div>
    </aside>
  );

  if (!modal) return sheet;
  return createPortal(
    <>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      {sheet}
    </>,
    document.body,
  );
}
