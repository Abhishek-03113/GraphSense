import { create } from 'zustand';
import { ApiError } from '../lib/api/client';
import { sendChatMessage } from '../lib/api/queries';
import type { ChatResponse } from '../lib/api/schemas';

export interface RecordRef {
  id: string;
  type: string;
  label: string;
}

export interface Turn {
  id: string;
  question: string;
  status: 'pending' | 'done' | 'failed';
  askedAt: number;
  answer?: string;
  sql?: string | null;
  rows?: Record<string, unknown>[] | null;
  rowCount?: number;
  records?: RecordRef[];
  /** Server-side error code, e.g. "guardrail" or "sql_generation_failed". */
  errorCode?: string | null;
  /** Set when the request itself failed (offline, server error). */
  requestError?: { message: string; offline: boolean };
}

interface AskState {
  turns: Turn[];
  /** Text waiting in the composer, shared so other screens can prefill it. */
  draft: string;
  setDraft: (draft: string) => void;
  send: (question: string) => Promise<void>;
  retry: (turnId: string) => Promise<void>;
  reset: () => void;
}

let counter = 0;
const nextId = () => `turn-${Date.now()}-${(counter += 1)}`;

function recordsFrom(response: ChatResponse): RecordRef[] {
  const seen = new Set<string>();
  const out: RecordRef[] = [];
  const add = (id: string, type: string, label: string) => {
    if (seen.has(id)) return;
    seen.add(id);
    out.push({ id, type, label });
  };
  for (const node of response.graph_nodes) {
    add(node.id, node.type, node.label ?? node.id.slice(node.id.indexOf(':') + 1));
  }
  if (out.length === 0) {
    for (const entity of response.entities) {
      const value = entity.value ?? entity.id;
      add(entity.id.includes(':') ? entity.id : `${entity.type}:${value}`, entity.type, value);
    }
  }
  return out;
}

export const useAsk = create<AskState>((set, get) => {
  const run = async (turnId: string, question: string) => {
    try {
      const response = await sendChatMessage(question);
      set((state) => ({
        turns: state.turns.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                status: 'done',
                answer: response.answer,
                sql: response.sql ?? null,
                rows: response.data ?? null,
                rowCount: response.row_count ?? response.data?.length ?? 0,
                records: recordsFrom(response),
                errorCode: response.error ?? null,
              }
            : turn,
        ),
      }));
    } catch (error) {
      const offline = error instanceof ApiError && error.isNetwork;
      const message = error instanceof Error ? error.message : 'Something went wrong.';
      set((state) => ({
        turns: state.turns.map((turn) =>
          turn.id === turnId ? { ...turn, status: 'failed', requestError: { message, offline } } : turn,
        ),
      }));
    }
  };

  return {
    turns: [],
    draft: '',
    setDraft: (draft) => set({ draft }),
    send: async (question) => {
      const text = question.trim();
      if (!text || get().turns.some((turn) => turn.status === 'pending')) return;
      const turn: Turn = { id: nextId(), question: text, status: 'pending', askedAt: Date.now() };
      set((state) => ({ turns: [...state.turns, turn], draft: '' }));
      await run(turn.id, text);
    },
    retry: async (turnId) => {
      const turn = get().turns.find((candidate) => candidate.id === turnId);
      if (!turn || get().turns.some((candidate) => candidate.status === 'pending')) return;
      set((state) => ({
        turns: state.turns.map((candidate) =>
          candidate.id === turnId ? { ...candidate, status: 'pending', requestError: undefined } : candidate,
        ),
      }));
      await run(turnId, turn.question);
    },
    reset: () => set({ turns: [], draft: '' }),
  };
});
