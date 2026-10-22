import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import styles from './Button.module.css';
import { Tooltip } from './Tooltip';

type Variant = 'primary' | 'secondary' | 'ghost' | 'accentGhost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface CommonProps {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  block?: boolean;
}

function classes(variant: Variant, size: Size, block?: boolean, extra?: string) {
  return [styles.button, styles[variant], size !== 'md' ? styles[size] : '', block ? styles.block : '', extra ?? '']
    .filter(Boolean)
    .join(' ');
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, CommonProps {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, block, loading, children, className, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={classes(variant, size, block, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : icon}
      {children}
    </button>
  );
});

export interface LinkButtonProps extends Omit<LinkProps, 'className'>, CommonProps {
  className?: string;
}

export function LinkButton({ variant = 'secondary', size = 'md', icon, block, children, className, ...rest }: LinkButtonProps) {
  return (
    <Link className={classes(variant, size, block, className)} {...rest}>
      {icon}
      {children}
    </Link>
  );
}

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Required: icon-only controls need an accessible name. It also becomes the tooltip. */
  label: string;
  icon: ReactNode;
  variant?: Variant;
  size?: Size;
  pressed?: boolean;
  tooltipSide?: 'top' | 'bottom' | 'right' | 'left';
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, variant = 'ghost', size = 'md', pressed, tooltipSide, className, type = 'button', ...rest },
  ref,
) {
  return (
    <Tooltip content={label} side={tooltipSide}>
      <button
        ref={ref}
        type={type}
        aria-label={label}
        aria-pressed={pressed}
        className={classes(variant, size, false, `${styles.icon} ${className ?? ''}`)}
        {...rest}
      >
        {icon}
      </button>
    </Tooltip>
  );
});
