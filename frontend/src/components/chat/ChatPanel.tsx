import React, { useState, useRef, useEffect } from 'react';
import { Send, X, ChevronDown, ChevronUp, Database, Loader2, Sparkles, Layers } from 'lucide-react';
import { api, type ChatApiResponse, type GraphNodeRef } from '../../services/api';
import { useGraphStore } from '../../store/useGraphStore';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sql?: string | null;
  data?: Record<string, unknown>[] | null;
  entities?: { id: string; type: string; value: string }[];
  graphNodes?: GraphNodeRef[];
  error?: string | null;
  rowCount?: number;
  summary?: string;
  timestamp: number;
}

interface ChatPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ isOpen, onClose }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'Ask me anything about the SAP Order-to-Cash dataset — sales orders, deliveries, invoices, payments, customers, and products.',
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { setHighlightedEntities } = useGraphStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    // Clear stale highlights before new query
    setHighlightedEntities([]);

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const response: ChatApiResponse = await api.chat(trimmed);

      // Prefer LLM-structured graph_nodes; fall back to heuristic entities
      const graphNodes: GraphNodeRef[] =
        response.graph_nodes && response.graph_nodes.length > 0
          ? response.graph_nodes
          : (response.entities ?? []).map((e) => ({ id: e.id, type: e.type, label: e.value }));

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        sql: response.sql,
        data: response.data,
        entities: response.entities,
        graphNodes,
        error: response.error,
        rowCount: response.row_count,
        summary: response.summary,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // Highlight all extracted graph nodes automatically
      if (graphNodes.length > 0) {
        setHighlightedEntities(graphNodes.map((n) => n.id));
      }
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Failed to get a response. Please check that the backend is running and GEMINI_API_KEY is set.',
        error: (err as Error).message,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <aside className="chat-panel">
      <div className="chat-header">
        <div className="chat-header-title">
          <Database size={16} />
          <span>Query Assistant</span>
        </div>
        <button className="chat-close-btn" onClick={onClose} aria-label="Close chat">
          <X size={16} />
        </button>
      </div>

      <div className="chat-messages">
        {messages.map((msg) => (
          <div key={msg.id} className={`chat-message chat-message-${msg.role}`}>
            <div className="chat-bubble">
              <div className="chat-content">{msg.content}</div>

              {/* Data citation badge — shown when query returned results */}
              {msg.role === 'assistant' && msg.summary && !msg.error && (
                <DataCitation summary={msg.summary} rowCount={msg.rowCount ?? 0} />
              )}

              {msg.sql && <SqlBlock sql={msg.sql} />}
              {msg.data && msg.data.length > 0 && <DataTable data={msg.data} />}
              {msg.graphNodes && msg.graphNodes.length > 0 && (
                <EntityChips nodes={msg.graphNodes} onHighlight={setHighlightedEntities} />
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-bubble">
              <div className="chat-loading">
                <Loader2 size={14} className="spin" />
                <span>Analyzing your question...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          className="chat-input"
          type="text"
          placeholder="Ask about orders, invoices, customers..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isLoading}
        />
        <button
          className="chat-send-btn"
          type="submit"
          disabled={isLoading || !input.trim()}
          aria-label="Send message"
        >
          <Send size={16} />
        </button>
      </form>
    </aside>
  );
};

// ── Data citation badge ───────────────────────────────────────
const DataCitation: React.FC<{ summary: string; rowCount: number }> = ({ summary, rowCount }) => {
  const isEmpty = rowCount === 0;
  return (
    <div
      className="data-citation"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '0.74rem',
        color: isEmpty ? 'var(--text-muted)' : '#a78bfa',
        marginTop: '6px',
        marginBottom: '2px',
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      <Sparkles size={11} style={{ flexShrink: 0 }} />
      <span>{summary}</span>
    </div>
  );
};

// ── SQL collapsible block ─────────────────────────────────────
const SqlBlock: React.FC<{ sql: string }> = ({ sql }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="sql-block">
      <button
        className="sql-toggle"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <Database size={12} />
        <span>SQL Query</span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {expanded && <pre className="sql-code">{sql}</pre>}
    </div>
  );
};

// ── Data table ────────────────────────────────────────────────
const DataTable: React.FC<{ data: Record<string, unknown>[] }> = ({ data }) => {
  const [expanded, setExpanded] = useState(false);
  const columns = Object.keys(data[0] || {});
  const displayRows = data.slice(0, 10);

  return (
    <div className="data-table-container">
      <button
        className="sql-toggle"
        onClick={() => setExpanded(!expanded)}
        type="button"
      >
        <span>Results ({data.length} rows)</span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {expanded && (
        <div className="data-table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col}>{row[col] != null ? String(row[col]) : '—'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {data.length > 10 && (
            <div className="data-table-more">
              ...and {data.length - 10} more rows
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Entity type color map ─────────────────────────────────────
const ENTITY_TYPE_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  Invoice:      { bg: 'rgba(139,92,246,0.15)',  text: '#a78bfa', dot: '#8b5cf6' },
  SalesOrder:   { bg: 'rgba(59,130,246,0.15)',  text: '#60a5fa', dot: '#3b82f6' },
  Delivery:     { bg: 'rgba(16,185,129,0.15)',  text: '#34d399', dot: '#10b981' },
  JournalEntry: { bg: 'rgba(245,158,11,0.15)',  text: '#fbbf24', dot: '#f59e0b' },
  Payment:      { bg: 'rgba(236,72,153,0.15)',  text: '#f472b6', dot: '#ec4899' },
  Customer:     { bg: 'rgba(14,165,233,0.15)',  text: '#38bdf8', dot: '#0ea5e9' },
  Product:      { bg: 'rgba(168,85,247,0.15)',  text: '#c084fc', dot: '#a855f7' },
};
const DEFAULT_ENTITY_COLOR = { bg: 'rgba(100,116,139,0.15)', text: '#94a3b8', dot: '#64748b' };

// ── Entity chips ──────────────────────────────────────────────
const EntityChips: React.FC<{
  nodes: GraphNodeRef[];
  onHighlight: (ids: string[]) => void;
}> = ({ nodes, onHighlight }) => {
  const [showAll, setShowAll] = useState(false);
  const VISIBLE_MAX = 8;
  const visible = showAll ? nodes : nodes.slice(0, VISIBLE_MAX);
  const allIds = nodes.map((n) => n.id);

  // Group by type for the header summary
  const typeCounts = nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.type] = (acc[n.type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="entity-chips-wrapper">
      {/* Header row */}
      <div className="entity-chips-header">
        <Layers size={11} style={{ flexShrink: 0, color: '#94a3b8' }} />
        <span className="entity-chips-label">
          {Object.entries(typeCounts)
            .map(([type, count]) => `${count} ${type}${count > 1 ? 's' : ''}`)
            .join(' · ')}
        </span>
        <button
          className="entity-chip-highlight-all"
          type="button"
          title="Highlight all entities on the graph"
          onClick={() => onHighlight(allIds)}
        >
          Highlight all
        </button>
      </div>

      {/* Chips */}
      <div className="entity-chips">
        {visible.map((n) => {
          const colors = ENTITY_TYPE_COLORS[n.type] ?? DEFAULT_ENTITY_COLOR;
          return (
            <button
              key={n.id}
              className="entity-chip entity-chip-btn"
              title={`Highlight ${n.id} on graph`}
              type="button"
              onClick={() => onHighlight([n.id])}
              style={{
                background: colors.bg,
                color: colors.text,
                borderColor: colors.dot,
              }}
            >
              <span
                className="entity-chip-dot"
                style={{ background: colors.dot }}
              />
              <span className="entity-chip-type">{n.type}</span>
              <span className="entity-chip-value">{n.label}</span>
            </button>
          );
        })}
        {nodes.length > VISIBLE_MAX && (
          <button
            className="entity-chip entity-chip-more"
            type="button"
            onClick={() => setShowAll((s) => !s)}
          >
            {showAll ? 'Show less' : `+${nodes.length - VISIBLE_MAX} more`}
          </button>
        )}
      </div>
    </div>
  );
};
