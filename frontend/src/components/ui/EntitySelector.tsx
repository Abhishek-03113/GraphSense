import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import type { GraphEntity } from '../../types/graph';

interface EntitySelectorProps {
  selectedType: string | null;
  onSelectEntity: (type: string, id: string) => void;
  onBack: () => void;
}

export const EntitySelector: React.FC<EntitySelectorProps> = ({ selectedType, onSelectEntity, onBack }) => {
  const [entities, setEntities] = useState<GraphEntity | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (selectedType) {
      setLoading(true);
      api.getEntities(selectedType)
        .then(setEntities)
        .finally(() => setLoading(false));
    }
  }, [selectedType]);

  const filteredEntities = entities?.entities.filter(e => 
    e.id.toLowerCase().includes(search.toLowerCase()) || 
    e.label.toLowerCase().includes(search.toLowerCase())
  ) || [];

  return (
    <div className="selector-container">
      <div className="selector-card">
        <header className="selector-header">
          <button className="back-btn" onClick={onBack}>← Back to Dashboard</button>
          <h2>Select {selectedType}</h2>
          <p>Choose an entity to visualize its relationships</p>
        </header>

        <div className="search-box">
          <input 
            type="text" 
            placeholder={`Search ${selectedType} IDs...`} 
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {loading ? (
          <div className="loading-state">Fetching available entities...</div>
        ) : (
          <div className="entity-list">
            {filteredEntities.length > 0 ? (
              filteredEntities.map(entity => (
                <button 
                  key={entity.id} 
                  className="entity-item"
                  onClick={() => onSelectEntity(selectedType!, entity.id)}
                >
                  <div className="entity-id-badge">{entity.id}</div>
                  <div className="entity-label-text">{entity.label}</div>
                  <span className="visualize-hint">Visualize →</span>
                </button>
              ))
            ) : (
              <div className="empty-state">No entities found starting with "{search}"</div>
            )}
          </div>
        )}
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        .selector-container {
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
          padding: 2rem;
        }
        .selector-card {
          background: var(--bg-secondary);
          width: 100%;
          max-width: 600px;
          border-radius: 20px;
          border: 1px solid var(--border-color);
          padding: 2.5rem;
          box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        }
        .selector-header {
          margin-bottom: 2rem;
        }
        .back-btn {
          color: var(--text-secondary);
          background: transparent;
          border: none;
          cursor: pointer;
          margin-bottom: 1rem;
          font-size: 0.9rem;
          transition: color 0.2s;
        }
        .back-btn:hover {
          color: var(--accent-color);
        }
        .selector-header h2 {
          font-size: 2rem;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }
        .selector-header p {
          color: var(--text-secondary);
        }
        .search-box {
          margin-bottom: 1.5rem;
        }
        .search-box input {
          width: 100%;
          padding: 1rem 1.5rem;
          background: var(--bg-color);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          color: var(--text-primary);
          font-size: 1rem;
          outline: none;
          transition: border-color 0.2s;
        }
        .search-box input:focus {
          border-color: var(--accent-color);
        }
        .loading-state, .empty-state {
          padding: 3rem;
          text-align: center;
          color: var(--text-secondary);
        }
        .entity-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
          max-height: 400px;
          overflow-y: auto;
          padding-right: 0.5rem;
          scrollbar-width: thin;
          scrollbar-color: var(--border-color) transparent;
        }
        .entity-item {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding: 1rem;
          background: var(--bg-color);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          cursor: pointer;
          transition: all 0.2s;
          text-align: left;
          width: 100%;
        }
        .entity-item:hover {
          border-color: var(--accent-color);
          background: rgba(88, 166, 255, 0.05);
        }
        .entity-id-badge {
          background: var(--accent-color);
          color: white;
          padding: 0.25rem 0.6rem;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 600;
          font-family: 'JetBrains Mono', monospace;
        }
        .entity-label-text {
          flex: 1;
          color: var(--text-primary);
          font-weight: 500;
        }
        .visualize-hint {
          font-size: 0.8rem;
          color: var(--accent-color);
          opacity: 0.6;
        }
      `}} />
    </div>
  );
};
