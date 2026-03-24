import React, { useEffect, useRef } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import type { Core, StylesheetCSS, EventObject, NodeSingular } from 'cytoscape';
import { useGraphStore } from '../../store/useGraphStore';
import type { GraphData } from '../../types/graph';

import dagre from 'cytoscape-dagre';

cytoscape.use(dagre);

interface Props {
  data: GraphData;
}

export const GraphExplorer: React.FC<Props> = ({ data }) => {
  const cyRef = useRef<Core | null>(null);
  const { setSelectedNode, layoutMode } = useGraphStore();

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
        label: edge.type 
      }
    }))
  ];

  const stylesheet: StylesheetCSS[] = [
    {
      selector: 'node',
      css: {
        'label': 'data(label)',
        'background-color': (node: NodeSingular) => {
          const type = node.data('type');
          if (type === 'SalesOrder') return '#79c0ff';
          if (type === 'Delivery') return '#d2a8ff';
          if (type === 'BillingDocument') return '#ffa657';
          if (type === 'Payment') return '#7ee787';
          return '#8b949e';
        },
        'color': '#c9d1d9',
        'font-size': '12px',
        'text-valign': 'center',
        'text-halign': 'right',
        'text-margin-x': 5,
        'width': 40,
        'height': 40,
        'border-width': 2,
        'border-color': '#30363d',
        'overlay-padding': 6
      }
    },
    {
      selector: 'edge',
      css: {
        'width': 2,
        'line-color': '#30363d',
        'target-arrow-color': '#30363d',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '10px',
        'color': '#8b949e',
        'text-rotation': 'autorotate',
        'text-margin-y': -10
      }
    },
    {
      selector: 'node:selected',
      css: {
        'border-width': 4,
        'border-color': '#58a6ff',
        'width': 45,
        'height': 45
      }
    }
  ];

  useEffect(() => {
    if (cyRef.current) {
      cyRef.current.layout({ name: layoutMode, animate: true } as any).run();
    }
  }, [layoutMode, data]);

  return (
    <div className="graph-container">
      <CytoscapeComponent
        elements={elements}
        style={{ width: '100%', height: '100%', position: 'absolute' }}
        stylesheet={stylesheet}
        cy={(cy: Core) => {
          cyRef.current = cy;
          cy.on('tap', 'node', (evt: EventObject) => {
            const node = evt.target;
            setSelectedNode({
              id: node.data('id'),
              type: node.data('type'),
              label: node.data('label'),
              properties: node.data('properties')
            });
          });
          cy.on('tap', (evt: EventObject) => {
            if (evt.target === cy) {
              setSelectedNode(null);
            }
          });
        }}
        layout={{ name: layoutMode } as any}
      />
      
      {/* Layout Controls Overlay */}
      <div style={{ 
        position: 'absolute', 
        bottom: '20px', 
        left: '20px', 
        zIndex: 5,
        display: 'flex',
        gap: '8px'
      }}>
        {['cose', 'concentric'].map(mode => (
          <button 
            key={mode}
            onClick={() => useGraphStore.getState().setLayoutMode(mode as any)}
            style={{
              padding: '6px 12px',
              backgroundColor: layoutMode === mode ? 'var(--accent-color)' : 'var(--panel-bg)',
              color: layoutMode === mode ? '#000' : 'var(--text-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.8rem',
              fontWeight: 600,
              textTransform: 'uppercase'
            }}
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  );
};
