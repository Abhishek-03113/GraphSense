import { create } from 'zustand';
import type { GraphNode } from '../types/graph';

interface GraphState {
  selectedNode: GraphNode | null;
  layoutMode: 'cose-bilkent' | 'concentric' | 'dagre';
  isInspectorOpen: boolean;

  // Actions
  setSelectedNode: (node: GraphNode | null) => void;
  setLayoutMode: (mode: 'cose-bilkent' | 'concentric' | 'dagre') => void;
  toggleInspector: (open?: boolean) => void;
}

export const useGraphStore = create<GraphState>((set) => ({
  selectedNode: null,
  layoutMode: 'cose-bilkent',
  isInspectorOpen: false,

  setSelectedNode: (node) => set({
    selectedNode: node,
    isInspectorOpen: node !== null
  }),

  setLayoutMode: (mode) => set({ layoutMode: mode }),

  toggleInspector: (open) => set((state) => ({
    isInspectorOpen: open !== undefined ? open : !state.isInspectorOpen
  })),
}));
