import { LayoutGrid, MessageSquareText, Network, Route, Rows3, Workflow, type LucideIcon } from 'lucide-react';

export interface NavEntry {
  to: string;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Match only the exact path (used for Overview). */
  end?: boolean;
}

export const NAV: NavEntry[] = [
  { to: '/', label: 'Overview', description: 'Dataset summary and shortcuts', icon: LayoutGrid, end: true },
  { to: '/explore', label: 'Explore', description: 'See records and how they connect', icon: Network },
  { to: '/ask', label: 'Ask', description: 'Ask questions in plain language', icon: MessageSquareText },
  { to: '/flows', label: 'Flows', description: 'Follow how work moves through the process', icon: Workflow },
  { to: '/trace', label: 'Trace', description: 'Follow one record from start to finish', icon: Route },
  { to: '/records', label: 'Records', description: 'Browse records by type', icon: Rows3 },
];
