import { PanelLeftClose, PanelLeftOpen, Search } from 'lucide-react';
import { Link, NavLink } from 'react-router-dom';
import { IconButton } from '../components/ui/Button';
import { Kbd } from '../components/ui/Kbd';
import { Skeleton } from '../components/ui/Skeleton';
import { Tooltip } from '../components/ui/Tooltip';
import { useHealth } from '../lib/api/queries';
import { useMediaQuery } from '../lib/hooks';
import { SHORTCUT_LABEL } from '../lib/platform';
import { useSchema } from '../lib/schema';
import { useWorkspace } from '../store/workspace';
import { NAV } from './nav';
import styles from './Sidebar.module.css';

function ConnectionStatus() {
  const health = useHealth();
  const ok = health.data?.status === 'ok';
  const state = health.isPending ? 'wait' : ok ? 'ok' : 'bad';
  const text = state === 'wait' ? 'Checking connection' : state === 'ok' ? 'Connected' : 'Can’t reach server';
  const dotClass = state === 'ok' ? styles.dotOk : state === 'bad' ? styles.dotBad : styles.dotWait;
  return (
    <div className={styles.status} role="status">
      <span className={[styles.dot, dotClass].join(' ')} aria-hidden="true" />
      <span className={styles.statusText}>{text}</span>
      <span className="gs-sr-only">{`Connection: ${text}`}</span>
    </div>
  );
}

export function Sidebar() {
  const collapsedPref = useWorkspace((s) => s.sidebarCollapsed);
  const toggleSidebar = useWorkspace((s) => s.toggleSidebar);
  const setPaletteOpen = useWorkspace((s) => s.setPaletteOpen);
  const narrow = useMediaQuery('(max-width: 900px)');
  const collapsed = collapsedPref || narrow;
  const { schema, status } = useSchema();

  return (
    <aside className={[styles.sidebar, collapsedPref ? styles.collapsed : ''].filter(Boolean).join(' ')} aria-label="Sidebar">
      <div className={styles.brand}>
        <Link to="/" className={styles.wordmark} aria-label="GraphSense home">
          <span className={styles.full}>GraphSense</span>
          <span className={styles.short} aria-hidden="true">GS</span>
        </Link>
        <span className={styles.toggle}>
          <IconButton
            label={collapsedPref ? 'Expand sidebar' : 'Collapse sidebar'}
            tooltipSide="right"
            icon={collapsedPref ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            aria-expanded={!collapsedPref}
            onClick={toggleSidebar}
          />
        </span>
      </div>

      <Tooltip content={`Search (${SHORTCUT_LABEL})`} side="right" disabled={!collapsed} fill>
        <button type="button" className={styles.searchTrigger} onClick={() => setPaletteOpen(true)} aria-label="Search and jump to…" aria-keyshortcuts="Control+K Meta+K">
          <Search size={16} aria-hidden="true" />
          <span className={styles.searchLabel}>Search</span>
          <span className={styles.searchKbd}><Kbd>{SHORTCUT_LABEL}</Kbd></span>
        </button>
      </Tooltip>

      <nav className={styles.nav} aria-label="Main">
        <ul className={styles.navList}>
          {NAV.map((entry) => (
            <li key={entry.to}>
              <Tooltip content={entry.label} side="right" disabled={!collapsed} fill>
                <NavLink to={entry.to} end={entry.end} className={styles.link} aria-label={entry.label}>
                  <entry.icon className={styles.linkIcon} size={20} aria-hidden="true" />
                  <span className={styles.linkLabel}>{entry.label}</span>
                </NavLink>
              </Tooltip>
            </li>
          ))}
        </ul>
      </nav>

      <div className={styles.footer}>
        <span className={styles.datasetLabel}>Dataset</span>
        {status === 'loading' ? (
          <Skeleton width={120} height={16} />
        ) : (
          <span className={styles.datasetName} title={schema.domain.name}>{status === 'error' ? 'Not available' : schema.domain.name}</span>
        )}
        <ConnectionStatus />
      </div>
    </aside>
  );
}
