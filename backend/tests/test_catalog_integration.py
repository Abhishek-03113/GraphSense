"""The catalog against a real PostgreSQL (set ``TEST_DATABASE_DSN``; skipped otherwise).

Datasets are loaded with the package's own DDL and row coercion
(``tests/pg_support.py``), so these tests do not depend on the ingestion engine.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.catalog import CatalogSnapshot, repository
from src.catalog.builder import build_catalog
from src.catalog.hooks import refresh_catalog
from src.catalog.profiler import ProfileConfig
from src.catalog.refresh import profile_config, refresh_on_connection
from src.catalog.service import CatalogService
from src.config import get_settings, override_settings
from src.datasets import get_package
from tests import pg_support as pg
from tests.conftest import TOY_DATA_DIR, TOY_DIR

pytestmark = pytest.mark.integration

TOY_SCHEMA = "ds_toy_library"
O2C_SCHEMA = "ds_o2c"


@pytest.fixture(scope="module")
def engine():
    dsn = pg.database_dsn()
    if dsn is None:
        pytest.skip("TEST_DATABASE_DSN is not set")
    eng = pg.sync_engine(dsn)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
    pg.run_sql_file(eng, pg.CATALOG_MIGRATION)
    yield eng
    with eng.begin() as conn:
        for schema in (TOY_SCHEMA, O2C_SCHEMA):
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
    eng.dispose()


@pytest.fixture
def clean(engine):
    pg.reset_catalog_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS app.datasets"))


@pytest.fixture
def toy(engine, clean, toy_package, tmp_path):
    import shutil

    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    pg.load_source(engine, toy_package, TOY_SCHEMA, TOY_DATA_DIR)
    with override_settings(PACKAGES_DIR=tmp_path):
        yield toy_package


def _refresh(engine, pkg, **kw):
    with engine.connect() as conn:
        return refresh_on_connection(conn, pkg, cfg=kw.pop("cfg", ProfileConfig()), **kw)


def _catalog_text(engine) -> str:
    """Every stored catalog row, rendered as text."""
    parts = []
    with engine.connect() as conn:
        for table in ("catalog_builds", "catalog_tables", "catalog_columns", "catalog_relationships"):
            parts += [str(r) for r in conn.execute(text(f"SELECT t::text FROM app.{table} t"))]
    return "\n".join(parts)


# --- toy dataset ---------------------------------------------------------------------------------------


def test_toy_catalog_counts_and_labelled_top_values(engine, toy):
    built = _refresh(engine, toy, run_id="run-1")
    snap = built.snapshot
    assert {t.name: t.row_count for t in snap.tables} == {"authors": 3, "books": 3, "loans": 3, "members": 2}
    status = snap.table("loans").column("status")
    assert {(v.value, v.count, v.label) for v in status.top_values} == {
        ("O", 1, "Open"), ("R", 1, "Returned"), ("L", 1, "Late"),
    }
    assert status.distinct_count == 3 and status.null_rate == 0.0
    returned = snap.table("loans").column("returned_at")
    assert returned.null_rate == pytest.approx(1 / 3)
    assert snap.table("loans").column("copy_number").min_value == "1"  # normalised at load
    assert snap.table("books").column("language").top_values  # coded: labelled where a label exists
    # package fields are untouched
    pkg_snap = CatalogSnapshot.from_package(toy)
    for t in snap.tables:
        for c in t.columns:
            assert (c.description, c.role, c.data_type) == (
                pkg_snap.table(t.name).column(c.name).description,
                pkg_snap.table(t.name).column(c.name).role,
                pkg_snap.table(t.name).column(c.name).data_type,
            )


def test_sensitive_columns_have_no_values_in_the_snapshot_or_the_stored_rows(engine, toy):
    built = _refresh(engine, toy, run_id="run-1")
    email = built.snapshot.table("members").column("email")
    assert email.sensitive and email.distinct_count == 2 and email.null_rate == 0.0
    assert (email.min_value, email.max_value, email.top_values, email.sample_values) == (None, None, (), ())
    stored = _catalog_text(engine)
    assert "ada@example.test" not in stored and "bo@example.test" not in stored
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT min_value, max_value, top_values::text, sample_values::text FROM app.catalog_columns "
                "WHERE table_name = 'members' AND column_name = 'email'"
            )
        ).one()
    assert tuple(row) == (None, None, "[]", "[]")


def test_relationship_match_rate_and_coverage(engine, toy):
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {TOY_SCHEMA}.loans (loan_id, member_id, isbn, loaned_on, status) VALUES "
                "('L8', 'M1', 'no-such-book', '2025-03-01', 'O'), ('L9', 'M1', NULL, '2025-03-02', 'O')"
            )
        )
    built = _refresh(engine, toy, run_id="run-1")
    rel = next(r for r in built.snapshot.relationships if r.expression == "loans.isbn = books.isbn")
    # 5 loans, one has no isbn, one points at a missing book: 3 of the 4 keyed rows match
    assert rel.match_rate == pytest.approx(3 / 4)
    stat = built.relationship_stats[(rel.from_table, rel.from_columns, rel.to_table, rel.to_columns)]
    assert (stat.from_rows, stat.keyed_rows, stat.matched_rows) == (5, 4, 3)
    # of the 3 books, those some loan points at
    assert (stat.to_rows, stat.referenced_rows) == (3, 2)
    assert rel.coverage == pytest.approx(2 / 3)


def test_the_sample_cap_bounds_profiling_but_not_the_row_count(engine, toy):
    built = _refresh(engine, toy, run_id="run-1", cfg=ProfileConfig(sample_rows=2))
    assert built.snapshot.table("loans").row_count == 3
    assert built.profiled_rows["loans"] == 2
    with engine.connect() as conn:
        assert conn.execute(text("SELECT profiled_rows FROM app.catalog_tables WHERE table_name = 'loans'")).scalar() == 2


def test_enum_threshold_turns_top_values_into_samples(engine, toy):
    built = _refresh(engine, toy, run_id="run-1", cfg=ProfileConfig(enum_max_distinct=2))
    status = built.snapshot.table("loans").column("status")
    assert status.top_values == () and len(status.sample_values) == 3


def test_refreshing_a_run_twice_replaces_its_rows(engine, toy):
    _refresh(engine, toy, run_id="run-1")
    _refresh(engine, toy, run_id="run-1")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.catalog_builds")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM app.catalog_tables")).scalar() == 4
        cols = conn.execute(text("SELECT count(*) FROM app.catalog_columns")).scalar()
    assert cols == sum(len(t.columns) for t in CatalogSnapshot.from_package(toy).tables)


def test_old_builds_are_pruned_but_the_active_one_is_kept(engine, toy):
    for i in range(1, 6):
        _refresh(engine, toy, run_id=f"run-{i}")
        time.sleep(0.01)
    with engine.connect() as conn:
        kept = set(conn.execute(text("SELECT run_id FROM app.catalog_builds")).scalars())
    assert kept == {"run-3", "run-4", "run-5"}
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app.datasets (id text, schema_name text, active_run_id text)"))
        conn.execute(text(f"INSERT INTO app.datasets VALUES ('toy_library', '{TOY_SCHEMA}', 'run-3')"))
    _refresh(engine, toy, run_id="run-6")  # run-3 is active, so it survives
    with engine.connect() as conn:
        kept = set(conn.execute(text("SELECT run_id FROM app.catalog_builds")).scalars())
    assert kept == {"run-3", "run-4", "run-5", "run-6"}


# --- drift ---------------------------------------------------------------------------------------------------


def test_drift_is_detected_stored_and_does_not_stop_the_build(engine, toy):
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TOY_SCHEMA}.books ADD COLUMN colour text"))
        conn.execute(text(f"ALTER TABLE {TOY_SCHEMA}.books DROP COLUMN page_count"))
        conn.execute(text(f"ALTER TABLE {TOY_SCHEMA}.loans ALTER COLUMN late_fee TYPE text USING late_fee::text"))
        conn.execute(text(f"CREATE TABLE {TOY_SCHEMA}.stray (x int)"))
    built = _refresh(engine, toy, run_id="run-1")
    kinds = {(i.kind, i.table, i.column) for i in built.info.drift}
    assert kinds == {
        ("extra_column", "books", "colour"),
        ("missing_column", "books", "page_count"),
        ("type_mismatch", "loans", "late_fee"),
        ("extra_table", "stray", None),
    }
    # tables with errors are not profiled; the others are
    assert built.snapshot.table("books").row_count is None and built.snapshot.table("loans").row_count is None
    assert built.snapshot.table("authors").row_count == 3
    # relationships that touch an unprofiled table are not measured
    assert all(r.match_rate is None for r in built.snapshot.relationships if "loans" in r.expression or "books" in r.expression)
    with engine.connect() as conn:
        stored = repository.load_build(conn, "toy_library", "run-1")
    assert {(i.kind, i.table, i.column) for i in stored.info.drift} == kinds


def test_a_missing_dataset_schema_reports_every_table_as_missing(engine, clean, toy_package, tmp_path):
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{TOY_SCHEMA}" CASCADE'))
    built = _refresh(engine, toy_package, run_id="run-1")
    assert {i.kind for i in built.info.drift} == {"missing_table"} and len(built.info.drift) == 4
    assert all(t.row_count is None for t in built.snapshot.tables)


# --- the service ---------------------------------------------------------------------------------------------


def _async_engine():
    return create_async_engine(pg.async_url(pg.database_dsn()), poolclass=NullPool)


async def test_service_returns_the_stored_catalog_of_the_latest_build_without_app_datasets(engine, toy):
    built = _refresh(engine, toy, run_id="run-1")
    svc = CatalogService(engine=_async_engine, ttl_seconds=0)
    snap = await svc.get_snapshot("toy_library")
    assert snap == built.snapshot
    status = await svc.get_status("toy_library")
    assert status.origin == "stored" and status.run_id == "run-1" and status.built_at is not None


async def test_service_follows_the_active_run_and_invalidates_on_change(engine, toy):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app.datasets (id text, schema_name text, active_run_id text)"))
        conn.execute(text(f"INSERT INTO app.datasets VALUES ('toy_library', '{TOY_SCHEMA}', 'run-1')"))
    _refresh(engine, toy, run_id="run-1")
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {TOY_SCHEMA}.loans WHERE loan_id = 'L3'"))
    _refresh(engine, toy, run_id="run-2")  # a newer build that is not active yet
    svc = CatalogService(engine=_async_engine, ttl_seconds=0)
    first = await svc.get_snapshot("toy_library")
    assert first.run_id == "run-1" and first.table("loans").row_count == 3
    with engine.begin() as conn:
        conn.execute(text("UPDATE app.datasets SET active_run_id = 'run-2'"))
    second = await svc.get_snapshot("toy_library")
    assert second.run_id == "run-2" and second.table("loans").row_count == 2


async def test_service_builds_a_live_catalog_in_memory_when_nothing_is_stored(engine, toy):
    svc = CatalogService(engine=_async_engine)
    snap = await svc.get_snapshot("toy_library")
    status = await svc.get_status("toy_library")
    assert status.origin == "live" and snap.run_id is None
    assert snap.table("loans").row_count == 3
    assert {v.label for v in snap.table("loans").column("status").top_values} == {"Open", "Returned", "Late"}
    with engine.connect() as conn:  # nothing was written
        assert conn.execute(text("SELECT count(*) FROM app.catalog_builds")).scalar() == 0


async def test_service_falls_back_to_the_package_when_the_dataset_is_not_loaded(engine, toy):
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{TOY_SCHEMA}" CASCADE'))
    svc = CatalogService(engine=_async_engine)
    snap = await svc.get_snapshot("toy_library")
    assert snap == CatalogSnapshot.from_package(toy)
    assert (await svc.get_status("toy_library")).origin == "package"


async def test_service_never_fails_when_the_catalog_tables_do_not_exist(engine, toy):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE app.catalog_builds RENAME TO catalog_builds_off"))
    try:
        snap = await CatalogService(engine=_async_engine).get_snapshot("toy_library")
        assert snap.table("loans").row_count == 3  # live build
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE app.catalog_builds_off RENAME TO catalog_builds"))


# --- the hook ---------------------------------------------------------------------------------------------------


def _ctx(engine, pkg, schema, run_id=None):
    return SimpleNamespace(
        dataset_id=pkg.id, run_id=run_id or uuid.uuid4(), package=pkg, schema=schema, engine=engine,
        settings=get_settings(),
    )


def test_the_hook_is_registered_by_dotted_path():
    import importlib

    module, attr = ["src.catalog.hooks", "refresh_catalog"]
    hook = getattr(importlib.import_module(module), attr)
    assert hook is refresh_catalog and hook.name == "catalog" and hook.phase == "pre_swap"


async def test_the_hook_builds_the_catalog_of_the_staging_schema_on_a_sync_engine(engine, toy):
    run_id = uuid.uuid4()
    result = await refresh_catalog.run(_ctx(engine, toy, TOY_SCHEMA, run_id))
    assert result.status == "ok" and result.details["tables"] == 4 and result.details["drift"] == 0
    with engine.connect() as conn:
        stored = repository.load_build(conn, "toy_library", str(run_id))
    assert stored is not None and stored.info.schema_name == TOY_SCHEMA
    assert stored.profiles["loans"].row_count == 3


async def test_the_hook_builds_the_catalog_on_an_async_engine(engine, toy):
    aengine = _async_engine()
    try:
        result = await refresh_catalog.run(_ctx(aengine, toy, TOY_SCHEMA, "run-async"))
    finally:
        await aengine.dispose()
    assert result.status == "ok"
    with engine.connect() as conn:
        assert repository.load_build(conn, "toy_library", "run-async") is not None


async def test_the_hook_reports_drift_as_a_warning(engine, toy):
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {TOY_SCHEMA}.authors ADD COLUMN extra text"))
    result = await refresh_catalog.run(_ctx(engine, toy, TOY_SCHEMA))
    assert result.status == "warning" and result.details["drift"] == 1 and result.details["drift_errors"] == 0


async def test_the_hook_fails_softly(toy_package):
    class Broken:
        def connect(self):
            raise RuntimeError("boom with secret-host")

    result = await refresh_catalog.run(_ctx(Broken(), toy_package, "ds_x"))
    assert result.status == "failed" and "secret-host" not in result.message + str(result.details)


async def test_the_staging_catalog_becomes_live_with_the_swap(engine, toy):
    """The hook stores the build under the new run id; the service picks it up when the run becomes active."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app.datasets (id text, schema_name text, active_run_id text)"))
        conn.execute(text(f"INSERT INTO app.datasets VALUES ('toy_library', '{TOY_SCHEMA}', NULL)"))
    await refresh_catalog.run(_ctx(engine, toy, TOY_SCHEMA, "run-new"))
    svc = CatalogService(engine=_async_engine, ttl_seconds=0)
    assert (await svc.get_snapshot("toy_library")).source == "live"  # not active: live fallback, nothing stored for None
    with engine.begin() as conn:
        conn.execute(text("UPDATE app.datasets SET active_run_id = 'run-new'"))
    assert (await svc.get_snapshot("toy_library")).run_id == "run-new"


