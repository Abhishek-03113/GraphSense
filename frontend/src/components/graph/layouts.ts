import type { LayoutOptions } from 'cytoscape';

export type LayoutName = 'physics' | 'organic' | 'leftToRight' | 'topDown' | 'circle';

export const LAYOUT_CHOICES: { value: LayoutName; label: string }[] = [
  { value: 'physics', label: 'Physics' },
  { value: 'organic', label: 'Clusters' },
  { value: 'leftToRight', label: 'Horizontal' },
  { value: 'topDown', label: 'Vertical' },
  { value: 'circle', label: 'Circle' },
];

interface LayoutRun {
  animate: boolean;
  /** Start from scratch rather than from current positions. */
  randomize: boolean;
}

/** Options for the static layouts. `physics` is not a Cytoscape layout: `attachPhysics` drives it. */
export function layoutOptions(name: Exclude<LayoutName, 'physics'>, { animate, randomize }: LayoutRun): LayoutOptions {
  const base = { fit: true, padding: 48, animate };
  switch (name) {
    case 'leftToRight':
      return { name: 'dagre', rankDir: 'LR', nodeSep: 32, rankSep: 96, edgeSep: 8, ranker: 'network-simplex', ...base } as LayoutOptions;
    case 'topDown':
      return { name: 'dagre', rankDir: 'TB', nodeSep: 40, rankSep: 72, edgeSep: 8, ranker: 'network-simplex', ...base } as LayoutOptions;
    case 'circle':
      return { name: 'circle', spacingFactor: 1.1, ...base } as LayoutOptions;
    case 'organic':
    default:
      return {
        name: 'cose-bilkent',
        ...base,
        animate: animate ? 'end' : false,
        animationDuration: 450,
        nodeRepulsion: 9000,
        idealEdgeLength: 80,
        edgeElasticity: 0.1,
        gravity: 0.3,
        gravityRange: 3.8,
        numIter: 2500,
        tile: true,
        randomize,
        nodeDimensionsIncludeLabels: true,
      } as LayoutOptions;
  }
}
