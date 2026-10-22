import { create } from 'zustand';

const SIDEBAR_KEY = 'graphsense.sidebar-collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_KEY, value ? '1' : '0');
  } catch {
    /* storage unavailable: the preference simply is not remembered */
  }
}

interface WorkspaceState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  /** Record ids to emphasise on the Explore canvas, usually set from an Ask answer. */
  highlightedIds: string[];
  setHighlightedIds: (ids: string[]) => void;
}

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  sidebarCollapsed: readCollapsed(),
  toggleSidebar: () => {
    const next = !get().sidebarCollapsed;
    writeCollapsed(next);
    set({ sidebarCollapsed: next });
  },
  paletteOpen: false,
  setPaletteOpen: (open) => set({ paletteOpen: open }),
  highlightedIds: [],
  setHighlightedIds: (ids) => set({ highlightedIds: ids }),
}));
