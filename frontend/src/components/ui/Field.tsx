import { ChevronDown, Search, X } from 'lucide-react';
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import styles from './Field.module.css';

interface FieldWrapperProps {
  label?: string;
  hint?: string;
  hideLabel?: boolean;
  size?: 'sm' | 'md';
  id: string;
  children: ReactNode;
}

function FieldWrapper({ label, hint, hideLabel, size, id, children }: FieldWrapperProps) {
  return (
    <div className={[styles.field, size === 'sm' ? styles.sm : ''].filter(Boolean).join(' ')}>
      {label && (
        <label htmlFor={id} className={hideLabel ? 'gs-sr-only' : styles.label}>
          {label}
        </label>
      )}
      {children}
      {hint && (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      )}
    </div>
  );
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: string;
  hint?: string;
  hideLabel?: boolean;
  icon?: ReactNode;
  size?: 'sm' | 'md';
  mono?: boolean;
  onClear?: () => void;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, hideLabel, icon, size = 'md', mono, onClear, className, id, value, ...rest },
  ref,
) {
  const generated = useId();
  const inputId = id ?? generated;
  return (
    <FieldWrapper id={inputId} label={label} hint={hint} hideLabel={hideLabel} size={size}>
      <div className={styles.control}>
        {icon && <span className={styles.leading}>{icon}</span>}
        <input
          ref={ref}
          id={inputId}
          value={value}
          aria-describedby={hint ? `${inputId}-hint` : undefined}
          className={[styles.input, icon ? styles.withIcon : '', mono ? styles.mono : '', className ?? ''].filter(Boolean).join(' ')}
          {...rest}
        />
        {onClear && value !== undefined && String(value).length > 0 && (
          <span className={styles.trailing}>
            <button
              type="button"
              aria-label="Clear"
              onClick={onClear}
              style={{
                display: 'grid',
                placeItems: 'center',
                width: 'var(--gs-hit-min)',
                height: 'var(--gs-hit-min)',
                border: 0,
                background: 'transparent',
                color: 'var(--gs-color-label-secondary)',
                borderRadius: 'var(--gs-radius-sm)',
              }}
            >
              <X size={14} />
            </button>
          </span>
        )}
      </div>
    </FieldWrapper>
  );
});

export const SearchInput = forwardRef<HTMLInputElement, Omit<InputProps, 'icon' | 'type'>>(function SearchInput(props, ref) {
  return <Input ref={ref} type="search" icon={<Search size={16} aria-hidden="true" />} autoComplete="off" {...props} />;
});

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label?: string;
  hint?: string;
  hideLabel?: boolean;
  size?: 'sm' | 'md';
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, hideLabel, size = 'md', className, id, children, ...rest },
  ref,
) {
  const generated = useId();
  const selectId = id ?? generated;
  return (
    <FieldWrapper id={selectId} label={label} hint={hint} hideLabel={hideLabel} size={size}>
      <div className={styles.control}>
        <select
          ref={ref}
          id={selectId}
          aria-describedby={hint ? `${selectId}-hint` : undefined}
          className={[styles.select, className ?? ''].filter(Boolean).join(' ')}
          {...rest}
        >
          {children}
        </select>
        <ChevronDown className={styles.chevron} size={16} aria-hidden="true" />
      </div>
    </FieldWrapper>
  );
});
