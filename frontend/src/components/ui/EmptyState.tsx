import { AlertTriangle, RotateCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { describeError } from '../../lib/api/client';
import { Button } from './Button';
import styles from './EmptyState.module.css';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  tone?: 'neutral' | 'accent' | 'danger';
  compact?: boolean;
  detail?: ReactNode;
}

/** Used for empty results, first-run onboarding and failures alike. Always says what happened and what to do next. */
export function EmptyState({ icon, title, description, actions, tone = 'neutral', compact, detail }: EmptyStateProps) {
  const toneClass = tone === 'neutral' ? '' : styles[tone];
  return (
    <div className={[styles.state, compact ? styles.compact : '', toneClass].filter(Boolean).join(' ')}>
      {icon && (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      )}
      <h2 className={styles.title}>{title}</h2>
      {description && <p className={styles.description}>{description}</p>}
      {actions && <div className={styles.actions}>{actions}</div>}
      {detail && <div className={styles.detail}>{detail}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  compact?: boolean;
}

/** A failed load, with a plain-language reason and a retry. */
export function ErrorState({ title = 'This didn’t load', error, onRetry, retrying, compact }: ErrorStateProps) {
  return (
    <div role="alert">
      <EmptyState
        compact={compact}
        tone="danger"
        icon={<AlertTriangle size={22} />}
        title={title}
        description={error ? describeError(error) : 'Something went wrong while loading this.'}
        actions={
          onRetry && (
            <Button variant="secondary" icon={<RotateCw size={16} />} onClick={onRetry} loading={retrying}>
              Try again
            </Button>
          )
        }
      />
    </div>
  );
}
