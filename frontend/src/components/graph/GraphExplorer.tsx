import React, { useEffect, useRef, useMemo, useCallback } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import type { Core, EventObject, LayoutOptions, NodeSingular } from 'cytoscape';
import { useGraphStore } from '../../store/useGraphStore';
import { NODE_TYPE_COLORS, DEFAULT_NODE_COLOR } from '../../constants/graph';
import type { GraphData } from '../../types/graph';

// @ts-ignore - cytoscape-cose-bilkent does not have TypeScript definitions
import coseBilkent from 'cytoscape-cose-bilkent';

cytoscape.use(coseBilkent);

const CSS_CLASSES = {
  FOCUSED: 'focused',
  DIMMED: 'dimmed',
  SELECTED: 'selected',
} as const;

// ─── Obsidian-style force-directed layout ──────────────────────────
// cose-bilkent accepts extra properties beyond base LayoutOptions;
// cast at call sites rather than on the constant.
const LAYOUT_OPTIONS = {
  name: 'cose-bilkent' as const,
  animate: 'end' as const,
  animationDuration: 400,
  nodeRepulsion: 12000,
  idealEdgeLength: 80,
  edgeElasticity: 0.05,
  gravity: 0.15,
  gravityRange: 5.0,
  numIter: 2500,
  tile: false,
  randomize: true,
  nestingFactor: 0.1,
};

interface Props {
  data: GraphData;
}

