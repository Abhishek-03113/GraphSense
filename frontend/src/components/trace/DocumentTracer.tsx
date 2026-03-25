import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../services/api';
import { GraphExplorer } from '../graph/GraphExplorer';
import { InspectorPanel } from '../graph/InspectorPanel';

const TRACEABLE_TYPES = [
  'Invoice',
  'SalesOrder',
  'Delivery',
  'JournalEntry',
  'Payment',
];

interface DocumentTracerProps {
  onBack: () => void;
}

interface TraceTarget {
  docType: string;
  docId: string;
}

export const DocumentTracer: React.FC<DocumentTracerProps> = ({ onBack }) => {
  const [docType, setDocType] = useState('Invoice');
  const [docId, setDocId] = useState('');
  const [target, setTarget] = useState<TraceTarget | null>(null);
  const { data: graphData, isLoading, error } = useQuery({
    queryKey: ['trace', target?.docType, target?.docId],
    queryFn: () => api.getTrace(target!.docType, target!.docId, 4),
    enabled: !!target,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!docId.trim()) return;
    setTarget({ docType, docId: docId.trim() });
  };

  const handleReset = () => {
    setTarget(null);
    setDocId('');
  };

  if (target && (isLoading || graphData || error)) {
    return (
      <div style={{ width: '100%', height: '100%', position: 'relative', display: 'flex' }}>
        <div style={{
          position: 'absolute', top: '1.5rem', left: '1.5rem', zIndex: 1000,
          display: 'flex', gap: '1rem', alignItems: 'center'
        }}>
          <button
            onClick={handleReset}
            style={{
              background: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-color)',
              padding: '0.6rem 1.2rem',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            }}
          >
            ← New Trace
          </button>
          <button
            onClick={onBack}
            style={{
              background: 'transparent',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
              padding: '0.6rem 1.2rem',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '0.875rem',
            }}
          >
            Dashboard
          </button>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Tracing:{' '}
            <span style={{ color: 'var(--accent-color)', fontWeight: 600 }}>
              {target.docType} {target.docId}
            </span>
          </div>
        </div>

        {isLoading && <div className="loading-screen">Tracing full O2C lifecycle...</div>}

        {error && (
          <div className="error-screen">
            <h3>Trace Failed</h3>
            <p>{(error as Error).message}</p>
            <button onClick={handleReset}>Try Again</button>
          </div>
        )}

        {graphData && !isLoading && graphData.nodes.length > 0 && (
          <>
            <GraphExplorer data={graphData} />
            <InspectorPanel />
          </>
        )}

        {graphData && !isLoading && graphData.nodes.length === 0 && (
          <div className="empty-state">
            <h3>No Trace Data</h3>
            <p>No relationships found for {target.docType} {target.docId}. Verify the document ID exists.</p>
          </div>
        )}

        {!graphData && !isLoading && !error && (
          <div className="empty-state">
            <h3>Waiting for data&hellip;</h3>
            <p>If this persists, check the browser console for API errors.</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      padding: '2rem',
      color: 'var(--text-primary)',
    }}>
      <div style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: '16px',
        padding: '2.5rem',
        width: '100%',
        maxWidth: '480px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
          <button
            onClick={onBack}
            style={{
              background: 'transparent',
              color: 'var(--text-secondary)',
              border: 'none',
              cursor: 'pointer',
              fontSize: '1.2rem',
              padding: 0,
              lineHeight: 1,
            }}
          >
            ←
          </button>
          <h2 style={{ margin: 0, fontSize: '1.5rem' }}>Trace Document</h2>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '2rem' }}>
          Enter a document ID to trace its full lifecycle across the O2C process.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Document Type
            </label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              style={{
                width: '100%',
                padding: '0.65rem 0.9rem',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                fontSize: '0.95rem',
                cursor: 'pointer',
              }}
            >
              {TRACEABLE_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Document ID
            </label>
            <input
              type="text"
              value={docId}
              onChange={(e) => setDocId(e.target.value)}
              placeholder="e.g. 90000001"
              style={{
                width: '100%',
                padding: '0.65rem 0.9rem',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                fontSize: '0.95rem',
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--accent-color)'; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border-color)'; }}
            />
          </div>

          <button
            type="submit"
            disabled={!docId.trim()}
            style={{
              marginTop: '0.5rem',
              padding: '0.75rem',
              background: docId.trim() ? 'var(--accent-color)' : 'var(--bg-primary)',
              color: docId.trim() ? '#0d1117' : 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              fontWeight: 700,
              fontSize: '0.95rem',
              cursor: docId.trim() ? 'pointer' : 'not-allowed',
              transition: 'all 0.15s ease',
            }}
          >
            Trace Lifecycle →
          </button>
        </form>

        <div style={{
          marginTop: '2rem',
          padding: '1rem',
          background: 'rgba(88,166,255,0.08)',
          borderRadius: '8px',
          border: '1px solid rgba(88,166,255,0.2)',
        }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontWeight: 600 }}>
            Example trace path (Invoice)
          </div>
          <div style={{ fontSize: '0.8rem', color: 'var(--accent-color)', fontFamily: 'monospace' }}>
            Invoice → InvoiceItem → DeliveryItem → SalesOrderItem<br />
            Invoice → JournalEntry ← Payment<br />
            Delivery → DeliveryItem → SalesOrderItem ← SalesOrder ← Customer
          </div>
        </div>
      </div>
    </div>
  );
};
