import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import styles from './Tooltip.module.css';

interface TooltipProps {
  content: ReactNode;
  side?: 'top' | 'bottom' | 'right' | 'left';
  children: ReactNode;
  /** Skip the tooltip entirely (for example when a visible label already says the same). */
  disabled?: boolean;
  /** Stretch the wrapper to the width of its container. */
  fill?: boolean;
}

/** Hover and keyboard-focus hint. The trigger keeps its own accessible name; the tip is supplementary. */
export function Tooltip({ content, side = 'top', children, disabled, fill }: TooltipProps) {
  const id = useId();
  const wrapRef = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number; transform: string } | null>(null);

  const show = useCallback(() => {
    const element = wrapRef.current;
    if (!element || disabled) return;
    const rect = element.getBoundingClientRect();
    const gap = 8;
    if (side === 'bottom') setPosition({ top: rect.bottom + gap, left: rect.left + rect.width / 2, transform: 'translateX(-50%)' });
    else if (side === 'right') setPosition({ top: rect.top + rect.height / 2, left: rect.right + gap, transform: 'translateY(-50%)' });
    else if (side === 'left') setPosition({ top: rect.top + rect.height / 2, left: rect.left - gap, transform: 'translate(-100%, -50%)' });
    else setPosition({ top: rect.top - gap, left: rect.left + rect.width / 2, transform: 'translate(-50%, -100%)' });
  }, [side, disabled]);

  const hide = useCallback(() => setPosition(null), []);

  useEffect(() => {
    if (!position) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPosition(null);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', hide, true);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', hide, true);
    };
  }, [position, hide]);

  return (
    <span
      ref={wrapRef}
      className={fill ? `${styles.wrap} ${styles.fill}` : styles.wrap}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onPointerDown={hide}
    >
      {children}
      {position &&
        createPortal(
          <span
            id={id}
            role="tooltip"
            className={styles.tip}
            style={{ top: position.top, left: position.left, transform: position.transform }}
          >
            {content}
          </span>,
          document.body,
        )}
    </span>
  );
}
