import type { ReactNode } from 'react';
import styles from './Ask.module.css';

interface NoticeProps {
  tone?: 'info' | 'warn' | 'danger';
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}

/** A calm callout inside the Ask thread: what happened, and what can be done about it. */
export function Notice({ tone = 'info', icon, title, children, actions }: NoticeProps) {
  const toneClass = tone === 'warn' ? styles.noticeWarn : tone === 'danger' ? styles.noticeDanger : '';
  return (
    <div className={[styles.notice, toneClass].filter(Boolean).join(' ')} role={tone === 'danger' ? 'alert' : undefined}>
      <span className={styles.noticeIcon} aria-hidden="true">{icon}</span>
      <div className={styles.noticeBody}>
        <p className={styles.noticeTitle}>{title}</p>
        {children && <div className={styles.noticeText}>{children}</div>}
        {actions && <div className={styles.noticeActions}>{actions}</div>}
      </div>
    </div>
  );
}
