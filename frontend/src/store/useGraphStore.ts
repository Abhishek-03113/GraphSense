import { create } from 'zustand';
import type { GraphNode } from '../types/graph';

interface GraphState {
  selectedNode: GraphNode | null;
  layoutMode: 'cose-bilkent' | 'concentric' | 'dagre';
  isInspectorOpen: boolean;

  // Knowledge graph filter state
  typeFilter: string[];
  nodeLimit: number;
  searchQuery: string;

  // Actions
  setSelectedNode: (node: GraphNode | null) => void;
  setLayoutMode: (mode: 'cose-bilkent' | 'concentric' | 'dagre') => void;
  toggleInspector: (open?: boolean) => void;
  setTypeFilter: (types: string[]) => void;
  setNodeLimit: (limit: number) => void;
  setSearchQuery: (query: string) => void;
}

export const useGraphStore = create<GraphState>((set) => ({
  selectedNode: null,
  layoutMode: 'cose-bilkent',
  isInspectorOpen: false,
  typeFilter: [],
  nodeLimit: 20,
  searchQuery: '',

  setSelectedNode: (node) => set({
    selectedNode: node,
    isInspectorOpen: node !== null
  }),

  setLayoutMode: (mode) => set({ layoutMode: mode }),

  toggleInspector: (open) => set((state) => ({
    isInspectorOpen: open !== undefined ? open : !state.isInspectorOpen
  })),

  setTypeFilter: (types) => set({ typeFilter: types }),
  setNodeLimit: (limit) => set({ nodeLimit: limit }),
  setSearchQuery: (query) => set({ searchQuery: query }),
}));
