import type { NodeSingular, StylesheetJsonBlock } from 'cytoscape';
import { PALETTE_SLOTS } from '../../lib/schema/types';
import type { ThemeColors } from './useThemeColors';

const FONT = 'system-ui, -apple-system, "Segoe UI", Inter, sans-serif';

/**
 * Canvas stylesheet built from resolved theme colours.
 * `labelsAlways` shows every record label; otherwise only the focused ones.
 */
export function buildStylesheet(colors: ThemeColors, labelsAlways: boolean, reducedMotion: boolean): StylesheetJsonBlock[] {
  const transition = reducedMotion ? 0 : 120;
  const slotRules: StylesheetJsonBlock[] = PALETTE_SLOTS.map((slot) => ({
    selector: `node[slot = "${slot}"]`,
    style: { 'background-color': colors.hue[slot] },
  }));

  return [
    {
      selector: 'node',
      style: {
        width: 'data(size)',
        height: 'data(size)',
        'border-width': 2,
        'border-color': colors.surface,
        label: labelsAlways ? 'data(short)' : '',
        color: colors.label,
        'font-family': FONT,
        'font-size': 11,
        'font-weight': 500,
        // The label's centre sits at an offset `placeLabels` picks: the freest side of the record.
        'text-valign': 'center',
        'text-halign': 'center',
        'text-margin-x': (node: NodeSingular) => Number(node.data('lx') ?? 0),
        'text-margin-y': (node: NodeSingular) => Number(node.data('ly') ?? 0),
        'text-wrap': 'ellipsis',
        'text-max-width': '96px',
        'text-background-color': colors.surface,
        'text-background-opacity': 0.82,
        'text-background-padding': '2px',
        'text-background-shape': 'roundrectangle',
        'min-zoomed-font-size': 8,
        'overlay-opacity': 0,
        'transition-property': 'opacity, border-width, border-color',
        'transition-duration': transition,
      },
    },
    ...slotRules,
    {
      selector: 'edge',
      style: {
        width: 1,
        'curve-style': 'bezier',
        'line-color': colors.edge,
        'line-opacity': 0.55,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': colors.edge,
        'arrow-scale': 0.7,
        label: '',
        color: colors.labelSecondary,
        'font-family': FONT,
        'font-size': 10,
        'font-weight': 500,
        'text-rotation': 'autorotate',
        'text-background-color': colors.surface,
        'text-background-opacity': 0.9,
        'text-background-padding': '2px',
        'text-background-shape': 'roundrectangle',
        'min-zoomed-font-size': 8,
        'overlay-opacity': 0,
        'transition-property': 'opacity, line-color, width',
        'transition-duration': transition,
      },
    },
    {
      selector: 'edge[?reversed]',
      style: { 'source-arrow-shape': 'triangle', 'source-arrow-color': colors.edge, 'target-arrow-shape': 'none' },
    },
    // Emphasis states ---------------------------------------------------
    // Dimmed context recedes far enough that it never competes with a focused record's label.
    { selector: 'node.dim', style: { opacity: 0.1, 'z-index': 0 } },
    { selector: 'edge.dim', style: { opacity: 0.05, 'z-index': 0 } },
    { selector: '.soft-dim', style: { opacity: 0.42 } },
    {
      selector: 'node.focus-label',
      style: { label: 'data(short)', 'z-index': 20, 'font-weight': 600, 'text-background-opacity': 0.95 },
    },
    {
      selector: 'edge.active',
      style: {
        'line-color': colors.accent,
        'target-arrow-color': colors.accent,
        'source-arrow-color': colors.accent,
        'line-opacity': 1,
        width: 1.8,
        'z-index': 10,
      },
    },
    // One label per relationship kind around the focus, not one per edge: twelve identical
    // "billed to" captions say nothing the first one did not.
    {
      selector: 'edge.labelled',
      style: { label: 'data(label)', color: colors.label, 'z-index': 11 },
    },
    {
      selector: 'node.hovered',
      style: { 'border-width': 3, 'border-color': colors.labelSecondary },
    },
    {
      selector: 'node.selected-record',
      style: {
        'border-width': 4,
        'border-color': colors.accent,
        label: 'data(short)',
        'font-weight': 700,
        'z-index': 30,
      },
    },
    {
      selector: 'node.match',
      style: { 'border-width': 3, 'border-color': colors.accent, label: 'data(short)', 'z-index': 15 },
    },
    {
      selector: 'node.mark',
      style: {
        'underlay-color': colors.accent,
        'underlay-opacity': 0.22,
        'underlay-padding': 6,
        'underlay-shape': 'ellipse',
        'border-width': 3,
        'border-color': colors.accent,
        label: 'data(short)',
        'font-weight': 700,
        'z-index': 25,
      },
    },
    {
      selector: 'node.highlighted',
      style: {
        'underlay-color': colors.highlight,
        'underlay-opacity': 0.35,
        'underlay-padding': 7,
        'underlay-shape': 'ellipse',
        'border-width': 3,
        'border-color': colors.highlight,
        label: 'data(short)',
        'font-weight': 700,
        'z-index': 25,
      },
    },
  ];
}
