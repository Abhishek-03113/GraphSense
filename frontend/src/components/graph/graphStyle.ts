import type { StylesheetJsonBlock } from 'cytoscape';
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
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 5,
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
    { selector: '.dim', style: { opacity: 0.16 } },
    { selector: '.soft-dim', style: { opacity: 0.42 } },
    {
      selector: 'node.focus-label',
      style: { label: 'data(short)', 'z-index': 20, 'font-weight': 600 },
    },
    {
      selector: 'edge.active',
      style: {
        'line-color': colors.accent,
        'target-arrow-color': colors.accent,
        'source-arrow-color': colors.accent,
        'line-opacity': 1,
        width: 1.8,
        label: 'data(label)',
        color: colors.label,
        'z-index': 10,
      },
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
