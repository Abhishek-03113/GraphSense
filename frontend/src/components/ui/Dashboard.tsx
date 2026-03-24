import React from 'react';
import type { GraphSummary } from '../../types/graph';

interface DashboardProps {
  summary: GraphSummary;
  onSelectType: (type: string) => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ summary, onSelectType }) => {
  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <h1>DodgeAI Data Explorer</h1>
        <p>Explore your supply chain graph entities and relationships</p>
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
      `}} />
    </div>
  );
};
