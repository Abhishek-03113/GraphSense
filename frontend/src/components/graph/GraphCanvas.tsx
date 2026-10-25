import cytoscape, { type Core, type EdgeCollection, type EdgeSingular, type ElementDefinition } from 'cytoscape';
import dagre from 'cytoscape-dagre';
import coseBilkent from 'cytoscape-cose-bilkent';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, type KeyboardEvent } from 'react';
import type { GraphEdge, GraphNode } from '../../lib/api/schemas';
import { recordValue } from '../../lib/graph';
import { usePrefersReducedMotion } from '../../lib/hooks';
import { flowRank, useSchema } from '../../lib/schema';
import styles from './GraphCanvas.module.css';
import { buildStylesheet } from './graphStyle';
import { defaultLabelOffset, placeLabels } from './labelPlacement';
import { layoutOptions, type LayoutName } from './layouts';
import { attachPhysics, type Physics } from './physics';
import { useThemeColors } from './useThemeColors';

cytoscape.use(dagre);
cytoscape.use(coseBilkent);

export interface GraphCanvasHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  relayout: () => void;
}

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  layout: LayoutName;
  selectedId?: string | null;
  highlightedIds?: string[];
  /** A record to ring without dimming anything else, such as the starting point of a trace. */
  markedId?: string | null;
  /** When set, records outside this set are dimmed (search results). */
  matchIds?: Set<string> | null;
  onSelect: (id: string | null) => void;
  onExpand?: (id: string) => void;
  /** Pixels at the right edge covered by an overlay, so selection can pan clear of it. */
  insetRight?: number;
  label: string;
  /** Show every record label. Defaults to on for small graphs. */
  labelsAlways?: boolean;
}

const FOCUS_CLASSES = 'dim soft-dim active labelled focus-label hovered selected-record match highlighted mark';

/** The longest edge of each relationship kind: the one with the most room for its caption. */
function captionEdges(edges: EdgeCollection): EdgeCollection {
  const longest = new Map<string, { edge: EdgeSingular; length: number }>();
  edges.forEach((edge) => {
    const a = edge.source().position();
    const b = edge.target().position();
    const length = Math.hypot(a.x - b.x, a.y - b.y);
    const kind = String(edge.data('label'));
    const current = longest.get(kind);
    if (!current || length > current.length) longest.set(kind, { edge, length });
  });
  return edges.filter((edge) => longest.get(String(edge.data('label')))?.edge === edge);
}

