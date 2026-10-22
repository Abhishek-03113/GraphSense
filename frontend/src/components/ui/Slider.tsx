import { useId, type CSSProperties } from 'react';
import styles from './Slider.module.css';

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  /** Text shown beside the label, defaults to the number. */
  valueText?: string;
}

export function Slider({ label, value, min, max, step = 1, onChange, valueText }: SliderProps) {
  const id = useId();
  const fill = ((value - min) / (max - min)) * 100;
  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <label htmlFor={id}>{label}</label>
        <span className={styles.value}>{valueText ?? value}</span>
      </div>
      <input
        id={id}
        type="range"
        className={styles.range}
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ '--fill': `${fill}%` } as CSSProperties}
        aria-valuetext={valueText}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}