export const GraphExplorer: React.FC<Props> = ({ data }) => {
  const cyRef = useRef<Core | null>(null);
  const { setSelectedNode } = useGraphStore();

  // ── Degree map (for subtle size variance) ──────────────────────
  const degreeMap = useMemo(() => {
    const degrees = new Map<string, number>();
    data.nodes.forEach((n) => degrees.set(n.id, 0));
    data.edges.forEach((e) => {
      degrees.set(e.source, (degrees.get(e.source) || 0) + 1);
      degrees.set(e.target, (degrees.get(e.target) || 0) + 1);
    });
    return degrees;
  }, [data]);

  const maxDegree = useMemo(() => {
    const vals = Array.from(degreeMap.values());
    return vals.length > 0 ? Math.max(...vals) : 0;
  }, [degreeMap]);

  const getNodeSize = useCallback(
    (nodeId: string): number => {
      const degree = degreeMap.get(nodeId) || 0;
      const MIN = 6;
      const MAX = 18;
      if (maxDegree === 0) return MIN;
      return MIN + (degree / maxDegree) * (MAX - MIN);
    },
    [degreeMap, maxDegree],
  );

  // ── Elements ───────────────────────────────────────────────────
  const elements = useMemo(
    () => [
      ...data.nodes.map((node) => ({
        data: {
          id: node.id,
          label: node.label,
          type: node.type,
          properties: node.properties,
        },
      })),
      ...data.edges.map((edge) => ({
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.type,
          properties: edge.properties,
        },
      })),
    ],
    [data],
  );

  // ── Stylesheet (Obsidian-style: tiny dots, thin edges, no labels) ─
  const stylesheet = useMemo(
    () =>
      [
        {
          selector: 'node',
          css: {
            label: '',
            'background-color': (node: NodeSingular) =>
              NODE_TYPE_COLORS[node.data('type')] || DEFAULT_NODE_COLOR,
            'background-opacity': 0.85,
            width: (node: NodeSingular) => getNodeSize(node.data('id')),
            height: (node: NodeSingular) => getNodeSize(node.data('id')),
            'border-width': 0,
            'overlay-padding': 4,
            'transition-property':
              'background-opacity, width, height, border-width, border-color, opacity',
            'transition-duration': '150ms',
          },
        },
        {
          selector: 'edge',
          css: {
            width: 0.4,
            'line-color': '#30363d',
            'target-arrow-color': '#30363d',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.3,
            'curve-style': 'bezier',
            label: '',
            opacity: 0.08,
            'transition-property': 'line-color, width, opacity, target-arrow-color',
            'transition-duration': '150ms',
          },
        },
        // ── Hover focus: soft highlight ──────────────────────────
        {
          selector: `node.${CSS_CLASSES.FOCUSED}`,
          css: {
            label: 'data(label)',
            'font-size': '9px',
            color: '#8b949e',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 5,
            'background-opacity': 1,
            'border-width': 1,
            'border-color': '#58a6ff',
            'z-index': 10,
          },
        },
        {
          selector: `edge.${CSS_CLASSES.FOCUSED}`,
          css: {
            'line-color': '#58a6ff',
            'target-arrow-color': '#58a6ff',
            width: 1,
            opacity: 0.5,
            'z-index': 10,
          },
        },
        {
          selector: `node.${CSS_CLASSES.DIMMED}`,
          css: { opacity: 0.06 },
        },
        {
          selector: `edge.${CSS_CLASSES.DIMMED}`,
          css: { opacity: 0.02 },
        },
        // ── Click selection: strong isolate ──────────────────────
        {
          selector: `node.${CSS_CLASSES.SELECTED}`,
          css: {
            label: 'data(label)',
            'font-size': '11px',
            color: '#c9d1d9',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 7,
            'background-opacity': 1,
            'border-width': 2,
            'border-color': '#58a6ff',
            'z-index': 20,
          },
        },
        {
          selector: `edge.${CSS_CLASSES.SELECTED}`,
          css: {
            'line-color': '#58a6ff',
            'target-arrow-color': '#58a6ff',
            width: 1.8,
            opacity: 0.85,
            'z-index': 20,
          },
        },
      ] as cytoscape.StylesheetCSS[],
    [getNodeSize],
  );

  // ── Hover: highlight neighbours ─────────────────────────────────
  // Re-binds when data changes so handlers reference the current cy instance
  // after CytoscapeComponent remounts with new elements.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const handleMouseover = (evt: EventObject) => {
      const node = evt.target;
      if (!node.isNode()) return;

      const hood = node.closedNeighborhood();
      hood.addClass(CSS_CLASSES.FOCUSED);
      cy.elements().not(hood).addClass(CSS_CLASSES.DIMMED);
    };

    const handleMouseout = () => {
      cy.elements().removeClass(`${CSS_CLASSES.FOCUSED} ${CSS_CLASSES.DIMMED}`);
    };

    cy.on('mouseover', 'node', handleMouseover);
    cy.on('mouseout', 'node', handleMouseout);

    return () => {
      cy.off('mouseover', 'node', handleMouseover);
      cy.off('mouseout', 'node', handleMouseout);
    };
  }, [data]);

  // ── Click: isolate neighbourhood + inspector panel ──────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const clearSelection = () => {
      cy.elements().removeClass(
        `${CSS_CLASSES.SELECTED} ${CSS_CLASSES.DIMMED}`
      );
    };

    const handleTap = (evt: EventObject) => {
      const node = evt.target;
      if (!node.isNode()) return;

      clearSelection();
      // Also clear hover state to avoid conflict
      cy.elements().removeClass(`${CSS_CLASSES.FOCUSED}`);

      const hood = node.closedNeighborhood();
      hood.addClass(CSS_CLASSES.SELECTED);
      cy.elements().not(hood).addClass(CSS_CLASSES.DIMMED);

      setSelectedNode({
        id: node.data('id'),
        type: node.data('type'),
        label: node.data('label'),
        properties: node.data('properties'),
      });
    };

    const handleCanvasTap = (evt: EventObject) => {
      if (evt.target === cy) {
        clearSelection();
        setSelectedNode(null);
      }
    };

    cy.on('tap', 'node', handleTap);
    cy.on('tap', handleCanvasTap);

    return () => {
      cy.off('tap', 'node', handleTap);
      cy.off('tap', handleCanvasTap);
    };
  }, [setSelectedNode, data]);

  // ── Layout: re-run on data change ───────────────────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const layout = cy.layout(LAYOUT_OPTIONS as LayoutOptions);
    layout.run();
    return () => { layout.stop(); };
  }, [data]);

  // ── Canvas controls ─────────────────────────────────────────────
  const handleFitView = () => cyRef.current?.fit(undefined, 30);

  return (
    <div className="graph-container">
      <CytoscapeComponent
        elements={elements}
        style={{ width: '100%', height: '100%', position: 'absolute' }}
        stylesheet={stylesheet}
        cy={(cy: Core) => {
          cyRef.current = cy;
        }}
        layout={LAYOUT_OPTIONS as LayoutOptions}
        wheelSensitivity={0.15}
        minZoom={0.1}
        maxZoom={6}
      />

      {/* Top-right: fit view */}
      <div className="graph-canvas-controls">
        <button
          type="button"
          onClick={handleFitView}
          title="Fit all nodes in view"
          aria-label="Fit view"
        >
          ◻
        </button>
      </div>
    </div>
  );
};
