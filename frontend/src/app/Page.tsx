import type { ReactNode } from 'react';
import { useDocumentTitle } from '../lib/hooks';
import styles from './Page.module.css';

interface PageProps {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Fill the remaining height with no padding (graph canvases and split views). */
  flush?: boolean;
  children: ReactNode;
}

/** Standard page frame: a header with title, subtitle and contextual actions, then the content. */
export function Page({ title, subtitle, actions, flush, children }: PageProps) {
  useDocumentTitle(title);
  return (
    <div className={styles.page}>
      <header className={[styles.header, flush ? styles.headerFlush : ''].filter(Boolean).join(' ')}>
        <div className={styles.titles}>
          <h1 className={styles.title}>{title}</h1>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </header>
      {flush ? (
        <div className={[styles.body, styles.flush].join(' ')}>{children}</div>
      ) : (
        <div className={styles.body}>
          <div className={styles.contained}>{children}</div>
        </div>
      )}
    </div>
  );
}
