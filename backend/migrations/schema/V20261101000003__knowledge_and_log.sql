-- Migration: knowledge store, query log and evaluation runs for the Ask layer
-- Category: schema
--
-- app.knowledge_items holds the text the Ask layer retrieves from (tables, relationships,
-- glossary entries, example questions, data profiles, coded values) with an optional embedding.
-- The embedding column has no fixed size: embed_model and dims are stored per row, so a change of
-- embedding model never needs a schema change.  A row without an embedding is still found by text search.
-- Note: no vector index, because exact search is fast enough for a few thousand items per dataset.
--
-- No foreign keys to other streams' tables.  The migration runner splits on semicolons,
-- so a statement never contains one inside.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.knowledge_items (
    id            BIGSERIAL    PRIMARY KEY,
    dataset_id    TEXT         NOT NULL,
    kind          TEXT         NOT NULL CHECK (kind IN ('table', 'relationship', 'glossary', 'example', 'profile', 'value_set')),
    ref           TEXT         NOT NULL,
    text          TEXT         NOT NULL,
    content_hash  TEXT         NOT NULL,
    embed_model   TEXT         NOT NULL DEFAULT '',
    dims          INTEGER,
    embedding     vector,
    metadata      JSONB        NOT NULL DEFAULT '{}',
    tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', replace(text, '_', ' '))) STORED,
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_items UNIQUE (dataset_id, kind, content_hash, embed_model)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_dataset ON app.knowledge_items (dataset_id, kind);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_tsv ON app.knowledge_items USING GIN (tsv);

-- Questions and the SQL written for them.  Rows older than QUERY_LOG_RETENTION_DAYS are purged
-- (graphsense knowledge purge-log).
CREATE TABLE IF NOT EXISTS app.query_log (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id     TEXT         NOT NULL,
    ts             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    question       TEXT         NOT NULL,
    sql            TEXT,
    validated      BOOLEAN      NOT NULL DEFAULT FALSE,
    error_code     TEXT,
    row_count      INTEGER,
    latency_ms     INTEGER,
    prompt_version TEXT,
    model          TEXT,
    tokens         INTEGER,
    feedback       JSONB
);

CREATE INDEX IF NOT EXISTS idx_query_log_ts ON app.query_log (ts);

CREATE INDEX IF NOT EXISTS idx_query_log_dataset ON app.query_log (dataset_id, ts);

-- One row per evaluation run (written by the evaluation harness).
CREATE TABLE IF NOT EXISTS app.eval_runs (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id    TEXT         NOT NULL,
    ts            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    mode          TEXT         NOT NULL,
    package_hash  TEXT,
    model         TEXT,
    metrics       JSONB        NOT NULL DEFAULT '{}',
    report        JSONB        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_dataset ON app.eval_runs (dataset_id, ts);