# --- the endpoint ---------------------------------------------------------------------------------------------------


def test_endpoint_returns_labelled_values_and_no_sensitive_values(engine, toy):
    from fastapi.testclient import TestClient

    from src.main import app

    _refresh(engine, toy, run_id="run-1")
    from src.catalog.service import get_catalog_service

    app.dependency_overrides[get_catalog_service] = lambda: CatalogService(engine=_async_engine, ttl_seconds=0)
    try:
        response = TestClient(app).get("/api/datasets/toy_library/catalog")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert "ada@example.test" not in response.text
    assert body["build"]["origin"] == "stored" and body["build"]["run_id"] == "run-1"
    loans = next(t for t in body["tables"] if t["name"] == "loans")
    assert loans["row_count"] == 3
    status = next(c for c in loans["columns"] if c["name"] == "status")
    assert {(v["value"], v["label"]) for v in status["top_values"]} == {("O", "Open"), ("R", "Returned"), ("L", "Late")}
    rel = next(r for r in body["relationships"] if r["expression"] == "loans.isbn = books.isbn")
    assert rel["match_rate"] == 1.0 and rel["coverage"] == pytest.approx(2 / 3)


# --- the command line ---------------------------------------------------------------------------------------------------


def test_cli_refresh_and_show(engine, toy):
    from click.testing import CliRunner

    from src.cli.main import cli, discover_commands

    discover_commands()
    runner = CliRunner()
    with override_settings(DATABASE_DSN=pg.async_url(pg.database_dsn())):
        _run_cli(runner, cli)


