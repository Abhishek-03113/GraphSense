import type { AiState, DatasetPhase } from './context';

export interface StatusLine {
  /** Short text for the sidebar, e.g. "Ask is ready". */
  text: string;
  /** One sentence for hover and screen readers. */
  detail: string;
  /** ok: all good. limited: works with a caveat. off: not available. wait: in progress. */
  tone: 'ok' | 'limited' | 'off' | 'wait';
}

/** A one-line summary of what Ask can do, or null when the server does not report an AI state. */
export function summariseAi(ai: AiState): StatusLine | null {
  if (ai.mode === 'unknown') return null;
  if (ai.mode === 'disabled') {
    return { text: 'Ask is off', detail: 'Ask needs a language service that has not been connected to this server.', tone: 'off' };
  }
  if (ai.mode === 'degraded') {
    return { text: 'Ask is limited', detail: 'Ask is running in a simpler mode, so answers may be less precise.', tone: 'limited' };
  }
  if (ai.knowledge === 'missing') {
    return { text: 'Ask is limited', detail: 'Ask is on, but its notes about this dataset have not been prepared yet.', tone: 'limited' };
  }
  return { text: 'Ask is ready', detail: 'Ask can answer questions about this dataset.', tone: 'ok' };
}

/** A one-line summary of where the data stands when it is not simply ready, otherwise null. */
export function summariseData(phase: DatasetPhase): StatusLine | null {
  switch (phase) {
    case 'loading':
      return { text: 'Loading data', detail: 'The data is being loaded. This updates by itself.', tone: 'wait' };
    case 'empty':
      return { text: 'No data yet', detail: 'The data has not been loaded. Your administrator loads it.', tone: 'off' };
    case 'failed':
      return { text: 'Load didn’t finish', detail: 'The last data load did not finish. Your administrator can run it again.', tone: 'off' };
    default:
      return null;
  }
}
