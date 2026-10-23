-- Runs once, when the database container is first created (as the superuser).
-- It creates the application roles with development passwords and enables pgvector.
-- Grants are applied later by `graphsense db provision-roles` (run it after `graphsense db migrate`).
-- Change these passwords for anything that is not a local development database.

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphsense_app') THEN
        CREATE ROLE graphsense_app LOGIN PASSWORD 'graphsense_app';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphsense_ro') THEN
        CREATE ROLE graphsense_ro LOGIN PASSWORD 'graphsense_ro';
    END IF;
END
$$;
