import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import type { ReactNode, RefObject } from 'react';
import { IconButton } from '../ui/Button';
import { Select } from '../ui/Field';
import styles from './CanvasToolbar.module.css';
import type { GraphCanvasHandle } from './GraphCanvas';
import { LAYOUT_CHOICES, type LayoutName } from './layouts';

interface CanvasToolbarProps {
  canvas: RefObject<GraphCanvasHandle | null>;
  layout: LayoutName;
  onLayout: (layout: LayoutName) => void;
  /** Controls placed before the zoom group, such as a filters toggle. */
  leading?: ReactNode;
}

/** Floating controls over a graph canvas: zoom, fit, layout. */
export function CanvasToolbar({ canvas, layout, onLayout, leading }: CanvasToolbarProps) {
  return (
    <div className={styles.toolbar} role="toolbar" aria-label="Graph controls">
      {leading}
      {leading && <span className={styles.divider} aria-hidden="true" />}
      <IconButton label="Zoom in" tooltipSide="bottom" icon={<ZoomIn size={18} />} onClick={() => canvas.current?.zoomIn()} />
      <IconButton label="Zoom out" tooltipSide="bottom" icon={<ZoomOut size={18} />} onClick={() => canvas.current?.zoomOut()} />
      <IconButton label="Fit to screen" tooltipSide="bottom" icon={<Maximize2 size={17} />} onClick={() => canvas.current?.fit()} />
      <span className={styles.divider} aria-hidden="true" />
      <div className={styles.layout}>
        <Select
          label="Layout"
          hideLabel
          size="sm"
          value={layout}
          onChange={(event) => onLayout(event.target.value as LayoutName)}
        >
          {LAYOUT_CHOICES.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}
