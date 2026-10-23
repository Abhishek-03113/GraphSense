import type { FormattedValue } from '../../lib/format';
import styles from './ValueText.module.css';

/**
 * Text for a formatted value. A coded value shows its meaning with the raw code beside it
 * ("Completely delivered · C"), so people read the label and can still match the code in the source data.
 */
export function ValueText({ value, nowrap }: { value: FormattedValue; /** Keep the label and code on one line (table cells). */ nowrap?: boolean }) {
  if (value.label === undefined || value.code === undefined) return <>{value.text}</>;
  return (
    <span className={[styles.coded, nowrap ? styles.nowrap : ''].filter(Boolean).join(' ')} title={`${value.label} (code ${value.code})`}>
      <span className={styles.label}>{value.label}</span>
      <span className={styles.code} aria-label={`code ${value.code}`}>
        <span aria-hidden="true">·</span> {value.code}
      </span>
    </span>
  );
}
