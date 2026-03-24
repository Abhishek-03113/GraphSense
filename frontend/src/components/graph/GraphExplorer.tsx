import React, { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import type { Core, StylesheetCSS, EventObject, NodeSingular } from 'cytoscape';
import { useGraphStore } from '../../store/useGraphStore';
import type { GraphData } from '../../types/graph';

import dagre from 'cytoscape-dagre';
// @ts-ignore - cytoscape-cose-bilkent does not have TypeScript definitions
import cosBilkent from 'cytoscape-cose-bilkent';

cytoscape.use(dagre);
cytoscape.use(cosBilkent);

// Cytoscape event names and CSS class constants
const CYTOSCAPE_EVENTS = {
  MOUSEOVER: 'mouseover',
  MOUSEOUT: 'mouseout',
  TAP: 'tap'
} as const;

const CSS_CLASSES = {
  HIGHLIGHTED: 'highlighted',
  DIMMED: 'dimmed'
} as const;

interface Props {
  data: GraphData;
}

export const GraphExplorer: React.FC<Props> = ({ data }) => {
  const cyRef = useRef<Core | null>(null);
  const { setSelectedNode, layoutMode, setLayoutMode } = useGraphStore();
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Map node types to colors (matching CSS variables)
  const NODE_TYPE_COLORS: Record<string, string> = {
    'SalesOrder': '#79c0ff',
    'SalesOrderItem': '#79c0ff',
    'Delivery': '#d2a8ff',
    'DeliveryItem': '#d2a8ff',
    'BillingDocument': '#ffa657',
    'BillingItem': '#ffa657',
    'Payment': '#7ee787',
    'JournalEntry': '#7ee787',
    'Customer': '#56d364',
    'Product': '#f0883e',
    'Plant': '#79c0ff'
  };

  // Compute degree (number of connections) for each node for sizing
  const degreeMap = useMemo(() => {
    const degrees = new Map<string, number>();
    data.nodes.forEach(node => degrees.set(node.id, 0));
    data.edges.forEach(edge => {
      degrees.set(edge.source, (degrees.get(edge.source) || 0) + 1);
      degrees.set(edge.target, (degrees.get(edge.target) || 0) + 1);
    });
    return degrees;
  }, [data]);

  // Compute max degree once to avoid O(n) calculation per node
  const maxDegree = useMemo(() => {
    const values = Array.from(degreeMap.values());
    return values.length > 0 ? Math.max(...values) : 0;
  }, [degreeMap]);

  // Helper to compute node size based on degree (O(1) with precomputed maxDegree)
  const getNodeSize = useCallback((nodeId: string): number => {
    const degree = degreeMap.get(nodeId) || 0;
    const minSize = 30;
    const maxSize = 80;
    if (maxDegree === 0) return minSize;
    return minSize + (degree / maxDegree) * (maxSize - minSize);
  }, [degreeMap, maxDegree]);

  // Pre-compute color map to avoid switch statement in hot path
  const colorMap = useMemo(() => {
    const colors = new Map<string, string>();
    data.nodes.forEach(node => {
      colors.set(node.id, NODE_TYPE_COLORS[node.type] || '#8b949e');
    });
    return colors;
  }, [data.nodes]);

  const elements = [
    ...data.nodes.map(node => ({
      data: {
        id: node.id,
        label: node.label,
        type: node.type,
        properties: node.properties
      }
    })),
    ...data.edges.map(edge => ({
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.type,
        properties: edge.properties
      }
    }))
  ];

  const stylesheet: StylesheetCSS[] = [
    // Base node styling with dynamic sizing
    {
      selector: 'node',
      css: {
        'label': 'data(label)',
        'background-color': (node: NodeSingular) => colorMap.get(node.data('id')) || '#8b949e',
        'background-opacity': 0.9,
        'color': '#c9d1d9',
        'font-size': '11px',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-margin-y': 0,
        'width': (node: NodeSingular) => `${getNodeSize(node.data('id'))}px`,
        'height': (node: NodeSingular) => `${getNodeSize(node.data('id'))}px`,
        'border-width': 2,
        'border-color': '#30363d',
        'overlay-padding': 6
      } as any
    },
    // Base edge styling
    {
      selector: 'edge',
      css: {
        'width': 2,
        'line-color': '#30363d',
        'target-arrow-color': '#30363d',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '9px',
        'color': '#8b949e',
        'text-rotation': 'autorotate',
        'text-margin-y': -8,
        'opacity': 0.6,
        'transition-property': 'line-color,width,opacity',
        'transition-duration': '200ms'
      }
    },
    // Selected node with glow effect
    {
      selector: 'node:selected',
      css: {
        'border-width': 3,
        'border-color': '#58a6ff',
        'shadow-blur': 20,
        'shadow-color': '#58a6ff',
        'shadow-opacity': 0.8,
        'shadow-offset-x': 0,
        'shadow-offset-y': 0
      } as any
    },
    // Highlighted nodes (hovered node + connected)
    {
      selector: `node.${CSS_CLASSES.HIGHLIGHTED}`,
      css: {
        'border-color': '#58a6ff',
        'border-width': 3,
        'background-opacity': 1
      }
    },
    // Dimmed nodes (not connected to hovered)
    {
      selector: `node.${CSS_CLASSES.DIMMED}`,
      css: {
        'opacity': 0.15
      }
    },
    // Highlighted edges
    {
      selector: `edge.${CSS_CLASSES.HIGHLIGHTED}`,
      css: {
        'line-color': '#58a6ff',
        'width': 3,
        'opacity': 1
      }
    },
    // Dimmed edges
    {
      selector: `edge.${CSS_CLASSES.DIMMED}`,
      css: {
        'opacity': 0.05
      }
    }
  ];

  // Handle hover interactions
  useEffect(() => {
    if (!cyRef.current) return;

    const cy = cyRef.current;

    const handleMouseover = (evt: EventObject) => {
      const node = evt.target;
      if (!node.isNode()) return;

      const nodeId = node.id();

      // Idempotence guard: only update if hovering a different node
      if (hoveredNodeId === nodeId) return;
      setHoveredNodeId(nodeId);

      // Get all directly connected nodes and edges
      const connectedNodes = node.connectedEdges().connectedNodes();
      const connectedEdges = node.connectedEdges();

      // Highlight hovered node and connected elements
      node.addClass(CSS_CLASSES.HIGHLIGHTED);
      connectedNodes.addClass(CSS_CLASSES.HIGHLIGHTED);
      connectedEdges.addClass(CSS_CLASSES.HIGHLIGHTED);

      // Dim unconnected elements (optimize query by excluding connected in one go)
      const unconnected = cy.elements().not(node).not(connectedNodes).not(connectedEdges);
      unconnected.addClass(CSS_CLASSES.DIMMED);
    };

    const handleMouseout = () => {
      if (hoveredNodeId === null) return; // Guard: only clear if something was highlighted
      setHoveredNodeId(null);

      cy.nodes().removeClass(`${CSS_CLASSES.HIGHLIGHTED} ${CSS_CLASSES.DIMMED}`);
      cy.edges().removeClass(`${CSS_CLASSES.HIGHLIGHTED} ${CSS_CLASSES.DIMMED}`);
    };

    cy.on(CYTOSCAPE_EVENTS.MOUSEOVER, 'node', handleMouseover);
    cy.on(CYTOSCAPE_EVENTS.MOUSEOUT, 'node', handleMouseout);

    return () => {
      cy.off(CYTOSCAPE_EVENTS.MOUSEOVER, 'node', handleMouseover);
      cy.off(CYTOSCAPE_EVENTS.MOUSEOUT, 'node', handleMouseout);
    };
  }, [hoveredNodeId]);

  // Handle node selection
  useEffect(() => {
    if (!cyRef.current) return;

    const cy = cyRef.current;

    const handleNodeTap = (evt: EventObject) => {
      const node = evt.target;
      if (!node.isNode()) return;
      setSelectedNode({
        id: node.data('id'),
        type: node.data('type'),
        label: node.data('label'),
        properties: node.data('properties')
      });
    };

    const handleCanvasTap = (evt: EventObject) => {
      if (evt.target === cy) {
        setSelectedNode(null);
      }
    };

    cy.on(CYTOSCAPE_EVENTS.TAP, 'node', handleNodeTap);
    cy.on(CYTOSCAPE_EVENTS.TAP, handleCanvasTap);

    return () => {
      cy.off(CYTOSCAPE_EVENTS.TAP, 'node', handleNodeTap);
      cy.off(CYTOSCAPE_EVENTS.TAP, handleCanvasTap);
    };
  }, [setSelectedNode]);

  // Re-run layout on layoutMode change or data change
  useEffect(() => {
    if (cyRef.current) {
      const layoutOptions: any = {
        name: layoutMode,
        animate: true,
        animationDuration: 300,
        animationEasing: 'ease-out'
      };

      // Add layout-specific options
      if (layoutMode === 'cose-bilkent') {
        Object.assign(layoutOptions, {
          nodeSpacing: 10,
          gravity: 0.05,
          gravityRange: Infinity,
          friction: 0.9,
          numIter: 1000,
          initialTemp: 200,
          coolingFactor: 0.95,
          minTemp: 1.0,
          randomize: false
        });
      } else if (layoutMode === 'concentric') {
        Object.assign(layoutOptions, {
          minNodeSpacing: 40,
          concentric: (node: NodeSingular) => {
            return degreeMap.get(node.data('id')) || 0;
          },
          levelWidth: (height: number) => height * 0.8,
          equidistant: false
        });
      }

      cyRef.current.layout(layoutOptions).run();
    }
  }, [layoutMode, data, degreeMap, maxDegree]);

  // Canvas controls handlers
  const handleFitView = () => {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 30);
    }
  };

  const handleCenterOnSelected = () => {
    if (cyRef.current) {
      const selected = cyRef.current.$(':selected');
      if (selected.length > 0) {
        cyRef.current.center(selected.first());
      }
    }
  };

  return (
    <div className="graph-container">
      <CytoscapeComponent
        elements={elements}
        style={{ width: '100%', height: '100%', position: 'absolute' }}
        stylesheet={stylesheet}
        cy={(cy: Core) => {
          cyRef.current = cy;
        }}
        layout={{ name: layoutMode } as any}
        wheelSensitivity={0.1}
      />

      {/* Top-right canvas controls */}
      <div className="graph-canvas-controls">
        <button
          onClick={handleFitView}
          title="Fit all nodes in view"
          aria-label="Fit view"
        >
          ◻
        </button>
        <button
          onClick={handleCenterOnSelected}
          title="Center on selected node"
          aria-label="Center selected"
        >
          ◎
        </button>
      </div>

      {/* Bottom-left layout controls */}
      <div className="graph-controls">
        {[
          { key: 'cose-bilkent', label: 'Force' },
          { key: 'concentric', label: 'Radial' },
          { key: 'dagre', label: 'Hierarchy' }
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setLayoutMode(key as any)}
            className={layoutMode === key ? 'active' : ''}
            title={`Switch to ${label} layout`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
};