/** Interactive relationship graph. Knows nothing about the dataset: colours and labels come from the schema. */
export const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(function GraphCanvas(
  { nodes, edges, layout, selectedId, highlightedIds, markedId, matchIds, onSelect, onExpand, insetRight = 0, label, labelsAlways },
  ref,
) {
  const { schema, slotForType, edgeLabel } = useSchema();
  const rank = useMemo(() => flowRank(schema), [schema]);
  const colors = useThemeColors();
  const reducedMotion = usePrefersReducedMotion();

  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const physicsRef = useRef<Physics | null>(null);
  const hoveredRef = useRef<string | null>(null);
  const latest = useRef({ onSelect, onExpand, layout, reducedMotion, insetRight });
  const structureRef = useRef('');
  const emphasisRef = useRef<() => void>(() => undefined);
  /** Edges captioned by the current emphasis, so pointing away from another edge only touches that edge. */
  const captionedRef = useRef<EdgeCollection | null>(null);

  useEffect(() => {
    latest.current = { onSelect, onExpand, layout, reducedMotion, insetRight };
  });

  const showAllLabels = labelsAlways ?? nodes.length <= 70;

  // ── Elements ─────────────────────────────────────────────
  const elements = useMemo<ElementDefinition[]>(() => {
    const typeById = new Map(nodes.map((node) => [node.id, node.type]));
    const seenNodes = new Set<string>();
    const degree = new Map<string, number>();
    const validEdges = edges.filter((edge) => typeById.has(edge.source) && typeById.has(edge.target));
    for (const edge of validEdges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    const dense = nodes.length > 150;
    const out: ElementDefinition[] = [];
    for (const node of nodes) {
      if (seenNodes.has(node.id)) continue;
      seenNodes.add(node.id);
      const d = degree.get(node.id) ?? 0;
      const size = dense ? Math.min(10 + 3 * Math.sqrt(d), 26) : Math.min(18 + 5 * Math.sqrt(d), 42);
      out.push({
        group: 'nodes',
        data: { id: node.id, short: recordValue(node), slot: slotForType(node.type), size, ...defaultLabelOffset(size) },
      });
    }
    const seenEdges = new Set<string>();
    for (const edge of validEdges) {
      if (seenEdges.has(edge.id)) continue;
      seenEdges.add(edge.id);
      // Lay relationships out in process order: when one points against the flow, swap its ends for
      // layout and draw the arrowhead at the other end so it still points the true way.
      const sourceRank = rank.get(typeById.get(edge.source) ?? '');
      const targetRank = rank.get(typeById.get(edge.target) ?? '');
      const reversed = sourceRank !== undefined && targetRank !== undefined && sourceRank > targetRank;
      out.push({
        group: 'edges',
        data: {
          id: edge.id,
          source: reversed ? edge.target : edge.source,
          target: reversed ? edge.source : edge.target,
          reversed,
          label: edgeLabel(edge.type, typeById.get(edge.source), typeById.get(edge.target)),
        },
      });
    }
    return out;
  }, [nodes, edges, slotForType, edgeLabel, rank]);

  const runLayout = useCallback((randomize: boolean, animate = true) => {
    const cy = cyRef.current;
    if (!cy || cy.nodes().length === 0) return;
    const { layout: name, reducedMotion: reduce } = latest.current;
    if (name === 'physics') {
      physicsRef.current ??= attachPhysics(cy, () => placeLabels(cy));
      physicsRef.current.run({ scatter: randomize, animate: animate && !reduce });
      return;
    }
    physicsRef.current?.destroy();
    physicsRef.current = null;
    cy.layout(layoutOptions(name, { animate: animate && !reduce && cy.nodes().length < 220, randomize })).run();
  }, []);

  // ── Create and destroy the instance ──────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const cy = cytoscape({
      container,
      elements: [],
      minZoom: 0.12,
      maxZoom: 3,
      wheelSensitivity: 0.3,
      boxSelectionEnabled: false,
      style: [],
    });
    cyRef.current = cy;

    cy.on('tap', 'node', (event) => latest.current.onSelect(event.target.id()));
    cy.on('tap', (event) => {
      if (event.target === cy) latest.current.onSelect(null);
    });
    cy.on('dbltap', 'node', (event) => latest.current.onExpand?.(event.target.id()));
    cy.on('mouseover', 'node', (event) => {
      hoveredRef.current = event.target.id();
      container.style.cursor = 'pointer';
      emphasisRef.current();
    });
    cy.on('mouseout', 'node', () => {
      hoveredRef.current = null;
      container.style.cursor = '';
      emphasisRef.current();
    });
    // Any single relationship can still be read by pointing at it.
    cy.on('mouseover', 'edge', (event) => {
      if (!event.target.hasClass('dim')) event.target.addClass('labelled');
    });
    cy.on('mouseout', 'edge', (event) => {
      if (!captionedRef.current?.contains(event.target)) event.target.removeClass('labelled');
    });
    cy.on('layoutstop', () => placeLabels(cy));
    cy.on('free', 'node', () => placeLabels(cy));

    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      physicsRef.current?.destroy();
      physicsRef.current = null;
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // ── Theme ────────────────────────────────────────────────
  useEffect(() => {
    cyRef.current?.style(buildStylesheet(colors, showAllLabels, reducedMotion));
  }, [colors, showAllLabels, reducedMotion]);

  // ── Sync elements ────────────────────────────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const wanted = new Map(elements.map((element) => [element.data.id as string, element]));
    const key = [...wanted.keys()].sort().join('|');
    const changed = key !== structureRef.current;
    const hadNodes = cy.nodes().length > 0;

    cy.batch(() => {
      cy.elements().forEach((element) => {
        if (!wanted.has(element.id())) element.remove();
      });
      const additions = elements.filter((element) => cy.getElementById(element.data.id as string).empty());
      // Nodes must exist before edges that reference them.
      cy.add(additions.filter((element) => element.group === 'nodes'));
      cy.add(additions.filter((element) => element.group === 'edges'));
      for (const element of elements) {
        const existing = cy.getElementById(element.data.id as string);
        if (existing.nonempty()) existing.data(element.data);
      }
    });
    cy.style(buildStylesheet(colors, showAllLabels, reducedMotion));
    if (changed) {
      structureRef.current = key;
      runLayout(!hadNodes);
    } else {
      // Syncing data reset label offsets on records that have not moved. New records sit at the origin
      // until the layout above places them, and every layout places labels when it finishes.
      placeLabels(cy);
    }
    emphasisRef.current();
    // Only element identity should re-sync; colours and label mode have their own effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements, runLayout]);

  // ── Layout choice ────────────────────────────────────────
  const firstLayout = useRef(true);
  useEffect(() => {
    if (firstLayout.current) {
      firstLayout.current = false;
      return;
    }
    // Physics starts from the current arrangement, so switching to it morphs rather than jumps.
    runLayout(layout !== 'physics');
  }, [layout, runLayout]);

  // ── Emphasis: selection, hover, search, highlights ───────
  const highlightKey = (highlightedIds ?? []).join('|');
  useEffect(() => {
    emphasisRef.current = () => {
      const cy = cyRef.current;
      if (!cy) return;
      const highlightSet = new Set(highlightedIds ?? []);
      captionedRef.current = null;
      cy.batch(() => {
        cy.elements().removeClass(FOCUS_CLASSES);

        if (highlightSet.size > 0) {
          cy.nodes().filter((node) => highlightSet.has(node.id())).addClass('highlighted');
        }
        if (markedId) cy.getElementById(markedId).addClass('mark');

        const selected = selectedId ? cy.getElementById(selectedId) : cy.collection();
        const hovered = hoveredRef.current ? cy.getElementById(hoveredRef.current) : cy.collection();
        if (selected.nonempty()) selected.addClass('selected-record');
        if (hovered.nonempty() && !hovered.same(selected)) hovered.addClass('hovered');

        const focus = hovered.nonempty() ? hovered : selected;
        if (focus.nonempty()) {
          const hood = focus.closedNeighborhood();
          cy.elements().not(hood).addClass('dim');
          hood.nodes().addClass('focus-label');
          const active = focus.connectedEdges();
          active.addClass('active');
          captionedRef.current = captionEdges(active).addClass('labelled');
        } else if (matchIds && matchIds.size > 0) {
          cy.nodes().forEach((node) => {
            if (matchIds.has(node.id())) node.addClass('match');
            else node.addClass('dim');
          });
          cy.edges().addClass('dim');
        } else if (highlightSet.size > 0) {
          cy.nodes().not('.highlighted').addClass('soft-dim');
          cy.edges().addClass('soft-dim');
        }
      });
    };
    emphasisRef.current();
    // highlightedIds is tracked through highlightKey so a new array with the same ids does not re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, highlightKey, markedId, matchIds, elements]);

  // ── Keep the selection clear of overlays ─────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selectedId) return;
    const node = cy.getElementById(selectedId);
    if (node.empty()) return;
    const position = node.renderedPosition();
    const margin = 56;
    const maxX = cy.width() - latest.current.insetRight - margin;
    const maxY = cy.height() - margin;
    const dx = position.x < margin ? margin - position.x : position.x > maxX ? maxX - position.x : 0;
    const dy = position.y < margin ? margin - position.y : position.y > maxY ? maxY - position.y : 0;
    if (dx !== 0 || dy !== 0) {
      cy.animate({ panBy: { x: dx, y: dy } }, { duration: latest.current.reducedMotion ? 0 : 240 });
    }
  }, [selectedId, elements]);

  const zoomBy = useCallback((factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    const level = Math.min(Math.max(cy.zoom() * factor, cy.minZoom()), cy.maxZoom());
    cy.zoom({ level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }, []);

  // ── Imperative controls ──────────────────────────────────
  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => zoomBy(1.3),
      zoomOut: () => zoomBy(1 / 1.3),
      fit: () => cyRef.current?.fit(undefined, 48),
      relayout: () => runLayout(true),
    }),
    [runLayout, zoomBy],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === '+' || event.key === '=') zoomBy(1.3);
    else if (event.key === '-') zoomBy(1 / 1.3);
    else if (event.key === '0') cyRef.current?.fit(undefined, 48);
    else return;
    event.preventDefault();
  };

  return (
    <div
      ref={containerRef}
      className={styles.canvas}
      role="application"
      aria-label={label}
      aria-roledescription="relationship graph"
      tabIndex={0}
      onKeyDown={onKeyDown}
      data-testid="graph-canvas"
      data-records={nodes.length}
      data-relationships={edges.length}
    />
  );
});
