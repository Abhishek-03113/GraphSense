"""Where the workstreams meet: default hooks, roles for the catalog and knowledge tables, engine hygiene.

These tests need a PostgreSQL server (``TEST_DATABASE_DSN``).  The knowledge hook runs without an
embedding provider here, so items are stored as text only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from src.config import get_settings
from src.ingestion.runner import IngestOptions, ingest
from src.storage.engines import get_owner_sync_engine
from src.storage.roles import provision_roles

pytestmark = pytest.mark.integration

APP_WRITES = ("app.knowledge_items", "app.query_log", "app.eval_runs")
CATALOG_READS = ("app.catalog_builds", "app.catalog_tables", "app.catalog_columns", "app.catalog_relationships")


def hook_statuses(outcome) -> dict[str, str]:
    return {h["name"]: h["status"] for h in outcome.report.get("hooks", [])}


def privileges(conn, role: str, relation: str, what: str) -> bool:
    return bool(conn.execute(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": relation, "p": what}).scalar())


def test_the_default_hooks_build_the_catalog_and_the_knowledge(db, toy_root):
    assert get_settings().POST_INGEST_HOOKS == [
        "src.catalog.hooks:refresh_catalog",
        "src.intelligence.knowledge.hooks:refresh_knowledge",
    ]
    outcome = ingest("toy_library", IngestOptions(data_root=toy_root))
    assert outcome.status == "succeeded", outcome.report
    assert hook_statuses(outcome) == {"catalog": "ok", "knowledge": "ok"}
    engine = get_owner_sync_engine()
    with engine.connect() as conn:
        run_id = str(conn.execute(text("SELECT active_run_id FROM app.datasets WHERE id = 'toy_library'")).scalar())
        stored = conn.execute(text("SELECT count(*) FROM app.catalog_builds WHERE dataset_id = 'toy_library' AND run_id = :r"), {"r": run_id}).scalar()
        items = conn.execute(text("SELECT count(*) FROM app.knowledge_items WHERE dataset_id = 'toy_library'")).scalar()
    assert stored == 1, "the catalog build is stored under the run that went live"
    assert items > 0


def test_an_ingest_does_not_create_the_process_wide_application_engine(db, toy_root):
    """Hooks run on a worker event loop; a pooled engine created there would break every later request."""
    import src.db.engine as app_engine

    assert app_engine._engine is None
    ingest("toy_library", IngestOptions(data_root=toy_root))
    assert app_engine._engine is None


def test_roles_cover_the_catalog_and_knowledge_tables_across_generations(db, toy_root):
    engine = get_owner_sync_engine()
    provision_roles(engine, app_password="app-pw", readonly_password="ro-pw")
    # Tables that appear after the roles exist are covered by default privileges, and so is a new generation.
    ingest("toy_library", IngestOptions(data_root=toy_root))
    ingest("toy_library", IngestOptions(data_root=toy_root, force=True))
    with engine.connect() as conn:
        for table in (*APP_WRITES, *CATALOG_READS, "app.datasets"):
            assert privileges(conn, "graphsense_app", table, "SELECT"), table
        for table in APP_WRITES:
            assert privileges(conn, "graphsense_app", table, "INSERT, UPDATE, DELETE"), table
        for schema in ("ds_toy_library", "ds_toy_library__prev"):
            assert conn.execute(text("SELECT has_schema_privilege('graphsense_ro', :s, 'USAGE')"), {"s": schema}).scalar(), schema
            assert privileges(conn, "graphsense_ro", f"{schema}.books", "SELECT"), schema
            assert not privileges(conn, "graphsense_ro", f"{schema}.books", "INSERT, UPDATE, DELETE"), schema
        assert not conn.execute(text("SELECT has_schema_privilege('graphsense_ro', 'app', 'USAGE')")).scalar()
        for table in (*APP_WRITES, *CATALOG_READS, "app.datasets"):
            assert not privileges(conn, "graphsense_ro", table, "SELECT"), table
        # The application role may read dataset data but never change it.
        assert privileges(conn, "graphsense_app", "ds_toy_library.books", "SELECT")
        assert not privileges(conn, "graphsense_app", "ds_toy_library.books", "INSERT, UPDATE, DELETE")
