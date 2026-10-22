import type { ReactNode } from 'react';
import styles from './Badge.module.css';

interface BadgeProps {
  tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger';
  /** Status badges always carry an icon so meaning never rests on colour alone. */
  icon?: ReactNode;
  /** CSS colour for a leading dot, used for record types. */
  dotColor?: string;
  children: ReactNode;
  title?: string;
}

export function Badge({ tone = 'neutral', icon, dotColor, children, title }: BadgeProps) {
  return (
    <span className={[styles.badge, tone === 'neutral' ? '' : styles[tone]].filter(Boolean).join(' ')} title={title}>
      {dotColor && <span className={styles.dot} style={{ background: dotColor }} aria-hidden="true" />}
      {icon && (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      )}
      <span className={styles.label}>{children}</span>
    </span>
  );
}
