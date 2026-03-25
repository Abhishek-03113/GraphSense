-- Migration: Add pgvector-based RAG embeddings table
-- Category: schema
-- Replaces ChromaDB with PostgreSQL pgvector for embedding storage and similarity search

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id              BIGSERIAL       PRIMARY KEY,
    category        VARCHAR(32)     NOT NULL,  -- 'ddl', 'documentation', 'sql_pair', 'data_summary'
    content         TEXT            NOT NULL,
    metadata        JSONB           NOT NULL DEFAULT '{}',
    embedding       vector(768)     NOT NULL,  -- Gemini text-embedding-004 outputs 768 dimensions
    content_hash    VARCHAR(32)     NOT NULL,  -- MD5 hash for idempotent upserts
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT uq_rag_embeddings_hash UNIQUE (content_hash)
);

-- IVFFlat index for fast cosine similarity search
-- lists = 4 * sqrt(expected_rows) — start small, recreate after bulk load if needed
CREATE INDEX IF NOT EXISTS idx_rag_embeddings_cosine
    ON rag_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 20);

CREATE INDEX IF NOT EXISTS idx_rag_embeddings_category
    ON rag_embeddings (category);
