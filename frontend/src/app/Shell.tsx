import { Suspense, useEffect, useRef, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { CommandPalette } from '../components/ui/CommandPalette';
import { Skeleton } from '../components/ui/Skeleton';
import { useWorkspace } from '../store/workspace';
import { Sidebar } from './Sidebar';
import { useCommandItems } from './useCommandItems';
import styles from './Shell.module.css';

function PageFallback() {
  return (
    <div className={styles.fallback} role="status" aria-busy="true" aria-label="Loading page">
      <Skeleton width={220} height={28} />
      <div style={{ height: 12 }} />
      <Skeleton width={360} height={16} />
    </div>
  );
}

/** Mounted only while open, so every opening starts with an empty search. */
function PaletteHost({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const { items, busy } = useCommandItems(query, true);
  return <CommandPalette open onClose={onClose} items={items} query={query} onQueryChange={setQuery} busyText={busy} />;
}

/** App frame: sidebar, routed page, and the global command palette. */
export function Shell() {
  const mainRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const paletteOpen = useWorkspace((s) => s.paletteOpen);
  const setPaletteOpen = useWorkspace((s) => s.setPaletteOpen);

  // After navigating, move focus to the page so keyboard and screen reader users start at the top of it.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [pathname]);

  // Ctrl/Cmd+K toggles the palette from anywhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen(!useWorkspace.getState().paletteOpen);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setPaletteOpen]);

  return (
    <div className={styles.shell}>
      <a href="#main" className="gs-skip-link">Skip to content</a>
      <Sidebar />
      <main id="main" ref={mainRef} className={styles.main} tabIndex={-1}>
        <Suspense fallback={<PageFallback />}>
          <Outlet />
        </Suspense>
      </main>
      {paletteOpen && <PaletteHost onClose={() => setPaletteOpen(false)} />}
    </div>
  );
}
