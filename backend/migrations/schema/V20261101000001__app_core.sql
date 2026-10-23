-- Migration: app_core
-- Category: schema
-- The application-owned schema and the core tables of dataset management.
-- Dataset data itself lives in generated schemas (ds_<id>), never here.
-- Statements are split on semicolons by the migration runner, so comments must not contain any.

CREATE SCHEMA IF NOT EXISTS app;

-- One row per dataset that has been loaded or adopted.
CREATE TABLE IF NOT EXISTS app.datasets (
    id               text        PRIMARY KEY,
    package_id       text        NOT NULL,
    package_version  text        NOT NULL,
    package_hash     text        NOT NULL,
    schema_name      text        NOT NULL,
    status           text        NOT NULL DEFAULT 'empty'
                     CHECK (status IN ('empty', 'ready', 'legacy', 'failed')),
    active_run_id    uuid,
    previous_run_id  uuid,
    compat_views     boolean     NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- One row per ingestion attempt, including skipped and failed ones.
CREATE TABLE IF NOT EXISTS app.ingestion_runs (
    id                  uuid        PRIMARY KEY,
    dataset_id          text        NOT NULL,
    kind                text        NOT NULL DEFAULT 'ingest'
                        CHECK (kind IN ('ingest', 'adopt', 'refresh')),
    status              text        NOT NULL
                        CHECK (status IN ('queued', 'running', 'succeeded', 'succeeded_with_warnings', 'failed', 'skipped')),
    phase               text,
    package_hash        text,
    source_fingerprint  text,
    started_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    heartbeat_at        timestamptz NOT NULL DEFAULT now(),
    table_counts        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    reject_counts       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    report              jsonb       NOT NULL DEFAULT '{}'::jsonb,
    error_code          text,
    error_message       text,
    triggered_by        text
);

CREATE INDEX IF NOT EXISTS ix_ingestion_runs_dataset_started
    ON app.ingestion_runs (dataset_id, started_at DESC);

-- Row level findings of a run, aggregated by table and code (samples are capped).
CREATE TABLE IF NOT EXISTS app.ingestion_issues (
    id          bigserial   PRIMARY KEY,
    run_id      uuid        NOT NULL REFERENCES app.ingestion_runs (id) ON DELETE CASCADE,
    table_name  text        NOT NULL,
    severity    text        NOT NULL CHECK (severity IN ('error', 'warning', 'info')),
    code        text        NOT NULL,
    message     text        NOT NULL,
    sample      jsonb,
    count       bigint      NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_ingestion_issues_run
    ON app.ingestion_issues (run_id);
