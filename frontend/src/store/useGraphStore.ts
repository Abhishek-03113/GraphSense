import { create } from 'zustand';
import type { GraphNode } from '../types/graph';

interface GraphState {
  selectedNode: GraphNode | null;
  isInspectorOpen: boolean;
  searchQuery: string;
  isChatOpen: boolean;
  highlightedEntities: string[];

  setSelectedNode: (node: GraphNode | null) => void;
  setSearchQuery: (query: string) => void;
  setChatOpen: (open: boolean) => void;
  setHighlightedEntities: (ids: string[]) => void;
}

export const useGraphStore = create<GraphState>((set) => ({
  selectedNode: null,
  isInspectorOpen: false,
  searchQuery: '',
  isChatOpen: false,
  highlightedEntities: [],

  setSelectedNode: (node) => set({
    selectedNode: node,
    isInspectorOpen: node !== null,
  }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setChatOpen: (open) => set({ isChatOpen: open }),

  setHighlightedEntities: (ids) => set({ highlightedEntities: ids }),
}));
