import React, { useState, useRef, useEffect } from 'react';
import { Send, X, ChevronDown, ChevronUp, Database, Loader2 } from 'lucide-react';
import { api, type ChatApiResponse } from '../../services/api';
import { useGraphStore } from '../../store/useGraphStore';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sql?: string | null;
  data?: Record<string, unknown>[] | null;
  entities?: { id: string; type: string; value: string }[];
  error?: string | null;
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

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        sql: response.sql,
        data: response.data,
        entities: response.entities,
        error: response.error,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // Highlight referenced entities on the graph
      if (response.entities && response.entities.length > 0) {
        setHighlightedEntities(response.entities.map((e) => e.id));
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
              {msg.sql && <SqlBlock sql={msg.sql} />}
              {msg.data && msg.data.length > 0 && <DataTable data={msg.data} />}
              {msg.entities && msg.entities.length > 0 && (
                <EntityChips entities={msg.entities} />
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

// ── Entity chips ──────────────────────────────────────────────
const EntityChips: React.FC<{
  entities: { id: string; type: string; value: string }[];
}> = ({ entities }) => {
  const unique = entities.slice(0, 8);

  return (
    <div className="entity-chips">
      {unique.map((e) => (
        <span key={e.id} className="entity-chip" title={e.id}>
          {e.type}: {e.value}
        </span>
      ))}
      {entities.length > 8 && (
        <span className="entity-chip entity-chip-more">+{entities.length - 8} more</span>
      )}
    </div>
  );
};
