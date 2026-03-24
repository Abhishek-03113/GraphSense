import React from 'react';
import type { GraphSummary } from '../../types/graph';

interface DashboardProps {
  summary: GraphSummary;
  onSelectType: (type: string) => void;
  onExploreFlows: () => void;
  onTraceDocument: () => void;
  onKnowledgeGraph: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ summary, onSelectType, onExploreFlows, onTraceDocument, onKnowledgeGraph }) => {
  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <h1>DodgeAI Data Explorer</h1>
        <p>Explore your SAP O2C process graph — flows, documents, and entity relationships</p>
      </header>

      <div className="stats-grid">
        <div className="stats-card">
          <span className="stats-label">Total Entities</span>
          <span className="stats-value">
            {Object.values(summary.nodes).reduce((a, b) => a + b, 0).toLocaleString()}
          </span>
        </div>
        <div className="stats-card">
          <span className="stats-label">Total Relationships</span>
          <span className="stats-value">
            {Object.values(summary.edges).reduce((a, b) => a + b, 0).toLocaleString()}
          </span>
        </div>
      </div>

      <section className="entity-section" style={{ marginBottom: '3rem' }}>
        <h3>Explore the Graph</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1.25rem' }}>
          <button className="explore-card" onClick={onExploreFlows}>
            <div className="explore-card-icon">🔄</div>
            <div className="explore-card-title">O2C Process Flows</div>
            <div className="explore-card-desc">
              Visualize predefined flows: Sales, Fulfillment, Billing, Financial, and the full end-to-end O2C process.
            </div>
            <div className="explore-card-action">Select a flow →</div>
          </button>
          <button className="explore-card" onClick={onTraceDocument}>
            <div className="explore-card-icon">🔍</div>
            <div className="explore-card-title">Trace a Document</div>
            <div className="explore-card-desc">
              Enter any document ID to trace its complete lifecycle across Sales Order, Delivery, Billing, and Payment.
            </div>
            <div className="explore-card-action">Start tracing →</div>
          </button>
          <button className="explore-card" onClick={onKnowledgeGraph}>
            <div className="explore-card-icon">🌐</div>
            <div className="explore-card-title">Knowledge Graph</div>
            <div className="explore-card-desc">
              An Obsidian-style view of all entities and relationships. Filter by type, search by ID, adjust density.
            </div>
            <div className="explore-card-action">Open graph →</div>
          </button>
        </div>
      </section>

      <section className="entity-section">
        <h3>Browse by Entity Type</h3>
        <div className="entity-grid">
          {Object.entries(summary.nodes).map(([type, count]) => (
            <button
              key={type}
              className="entity-card"
              onClick={() => onSelectType(type)}
            >
              <div className="entity-type">{type}</div>
              <div className="entity-count">{count.toLocaleString()}</div>
              <div className="entity-action">Browse →</div>
            </button>
          ))}
        </div>
      </section>

      <style dangerouslySetInnerHTML={{ __html: `
        .dashboard-container {
          padding: 3rem;
          max-width: 1200px;
          margin: 0 auto;
          color: var(--text-primary);
        }
        .dashboard-header {
          margin-bottom: 3rem;
          text-align: center;
        }
        .dashboard-header h1 {
          font-size: 3rem;
          margin-bottom: 0.5rem;
          background: linear-gradient(135deg, #58a6ff 0%, #bc8cff 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .dashboard-header p {
          color: var(--text-secondary);
          font-size: 1.2rem;
        }
        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1.5rem;
          margin-bottom: 4rem;
        }
        .stats-card {
          background: var(--bg-secondary);
          padding: 2rem;
          border-radius: 16px;
          border: 1px solid var(--border-color);
          display: flex;
          flex-direction: column;
          align-items: center;
          transition: transform 0.2s, border-color 0.2s;
        }
        .stats-card:hover {
          transform: translateY(-4px);
          border-color: var(--accent-color);
        }
        .stats-label {
          color: var(--text-secondary);
          font-size: 0.9rem;
          text-transform: uppercase;
          letter-spacing: 0.1rem;
          margin-bottom: 0.5rem;
        }
        .stats-value {
          font-size: 2.5rem;
          font-weight: 700;
          color: var(--accent-color);
        }
        .entity-section h3 {
          margin-bottom: 1.5rem;
          color: var(--text-primary);
          font-size: 1.5rem;
          border-bottom: 1px solid var(--border-color);
          padding-bottom: 1rem;
        }
        .entity-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 1.25rem;
        }
        .entity-card {
          background: var(--bg-secondary);
          padding: 1.5rem;
          border-radius: 12px;
          border: 1px solid var(--border-color);
          text-align: left;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          width: 100%;
        }
        .entity-card:hover {
          background: rgba(88, 166, 255, 0.1);
          border-color: var(--accent-color);
          transform: scale(1.02);
        }
        .entity-type {
          font-weight: 600;
          font-size: 1.1rem;
          color: var(--text-primary);
        }
        .entity-count {
          color: var(--text-secondary);
          font-family: 'JetBrains Mono', monospace;
        }
        .entity-action {
          margin-top: auto;
          font-size: 0.85rem;
          color: var(--accent-color);
          opacity: 0.8;
        }
        .explore-card {
          background: var(--bg-secondary);
          padding: 1.75rem;
          border-radius: 14px;
          border: 1px solid var(--border-color);
          text-align: left;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          flex-direction: column;
          gap: 0.6rem;
          width: 100%;
        }
        .explore-card:hover {
          background: rgba(88, 166, 255, 0.08);
          border-color: var(--accent-color);
          transform: translateY(-3px);
          box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        }
        .explore-card-icon {
          font-size: 2rem;
          line-height: 1;
          margin-bottom: 0.25rem;
        }
        .explore-card-title {
          font-weight: 700;
          font-size: 1.1rem;
          color: var(--text-primary);
        }
        .explore-card-desc {
          color: var(--text-secondary);
          font-size: 0.875rem;
          line-height: 1.55;
          flex: 1;
        }
        .explore-card-action {
          margin-top: 0.5rem;
          font-size: 0.85rem;
          color: var(--accent-color);
          font-weight: 600;
        }
      `}} />
    </div>
  );
};
