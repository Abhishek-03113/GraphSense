-- Migration: embeddings for the Ask layer's knowledge items (needs the pgvector extension)
-- Category: schema
--
-- The column has no fixed size: embed_model and dims are stored on each row, so a change of
-- embedding model never needs a schema change.  Rows without an embedding are still found by
-- full-text search, and retrieval falls back to it when this migration has not been applied.
-- Note: no vector index, because exact search is fast enough for a few thousand items per dataset.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE app.knowledge_items ADD COLUMN IF NOT EXISTS embedding vector;
