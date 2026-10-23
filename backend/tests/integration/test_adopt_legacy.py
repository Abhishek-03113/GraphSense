"""Adopting a stage-1 database (dataset tables in ``public``) and the graph API on top of it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from psycopg2.extras import Json, execute_values
from sqlalchemy import create_engine

from src.datasets.coerce import row_coercer
from src.datasets.registry import get_package
from src.ingestion.adopt import adopt_legacy, revert_adoption
from src.ingestion.report import IngestError
from src.ingestion.runner import IngestOptions, ingest
from src.storage import schema_manager as sm
from src.storage.engines import sync_dsn

pytestmark = pytest.mark.integration

BASELINE = Path(__file__).resolve().parents[2] / "migrations" / "schema" / "V20260325000001__baseline_consolidated.sql"


def build_stage1(db, data_root: Path) -> dict[str, int]:
    """Create the stage-1 schema in ``public`` (the old baseline migration) and fill it with the raw data.

    Rows are loaded the way stage 1 stored them: item numbers exactly as exported (padded or not).
    """
    pkg = get_package("o2c")
    engine = create_engine(sync_dsn(db.dsn))
    counts = {}
    with engine.begin() as conn:
        lines = [ln for ln in BASELINE.read_text().splitlines() if not ln.strip().startswith("--")]
        for statement in "\n".join(lines).split(";"):
            if statement.strip():
                conn.exec_driver_sql(statement)
        cur = conn.connection.cursor()
        for table in pkg.tables:
            # stage 1 had no normalisation: strip the declared normalisers to keep the padding
            raw_table = table.model_copy(update={"columns": tuple(
                c.model_copy(update={"normalize": (), "keep_raw": False}) for c in table.columns)})
            coerce = row_coercer(raw_table)
            rows = {}
            pk = [i for i, c in enumerate(raw_table.stored_columns()) if c.name in raw_table.primary_key]
            for f in sorted((data_root / pkg.source.default_subdir / table.source.path).glob("*.jsonl")):
                for line in f.read_text().splitlines():
                    if line.strip():
                        row, issues = coerce(json.loads(line))
                        assert not issues
                        rows[tuple(row[i] for i in pk)] = row
            cols = ", ".join(c.name for c in raw_table.stored_columns())
            execute_values(
                cur, f"INSERT INTO public.{table.table} ({cols}) VALUES %s",
                [tuple(Json(v) if isinstance(v, dict | list) else v for v in r) for r in rows.values()],
            )
            counts[table.table] = len(rows)
    engine.dispose()
    return counts


def public_tables(db) -> set[str]:
    return {r[0] for r in db.sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name NOT LIKE '\\_%'")}


def public_views(db) -> set[str]:
    return {r[0] for r in db.sql("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")}


@pytest.fixture
def stage1(db, demo_root):
    counts = build_stage1(db, demo_root)
    return counts


def test_adopt_moves_the_tables_registers_the_dataset_and_keeps_old_names_working(db, stage1):
    pkg = get_package("o2c")
    report = adopt_legacy(pkg)
    assert report.adopted and report.compat_views
    assert report.tables == stage1
    assert public_tables(db) == set()
    assert public_views(db) >= set(stage1)
    for table, n in stage1.items():
        assert db.scalar(f"SELECT count(*) FROM ds_o2c.{table}") == n
        assert db.scalar(f"SELECT count(*) FROM public.{table}") == n  # the compatibility view
    row = db.sql("SELECT status, compat_views, active_run_id::text FROM app.datasets WHERE id = 'o2c'")[0]
    assert (row[0], row[1], row[2]) == ("legacy", True, report.run_id)
    assert db.scalar("SELECT kind FROM app.ingestion_runs WHERE id = :r", r=report.run_id) == "adopt"
    # the package's indexes now exist on the adopted tables
    assert db.scalar(
        "SELECT count(*) FROM pg_indexes WHERE schemaname = 'ds_o2c' AND indexname LIKE 'ix\\_%'"
    ) > 0


def test_adopting_twice_is_a_no_op_and_if_needed_is_quiet_on_a_clean_database(db, stage1):
    pkg = get_package("o2c")
    adopt_legacy(pkg)
    again = adopt_legacy(pkg)
    assert not again.adopted and again.reason == "already_adopted"
    assert db.scalar("SELECT count(*) FROM app.ingestion_runs WHERE kind = 'adopt'") == 1


def test_if_needed_does_nothing_when_there_is_nothing_to_adopt(db):
    report = adopt_legacy(get_package("o2c"), if_needed=True)
    assert not report.adopted and report.reason == "no_legacy_tables"
    with pytest.raises(IngestError) as info:
        adopt_legacy(get_package("o2c"))
    assert info.value.code == "no_legacy_tables"


def test_adoption_can_be_reverted_with_set_schema(db, stage1):
    pkg = get_package("o2c")
    adopt_legacy(pkg)
    revert_adoption(pkg)
    assert public_tables(db) == set(stage1)
    assert public_views(db) == set()
    assert db.scalar("SELECT count(*) FROM app.datasets") == 0
    assert db.scalar("SELECT count(*) FROM pg_namespace WHERE nspname = 'ds_o2c'") == 0
    for table, n in stage1.items():
        assert db.scalar(f"SELECT count(*) FROM public.{table}") == n
    assert adopt_legacy(pkg).adopted  # and it can be adopted again


def test_missing_columns_block_adoption_unless_they_can_be_added(db, stage1):
    db.sql("ALTER TABLE public.sales_order_headers DROP COLUMN sold_to_party")
    db.sql("ALTER TABLE public.products DROP COLUMN gross_weight")
    pkg = get_package("o2c")
    report = adopt_legacy(pkg)  # both are nullable, so they are added back
    assert report.adopted and "products.gross_weight" in report.added_columns
    assert "sales_order_headers.sold_to_party" in report.added_columns


def test_a_missing_required_column_is_drift_that_blocks_adoption(db, stage1):
    db.sql("ALTER TABLE public.sales_order_items DROP CONSTRAINT sales_order_items_pkey")
    db.sql("ALTER TABLE public.sales_order_items DROP COLUMN sales_order_item")
    with pytest.raises(IngestError) as info:
        adopt_legacy(get_package("o2c"))
    assert info.value.code == "drift"
    assert "sales_order_items.sales_order_item" in info.value.message
    assert public_tables(db) >= set(stage1)  # nothing moved: the transaction rolled back
    assert db.scalar("SELECT count(*) FROM pg_namespace WHERE nspname = 'ds_o2c'") == 0


async def test_the_api_serves_the_same_graph_before_and_after_adoption(db, stage1, client):
    before = (await client.get("/api/graph/summary")).json()
    entities_before = (await client.get("/api/graph/entities/SalesOrder", params={"limit": 100})).json()
    assert before["nodes"]["SalesOrder"] == 100

    adopt_legacy(get_package("o2c"))
    after = (await client.get("/api/graph/summary")).json()
    assert after == before
    assert (await client.get("/api/graph/entities/SalesOrder", params={"limit": 100})).json() == entities_before
    status = (await client.get("/api/datasets/o2c/status")).json()
    assert status["status"] == "legacy"


def test_reloading_after_adoption_swaps_in_canonical_data_and_rollback_returns_the_adopted_data(db, stage1, demo_root):
    pkg = get_package("o2c")
    adopt_legacy(pkg)
    assert db.scalar("SELECT count(*) FROM ds_o2c.sales_order_items WHERE sales_order_item ~ '^0'") > 0  # padded
    out = ingest("o2c", IngestOptions(data_root=demo_root))
    assert out.status in ("succeeded", "succeeded_with_warnings")
    assert db.scalar("SELECT status FROM app.datasets WHERE id = 'o2c'") == "ready"
    assert db.scalar("SELECT count(*) FROM ds_o2c.sales_order_items WHERE sales_order_item ~ '^0'") == 0
    # the old names follow the live generation
    assert db.scalar("SELECT count(*) FROM public.sales_order_items WHERE sales_order_item ~ '^0'") == 0
    assert public_views(db) >= set(stage1)

    sm.rollback("o2c")
    assert db.scalar("SELECT count(*) FROM ds_o2c.sales_order_items WHERE sales_order_item ~ '^0'") > 0
    assert db.scalar("SELECT count(*) FROM public.sales_order_items WHERE sales_order_item ~ '^0'") > 0
    assert db.scalar("SELECT status FROM app.datasets WHERE id = 'o2c'") == "legacy"
