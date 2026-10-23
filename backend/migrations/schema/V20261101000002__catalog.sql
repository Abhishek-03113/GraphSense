-- Semantic catalog: what a dataset's tables and columns hold, measured on the data.
-- One build per (dataset, run). No foreign keys: these tables stand on their own so the
-- catalog can ship independently of the ingestion tables.
-- Sensitive columns never get min/max, top values or samples (they are not written at all).

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.catalog_builds (
    dataset_id          text        NOT NULL,
    run_id              text        NOT NULL,
    package_version     text        NOT NULL,
    package_hash        text        NOT NULL,
    schema_name         text        NOT NULL,
    built_at            timestamptz NOT NULL DEFAULT now(),
    duration_ms         integer     NOT NULL DEFAULT 0,
    profile_sample_rows integer     NOT NULL,
    enum_max_distinct   integer     NOT NULL,
    table_count         integer     NOT NULL DEFAULT 0,
    column_count        integer     NOT NULL DEFAULT 0,
    relationship_count  integer     NOT NULL DEFAULT 0,
    drift               jsonb       NOT NULL DEFAULT '[]'::jsonb,
    notes               jsonb       NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (dataset_id, run_id)
);

CREATE TABLE IF NOT EXISTS app.catalog_tables (
    dataset_id    text   NOT NULL,
    run_id        text   NOT NULL,
    table_name    text   NOT NULL,
    description   text   NOT NULL DEFAULT '',
    grain         text,
    row_count     bigint,
    profiled_rows bigint,
    node_type     text,
    PRIMARY KEY (dataset_id, run_id, table_name)
);

CREATE TABLE IF NOT EXISTS app.catalog_columns (
    dataset_id      text    NOT NULL,
    run_id          text    NOT NULL,
    table_name      text    NOT NULL,
    column_name     text    NOT NULL,
    ordinal         integer NOT NULL,
    data_type       text    NOT NULL,
    nullable        boolean NOT NULL DEFAULT true,
    role            text,
    description     text    NOT NULL DEFAULT '',
    is_pk           boolean NOT NULL DEFAULT false,
    sensitive       boolean NOT NULL DEFAULT false,
    hidden          boolean NOT NULL DEFAULT false,
    null_rate       double precision,
    distinct_count  bigint,
    min_value       text,
    max_value       text,
    top_values      jsonb   NOT NULL DEFAULT '[]'::jsonb,
    sample_values   jsonb   NOT NULL DEFAULT '[]'::jsonb,
    value_set       text,
    value_labels    jsonb   NOT NULL DEFAULT '{}'::jsonb,
    currency_column text,
    PRIMARY KEY (dataset_id, run_id, table_name, column_name)
);

CREATE TABLE IF NOT EXISTS app.catalog_relationships (
    dataset_id     text   NOT NULL,
    run_id         text   NOT NULL,
    from_table     text   NOT NULL,
    from_columns   text[] NOT NULL,
    to_table       text   NOT NULL,
    to_columns     text[] NOT NULL,
    kind           text   NOT NULL,
    cardinality    text,
    expression     text   NOT NULL DEFAULT '',
    description    text   NOT NULL DEFAULT '',
    match_rate     double precision,
    from_rows      bigint,
    keyed_rows     bigint,
    matched_rows   bigint,
    to_rows        bigint,
    referenced_rows bigint,
    PRIMARY KEY (dataset_id, run_id, from_table, from_columns, to_table, to_columns)
);

CREATE INDEX IF NOT EXISTS ix_catalog_builds_dataset_built
    ON app.catalog_builds (dataset_id, built_at DESC);
