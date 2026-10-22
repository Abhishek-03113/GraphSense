import { useEffect, useState } from 'react';
import { PALETTE_SLOTS, type PaletteSlot } from '../../lib/schema/types';

export interface ThemeColors {
  label: string;
  labelSecondary: string;
  surface: string;
  surfaceInset: string;
  edge: string;
  accent: string;
  highlight: string;
  hue: Record<PaletteSlot, string>;
}

/** Canvas drawing cannot read CSS variables, so resolve them to concrete colours through a probe element. */
function resolve(probe: HTMLElement, variable: string): string {
  probe.style.color = `var(${variable})`;
  return getComputedStyle(probe).color;
}

export function readThemeColors(): ThemeColors {
  const probe = document.createElement('span');
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const hue = {} as Record<PaletteSlot, string>;
  for (const slot of PALETTE_SLOTS) hue[slot] = resolve(probe, `--gs-hue-${slot}`);
  const colors: ThemeColors = {
    label: resolve(probe, '--gs-color-label'),
    labelSecondary: resolve(probe, '--gs-color-label-secondary'),
    surface: resolve(probe, '--gs-surface-1'),
    surfaceInset: resolve(probe, '--gs-surface-2'),
    edge: resolve(probe, '--gs-border-strong'),
    accent: resolve(probe, '--gs-accent'),
    highlight: resolve(probe, '--gs-highlight'),
    hue,
  };
  probe.remove();
  return colors;
}

/** Current theme colours; re-reads when the system appearance changes. */
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState<ThemeColors>(() => readThemeColors());
  useEffect(() => {
    const list = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setColors(readThemeColors());
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, []);
  return colors;
}
