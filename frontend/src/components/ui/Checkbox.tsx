import { Check } from 'lucide-react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import styles from './Checkbox.module.css';

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'children'> {
  label: string;
  /** Leading decoration, such as a colour swatch. */
  leading?: ReactNode;
  /** Right-aligned secondary text, such as a count. */
  trailing?: ReactNode;
}

export function Checkbox({ label, leading, trailing, ...rest }: CheckboxProps) {
  return (
    <label className={styles.row}>
      <input type="checkbox" className={styles.native} {...rest} />
      <span className={styles.box} aria-hidden="true">
        {rest.checked && <Check size={13} strokeWidth={3} />}
      </span>
      <span className={styles.content}>
        {leading}
        <span className={styles.text}>{label}</span>
      </span>
      {trailing !== undefined && <span className={styles.trailing}>{trailing}</span>}
    </label>
  );
}
