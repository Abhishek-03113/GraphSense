"""The migration runner's handling of stage-1 migrations and missing extensions, and the CLI end to end."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from src.cli.main import cli, discover_commands
from src.db import migration_runner as runner
from src.storage.engines import make_owner_async_engine, sync_dsn
from tests.integration.conftest import ADMIN_DSN, _dsn_for

pytestmark = pytest.mark.integration


@pytest.fixture
def empty_db(monkeypatch):
    """A database with nothing in it (not even the migrations)."""
    name = f"gs_e_{uuid.uuid4().hex[:10]}"
    admin = create_engine(sync_dsn(ADMIN_DSN), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    monkeypatch.setenv("DATABASE_DSN", _dsn_for(name))
    from src.config import reset_settings

    reset_settings()
    yield name
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()
    reset_settings()


def statuses(name: str) -> dict[str, str]:
    engine = create_engine(sync_dsn(_dsn_for(name)))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version, status FROM _schema_migrations")).all()
    engine.dispose()
    return dict(rows)


def tables(name: str) -> set[str]:
    engine = create_engine(sync_dsn(_dsn_for(name)))
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema IN ('public', 'app')")
        ).all()
    engine.dispose()
    return {r[0] for r in rows}


def test_a_fresh_database_gets_the_app_schema_and_no_stage_one_tables(empty_db):
    async def go():
        engine = make_owner_async_engine()
        try:
            return await runner.apply_pending(engine)
        finally:
            await engine.dispose()

    asyncio.run(go())
    assert statuses(empty_db) == {
        "20260325000001": "baselined",
        "20260326000001": "baselined",
        "20261101000001": "applied",
    }
    present = tables(empty_db)
    assert {"app.datasets", "app.ingestion_runs", "app.ingestion_issues"} <= present
    assert "public.sales_order_headers" not in present and "public.rag_embeddings" not in present


def test_a_migration_needing_an_unavailable_extension_stays_pending(empty_db, tmp_path, monkeypatch):
    pending = tmp_path / "schema"
    pending.mkdir()
    (pending / "V29990101000001__needs_ext.sql").write_text(
        "CREATE EXTENSION IF NOT EXISTS definitely_not_installed;\nCREATE TABLE ext_user (id int);\n"
    )
    (pending / "V29990101000002__plain.sql").write_text("CREATE TABLE plain_table (id int);\n")
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)

    async def go():
        engine = make_owner_async_engine()
        skipped: list[str] = []
        try:
            await runner.apply_pending(engine, skipped)
            return skipped, [(s.version, s.status) for s in await runner.get_status(engine)]
        finally:
            await engine.dispose()

    skipped, status = asyncio.run(go())
    assert skipped == ["29990101000001"]
    assert dict(status) == {"29990101000001": "pending", "29990101000002": "applied"}
    assert "public.plain_table" in tables(empty_db) and "public.ext_user" not in tables(empty_db)


def test_the_cli_migrates_ingests_and_reports(db, toy_root):
    discover_commands()
    cli_runner = CliRunner()

    out = cli_runner.invoke(cli, ["db", "migrate"])
    assert out.exit_code == 0, out.output
    assert "No pending migrations" in out.output

    out = cli_runner.invoke(cli, ["ingest", "toy_library", "--data-root", str(toy_root)])
    assert out.exit_code == 0, out.output
    assert "succeeded" in out.output and "members" in out.output

    out = cli_runner.invoke(cli, ["ingest", "toy_library", "--data-root", str(toy_root)])
    assert out.exit_code == 0 and "skipped" in out.output

    out = cli_runner.invoke(cli, ["ingest", "toy_library", "--data-root", str(toy_root), "--force", "--json"])
    assert out.exit_code == 0, out.output
    payload = json.loads(out.output[out.output.index("{"):])
    assert payload["status"] == "succeeded" and payload["table_counts"]["books"] == 3

    out = cli_runner.invoke(cli, ["dataset", "status", "toy_library"])
    assert out.exit_code == 0 and "ready" in out.output and "live=True previous=True" in out.output
    out = cli_runner.invoke(cli, ["dataset", "list"])
    assert "toy_library" in out.output and "ready" in out.output

    out = cli_runner.invoke(cli, ["dataset", "rollback", "toy_library"])
    assert out.exit_code == 0 and "rolled back" in out.output
    out = cli_runner.invoke(cli, ["dataset", "rollback", "toy_library"])
    assert out.exit_code == 0
    out = cli_runner.invoke(cli, ["dataset", "drop", "toy_library", "--yes"])
    assert out.exit_code == 0 and "ds_toy_library" in out.output


def test_the_cli_exits_non_zero_on_a_failed_run(db, toy_root):
    discover_commands()
    (Path(toy_root) / "toy-library" / "loans" / "part-0001.jsonl").write_text("nope\n")
    out = CliRunner().invoke(cli, ["ingest", "toy_library", "--data-root", str(toy_root)])
    assert out.exit_code == 1
    assert "validation_failed" in out.output


def test_provision_roles_via_the_cli_is_repeatable(db):
    discover_commands()
    cli_runner = CliRunner()
    for _ in range(2):
        out = cli_runner.invoke(cli, ["db", "provision-roles", "--app-password", "a", "--readonly-password", "b"])
        assert out.exit_code == 0, out.output
        assert "Roles ready" in out.output
