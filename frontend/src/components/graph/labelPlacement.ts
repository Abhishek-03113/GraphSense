import type { Core, NodeSingular } from 'cytoscape';

/** Space between a record's edge and its label. */
const LABEL_GAP = 5;
/** Rough width of one label character at the canvas font size, and the label box limits. */
const CHAR_WIDTH = 6.3;
const MAX_LABEL_WIDTH = 100;
const LABEL_HEIGHT = 15;
/** Search radius for records and labels a label could collide with (a label reaches about this far). */
const REACH = 150;
const DOWN = Math.PI / 2;
/** Directions tried for a label, every 22.5 degrees; index 4 is straight down. */
const CANDIDATES = Array.from({ length: 16 }, (_, i) => (i * Math.PI) / 8);
/** Labels are wide and short: one beside a record crosses more than one above or below. */
const SIDEWAYS_PENALTY = 0.4;
const DOWN_BONUS = 1.05;
/** Clearance beyond a right angle buys nothing: a label is as safe at 90 degrees from its edges as at 180. */
const ENOUGH_CLEARANCE = Math.PI / 2;
/** Cost of a label box covering another record or label, in radians of clearance. */
const OVERLAP_COST = 2;

interface Offset {
  lx: number;
  ly: number;
}

interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/** Where a label sits by default, before anything has been placed. */
export function defaultLabelOffset(size: number): Offset {
  return { lx: 0, ly: size / 2 + LABEL_GAP + LABEL_HEIGHT / 2 };
}

const radiusOf = (node: NodeSingular) => Number(node.data('size') ?? 20) / 2;
const halfWidthOf = (node: NodeSingular) => Math.min(String(node.data('short') ?? '').length * CHAR_WIDTH, MAX_LABEL_WIDTH) / 2 + 2;
const separation = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
const cellOf = (value: number) => Math.floor(value / REACH);

/** Bucket records by position so finding the ones near a record does not scan the whole graph. */
function spatialIndex(cy: Core): Map<string, NodeSingular[]> {
  const grid = new Map<string, NodeSingular[]>();
  cy.nodes().forEach((node) => {
    const { x, y } = node.position();
    const cell = `${cellOf(x)}:${cellOf(y)}`;
    const bucket = grid.get(cell);
    if (bucket) bucket.push(node);
    else grid.set(cell, [node]);
  });
  return grid;
}

function nearby(grid: Map<string, NodeSingular[]>, node: NodeSingular): NodeSingular[] {
  const { x, y } = node.position();
  const found: NodeSingular[] = [];
  for (let i = -1; i <= 1; i += 1) {
    for (let j = -1; j <= 1; j += 1) {
      for (const other of grid.get(`${cellOf(x) + i}:${cellOf(y) + j}`) ?? []) {
        if (other !== node) found.push(other);
      }
    }
  }
  return found;
}

/** Offset of the label's centre so its box clears the record in direction `angle`. */
function offsetFor(node: NodeSingular, angle: number): Offset {
  const dx = Math.cos(angle);
  const dy = Math.sin(angle);
  const distance = radiusOf(node) + LABEL_GAP + Math.abs(dx) * halfWidthOf(node) + Math.abs(dy) * (LABEL_HEIGHT / 2);
  return { lx: dx * distance, ly: dy * distance };
}

function boxAt(node: NodeSingular, { lx, ly }: Offset): Box {
  const { x, y } = node.position();
  const halfWidth = halfWidthOf(node);
  return { left: x + lx - halfWidth, right: x + lx + halfWidth, top: y + ly - LABEL_HEIGHT / 2, bottom: y + ly + LABEL_HEIGHT / 2 };
}

const boxesOverlap = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

function boxHitsRecord(box: Box, node: NodeSingular): boolean {
  const { x, y } = node.position();
  const nearestX = Math.min(Math.max(x, box.left), box.right);
  const nearestY = Math.min(Math.max(y, box.top), box.bottom);
  return Math.hypot(x - nearestX, y - nearestY) < radiusOf(node);
}

/**
 * Put each label where it is furthest from the record's own relationships and covers no other record or
 * label. Busy records go first, so a hub labels into the gap between its spokes and the records around
 * it label outwards; below is preferred whenever it is as good as anything else.
 */
export function placeLabels(cy: Core): void {
  const grid = spatialIndex(cy);
  const placed = new Map<string, Box>();
  // One pass over the edges instead of a neighbourhood query per record.
  const adjacent = new Map<string, NodeSingular[]>();
  cy.edges().forEach((edge) => {
    const source = edge.source();
    const target = edge.target();
    for (const [from, to] of [
      [source, target],
      [target, source],
    ]) {
      const list = adjacent.get(from.id());
      if (list) list.push(to);
      else adjacent.set(from.id(), [to]);
    }
  });
  const order = cy.nodes().sort((a, b) => b.degree(false) - a.degree(false));

  cy.batch(() => {
    order.forEach((node) => {
      const { x, y } = node.position();
      const spokes: number[] = [];
      for (const other of adjacent.get(node.id()) ?? []) {
        const p = other.position();
        if (p.x !== x || p.y !== y) spokes.push(Math.atan2(p.y - y, p.x - x));
      }
      const around = nearby(grid, node);

      let best = offsetFor(node, DOWN);
      let bestScore = Number.NEGATIVE_INFINITY;
      for (const angle of CANDIDATES) {
        const offset = offsetFor(node, angle);
        const box = boxAt(node, offset);
        const clearance = Math.min(ENOUGH_CLEARANCE, ...spokes.map((spoke) => separation(angle, spoke)));
        let overlaps = 0;
        for (const other of around) {
          if (boxHitsRecord(box, other)) overlaps += 1;
          const otherBox = placed.get(other.id());
          if (otherBox && boxesOverlap(box, otherBox)) overlaps += 1;
        }
        const score =
          clearance * (1 - SIDEWAYS_PENALTY * Math.abs(Math.cos(angle))) * (angle === DOWN ? DOWN_BONUS : 1) - overlaps * OVERLAP_COST;
        if (score > bestScore) {
          bestScore = score;
          best = offset;
        }
      }

      placed.set(node.id(), boxAt(node, best));
      const lx = Math.round(best.lx);
      const ly = Math.round(best.ly);
      if (node.data('lx') !== lx || node.data('ly') !== ly) node.data({ lx, ly });
    });
  });
}
