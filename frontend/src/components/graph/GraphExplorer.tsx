import React, { useEffect, useRef, useMemo, useCallback } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import type { Core, EventObject, LayoutOptions, NodeSingular } from 'cytoscape';
import { useGraphStore } from '../../store/useGraphStore';
import { NODE_TYPE_COLORS, DEFAULT_NODE_COLOR } from '../../constants/graph';
import type { GraphData } from '../../types/graph';

// @ts-expect-error - cytoscape-cose-bilkent does not have TypeScript definitions
import coseBilkent from 'cytoscape-cose-bilkent';

cytoscape.use(coseBilkent);

const CSS_CLASSES = {
  FOCUSED: 'focused',
  DIMMED: 'dimmed',
  SELECTED: 'selected',
  CHAT_HIGHLIGHT: 'chat-highlight',
} as const;

const LAYOUT_OPTIONS = {
  name: 'cose-bilkent' as const,
  animate: 'end' as const,
  animationDuration: 500,
  nodeRepulsion: 14000,
  idealEdgeLength: 90,
  edgeElasticity: 0.04,
  gravity: 0.12,
  gravityRange: 5.0,
  numIter: 3000,
  tile: false,
  randomize: true,
  nestingFactor: 0.1,
};

interface Props {
  data: GraphData;
}

export const GraphExplorer: React.FC<Props> = ({ data }) => {
  const cyRef = useRef<Core | null>(null);
  const { setSelectedNode, highlightedEntities } = useGraphStore();

  // ── Degree map ────────────────────────────────────────────
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
      const MIN = 5;
      const MAX = 16;
      if (maxDegree === 0) return MIN;
      return MIN + (degree / maxDegree) * (MAX - MIN);
    },
    [degreeMap, maxDegree],
  );

  // ── Elements ──────────────────────────────────────────────
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

  // ── Stylesheet ────────────────────────────────────────────
  const stylesheet = useMemo(
    () =>
      [
        {
          selector: 'node',
          css: {
            label: '',
            'background-color': (node: NodeSingular) =>
              NODE_TYPE_COLORS[node.data('type')] || DEFAULT_NODE_COLOR,
            'background-opacity': 0.9,
            width: (node: NodeSingular) => getNodeSize(node.data('id')),
            height: (node: NodeSingular) => getNodeSize(node.data('id')),
            'border-width': 0,
            'overlay-padding': 4,
            'transition-property':
              'background-opacity, width, height, border-width, border-color, opacity',
            'transition-duration': '200ms',
          },
        },
        {
          selector: 'edge',
          css: {
            width: 0.4,
            'line-color': '#1e293b',
            'target-arrow-color': '#1e293b',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.25,
            'curve-style': 'bezier',
            label: '',
            opacity: 0.12,
            'transition-property': 'line-color, width, opacity, target-arrow-color',
            'transition-duration': '200ms',
          },
        },
        // Hover focus
        {
          selector: `node.${CSS_CLASSES.FOCUSED}`,
          css: {
            label: 'data(label)',
            'font-family': "'Space Grotesk', system-ui, sans-serif",
            'font-size': '9px',
            'font-weight': 500,
            color: '#94a3b8',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 5,
            'background-opacity': 1,
            'border-width': 1.5,
            'border-color': '#6366f1',
            'z-index': 10,
          },
        },
        {
          selector: `edge.${CSS_CLASSES.FOCUSED}`,
          css: {
            'line-color': '#6366f1',
            'target-arrow-color': '#6366f1',
            width: 0.8,
            opacity: 0.45,
            'z-index': 10,
          },
        },
        {
          selector: `node.${CSS_CLASSES.DIMMED}`,
          css: { opacity: 0.05 },
        },
        {
          selector: `edge.${CSS_CLASSES.DIMMED}`,
          css: { opacity: 0.015 },
        },
        // Click selection
        {
          selector: `node.${CSS_CLASSES.SELECTED}`,
          css: {
            label: 'data(label)',
            'font-family': "'Space Grotesk', system-ui, sans-serif",
            'font-size': '11px',
            'font-weight': 600,
            color: '#e2e8f0',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 7,
            'background-opacity': 1,
            'border-width': 2,
            'border-color': '#818cf8',
            'z-index': 20,
          },
        },
        {
          selector: `edge.${CSS_CLASSES.SELECTED}`,
          css: {
            'line-color': '#818cf8',
            'target-arrow-color': '#818cf8',
            width: 1.5,
            opacity: 0.8,
            'z-index': 20,
          },
        },
        // Chat-referenced node highlight (amber ring — separate from click/hover state)
        {
          selector: `node.${CSS_CLASSES.CHAT_HIGHLIGHT}`,
          css: {
            label: 'data(label)',
            'font-family': "'Space Grotesk', system-ui, sans-serif",
            'font-size': '10px',
            'font-weight': 600,
            color: '#fbbf24',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 6,
            'background-opacity': 1,
            'border-width': 2.5,
            'border-color': '#f59e0b',
            'z-index': 30,
          },
        },
      ] as cytoscape.StylesheetCSS[],
    [getNodeSize],
  );

  // ── Hover: highlight neighbours ───────────────────────────
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

  // ── Click: isolate neighbourhood + inspector ──────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const clearSelection = () => {
      cy.elements().removeClass(`${CSS_CLASSES.SELECTED} ${CSS_CLASSES.DIMMED}`);
    };

    const handleTap = (evt: EventObject) => {
      const node = evt.target;
      if (!node.isNode()) return;

      clearSelection();
      cy.elements().removeClass(CSS_CLASSES.FOCUSED);

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
        cy.elements().removeClass(CSS_CLASSES.CHAT_HIGHLIGHT);
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

  // ── Chat entity highlighting (amber ring, separate from click/hover) ──
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Always clear previous chat highlights first
    cy.elements().removeClass(CSS_CLASSES.CHAT_HIGHLIGHT);
    cy.elements().removeClass(CSS_CLASSES.DIMMED);

    if (highlightedEntities.length === 0) return;

    // Find nodes matching highlighted entity IDs
    const matchedNodes = cy.nodes().filter((n) => highlightedEntities.includes(n.data('id')));
    if (matchedNodes.length === 0) return;

    matchedNodes.addClass(CSS_CLASSES.CHAT_HIGHLIGHT);
    cy.elements().not(matchedNodes.closedNeighborhood()).addClass(CSS_CLASSES.DIMMED);

    // Fit view to highlighted nodes
    cy.animate({ fit: { eles: matchedNodes, padding: 60 } }, { duration: 500 });
  }, [highlightedEntities]);

  // ── Layout ────────────────────────────────────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const layout = cy.layout(LAYOUT_OPTIONS as LayoutOptions);
    layout.run();
    return () => {
      layout.stop();
    };
  }, [data]);

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

      <div className="graph-canvas-controls">
        <button
          type="button"
          onClick={handleFitView}
          title="Fit all nodes in view"
          aria-label="Fit view"
        >
          &#x2B1C;
        </button>
      </div>
    </div>
  );
};
