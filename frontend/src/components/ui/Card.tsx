import type { HTMLAttributes, ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import styles from './Card.module.css';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padded?: boolean;
  children: ReactNode;
}

export function Card({ padded = true, className, children, ...rest }: CardProps) {
  return (
    <div className={[styles.card, padded ? styles.padded : '', className ?? ''].filter(Boolean).join(' ')} {...rest}>
      {children}
    </div>
  );
}

/** A whole-card link: one tab stop, one accessible name. */
export function LinkCard({ className, children, ...rest }: LinkProps) {
  return (
    <Link className={[styles.card, styles.padded, styles.interactive, className ?? ''].filter(Boolean).join(' ')} {...rest}>
      {children}
    </Link>
  );
}
