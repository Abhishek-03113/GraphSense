-- Migration: Add pgvector-based RAG embeddings table
-- Category: schema
-- Replaces ChromaDB with PostgreSQL pgvector for embedding storage and similarity search

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id              BIGSERIAL       PRIMARY KEY,
    category        VARCHAR(32)     NOT NULL,  -- 'ddl', 'documentation', 'sql_pair', 'data_summary'
    content         TEXT            NOT NULL,
    metadata        JSONB           NOT NULL DEFAULT '{}',
    embedding       vector(3072)    NOT NULL,  -- gemini-embedding-2-preview outputs 3072 dimensions
    content_hash    VARCHAR(32)     NOT NULL,  -- MD5 hash for idempotent upserts
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT uq_rag_embeddings_hash UNIQUE (content_hash)
);

-- Note: ANN index skipped — vector(3072) exceeds pgvector's 2000-dim index limit.
-- Exact cosine search is used instead (fine for small RAG datasets < 10k rows).

CREATE INDEX IF NOT EXISTS idx_rag_embeddings_category
    ON rag_embeddings (category);