def _run_cli(runner, cli):
    import json

    result = runner.invoke(cli, ["catalog", "refresh", "toy_library", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["tables"] == 4 and summary["schema"] == TOY_SCHEMA and summary["drift"] == []
    text_out = runner.invoke(cli, ["catalog", "refresh", "toy_library"]).output
    assert "loans.isbn = books.isbn" in text_out and "100.0%" in text_out
    shown = runner.invoke(cli, ["catalog", "show", "toy_library", "--json"])
    assert shown.exit_code == 0 and json.loads(shown.output)["stale"] is False
    assert runner.invoke(cli, ["catalog", "refresh", "nope"]).exit_code != 0


# --- the real order-to-cash data ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def o2c_loaded(engine):
    source = pg.real_data_dir()
    if source is None:
        pytest.skip("the sample data directory is not available")
    pkg = get_package("o2c")
    counts = pg.load_source(engine, pkg, O2C_SCHEMA, source)
    return pkg, counts


def test_o2c_catalog_builds_quickly_and_matches_the_loaded_rows(engine, clean, o2c_loaded):
    pkg, counts = o2c_loaded
    with engine.connect() as conn:
        started = time.perf_counter()
        built = refresh_on_connection(conn, pkg, run_id="run-1", cfg=profile_config(get_settings()))
        elapsed = time.perf_counter() - started
    assert elapsed < 30
    assert built.info.schema_name == O2C_SCHEMA and built.info.drift == () and built.info.notes == ()
    assert {t.name: t.row_count for t in built.snapshot.tables} == counts
    assert built.info.table_count == 19


def test_o2c_relationship_rates_reproduce_the_documented_join_checks(engine, clean, o2c_loaded):
    pkg, _ = o2c_loaded
    with engine.connect() as conn:
        built = build_catalog(conn, pkg, schema=O2C_SCHEMA, run_id="r", cfg=ProfileConfig())
    by = {r.expression: r for r in built.snapshot.relationships}
    # forward: every foreign key finds its target, apart from the two known gaps
    sold_to = by["sales_order_headers.sold_to_party = business_partners.customer"]
    assert sold_to.match_rate == 1.0
    assert by["billing_document_headers.accounting_document = journal_entry_items_accounts_receivable.accounting_document"].match_rate == pytest.approx(0.755, abs=0.001)
    # reverse: share of targets that something points at (the "100% -> 86%" of the join checks)
    assert by["outbound_delivery_items.reference_sd_document = sales_order_headers.sales_order"].coverage == pytest.approx(0.86, abs=0.001)
    assert by["billing_document_items.reference_sd_document = outbound_delivery_headers.delivery_document"].coverage == pytest.approx(0.965, abs=0.001)


def test_o2c_coded_columns_are_labelled_and_sensitive_columns_are_empty(engine, clean, o2c_loaded):
    pkg, _ = o2c_loaded
    with engine.connect() as conn:
        built = refresh_on_connection(conn, pkg, run_id="run-1", cfg=ProfileConfig())
    status = built.snapshot.table("sales_order_headers").column("overall_delivery_status")
    labelled = {v.value: v.label for v in status.top_values}
    assert labelled.get("C") == "Completely delivered"
    doc_type = built.snapshot.table("billing_document_headers").column("billing_document_type")
    assert {v.value: v.label for v in doc_type.top_values}.get("F2") == "Invoice"
    secret = built.snapshot.sensitive_columns()
    assert secret
    for table, column in secret:
        col = built.snapshot.table(table).column(column)
        assert (col.min_value, col.max_value, col.top_values, col.sample_values) == (None, None, (), ()), (table, column)
    # and nothing of the kind was written for them
    with engine.connect() as conn:
        for table, column in secret:
            row = conn.execute(
                text(
                    "SELECT min_value, max_value, top_values::text, sample_values::text FROM app.catalog_columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            ).one()
            assert tuple(row) == (None, None, "[]", "[]")
        # a value that exists in a sensitive column must not occur in the stored sensitive rows
        leaked = conn.execute(
            text(f'SELECT DISTINCT created_by_user FROM {O2C_SCHEMA}.sales_order_headers WHERE created_by_user IS NOT NULL')
        ).scalars().all()
    for value in leaked:
        rows = _sensitive_rows(engine, secret)
        assert value not in rows


def _sensitive_rows(engine, secret) -> str:
    with engine.connect() as conn:
        return "\n".join(
            str(r)
            for table, column in secret
            for r in conn.execute(
                text("SELECT c::text FROM app.catalog_columns c WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": column},
            )
        )
