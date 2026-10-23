import type { ReactNode } from 'react';
import { Skeleton } from '../ui/Skeleton';
import styles from './CanvasOverlay.module.css';

/** Covers a graph canvas while it loads. */
export function CanvasLoading({ message = 'Loading records…' }: { message?: string }) {
  return (
    <div className={styles.overlay} role="status" aria-live="polite" aria-busy="true">
      <div className={styles.loading}>
        <div className={styles.dots} aria-hidden="true">
          {Array.from({ length: 10 }, (_, index) => (
            <Skeleton key={index} width={18} height={18} radius="999px" />
          ))}
        </div>
        <span>{message}</span>
      </div>
    </div>
  );
}

/** Covers a graph canvas with a message card (errors, empty results). */
export function CanvasMessage({ children }: { children: ReactNode }) {
  return (
    <div className={styles.overlay}>
      <div className={styles.card}>{children}</div>
    </div>
  );
}
