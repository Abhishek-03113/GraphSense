"""Hooks around the swap, and loading the demo and the real O2C data."""

from __future__ import annotations

import pytest

from src.ingestion.runner import IngestOptions, ingest, prepare_refresh
from tests import fake_hooks

pytestmark = pytest.mark.integration

HOOKS = ["tests.fake_hooks:fake_pre", "tests.fake_hooks:fake_post"]


@pytest.fixture(autouse=True)
def _clear_calls():
    fake_hooks.CALLS.clear()


def run_toy(root, **kw):
    return ingest("toy_library", IngestOptions(data_root=root, **kw))


def test_hooks_run_in_both_phases_around_the_swap(db, toy_root):
    out = run_toy(toy_root, hook_specs=HOOKS)
    assert out.status == "succeeded"
    pre, post = fake_hooks.CALLS
    assert pre["phase"] == "pre_swap" and pre["schema"].startswith("ds_toy_library__r") and pre["rows"] == 11
    assert post["phase"] == "post_swap" and post["schema"] == "ds_toy_library" and post["rows"] == 11
    assert pre["run_id"] == post["run_id"] == out.run_id
    hooks = out.report["hooks"]
    assert [(h["name"], h["phase"], h["status"]) for h in hooks] == [
        ("fake_pre", "pre_swap", "ok"), ("fake_post", "post_swap", "ok")
    ]
    stored = db.scalar("SELECT report->'hooks'->0->>'name' FROM app.ingestion_runs WHERE id = :r", r=out.run_id)
    assert stored == "fake_pre"


def test_a_missing_hook_module_is_skipped_with_a_warning(db, toy_root):
    out = run_toy(toy_root, hook_specs=["no_such_pkg.hooks:go", *HOOKS])
    assert out.status == "succeeded"  # unavailable hooks are not a problem of the run
    statuses = {h["name"]: h["status"] for h in out.report["hooks"]}
    assert statuses["no_such_pkg.hooks:go"] == "skipped" and statuses["fake_pre"] == "ok"
    assert len(fake_hooks.CALLS) == 2


def test_hooks_come_from_the_setting_and_can_be_skipped(db, toy_root, monkeypatch):
    from src.config import reset_settings

    monkeypatch.setenv("POST_INGEST_HOOKS", ",".join(HOOKS))
    reset_settings()
    run_toy(toy_root)
    assert len(fake_hooks.CALLS) == 2
    fake_hooks.CALLS.clear()
    run_toy(toy_root, force=True, skip_hooks=True)
    assert fake_hooks.CALLS == []


def test_a_failed_pre_swap_hook_is_a_warning_and_never_blocks_the_swap(db, toy_root):
    out = run_toy(toy_root, hook_specs=["tests.fake_hooks:failing_pre"])
    assert out.status == "succeeded_with_warnings"
    assert out.report["hooks"][0]["status"] == "failed"
    assert db.scalar("SELECT count(*) FROM ds_toy_library.books") == 3  # the data is live


def test_a_raising_post_swap_hook_does_not_undo_live_data_or_leak_its_error(db, toy_root):
    out = run_toy(toy_root, hook_specs=["tests.fake_hooks:raising_post"])
    assert out.status == "succeeded_with_warnings"
    hook = out.report["hooks"][0]
    assert hook["status"] == "failed"
    assert "/srv/path" not in hook["message"] and "SELECT" not in hook["message"]
    assert db.scalar("SELECT status FROM app.datasets WHERE id = 'toy_library'") == "ready"


def test_a_refresh_run_executes_the_post_swap_hooks_on_the_live_data(db, toy_root):
    run_toy(toy_root)
    run = prepare_refresh("toy_library", IngestOptions(hook_specs=HOOKS, force=True, triggered_by="test"))
    out = run.execute()
    assert out.status == "succeeded" and out.kind == "refresh"
    assert [c["phase"] for c in fake_hooks.CALLS] == ["post_swap"]
    assert fake_hooks.CALLS[0]["options"]["force"] is True
    assert db.scalar("SELECT kind FROM app.ingestion_runs WHERE id = :r", r=out.run_id) == "refresh"


def test_a_refresh_needs_loaded_data(db):
    out = prepare_refresh("toy_library", IngestOptions(hook_specs=HOOKS)).execute()
    assert out.status == "failed" and out.error_code == "dataset_not_ready"


# --- the O2C dataset ---------------------------------------------------------------------------


def test_demo_data_loads_and_item_numbers_are_canonical(db, demo_root):
    out = ingest("o2c", IngestOptions(data_root=demo_root))
    assert out.status in ("succeeded", "succeeded_with_warnings"), out.error_message
    assert out.table_counts["sales_order_headers"] == 100
    assert out.table_counts["business_partners"] == 10
    assert db.scalar("SELECT count(*) FROM ds_o2c.sales_order_items WHERE sales_order_item ~ '^0'") == 0
    assert db.scalar("SELECT count(*) FROM ds_o2c.outbound_delivery_items WHERE delivery_document_item ~ '^0'") == 0
    assert db.scalar("SELECT count(*) FROM ds_o2c.outbound_delivery_items WHERE reference_sd_document_item ~ '^0'") == 0
    # the join that needed REGEXP_REPLACE before now works on plain equality
    joined = db.scalar(
        "SELECT count(*) FROM ds_o2c.outbound_delivery_items d JOIN ds_o2c.sales_order_items s "
        "ON s.sales_order = d.reference_sd_document AND s.sales_order_item = d.reference_sd_document_item"
    )
    assert joined == out.table_counts["outbound_delivery_items"]


def test_real_data_loads_every_table_with_the_line_counts_of_the_files(db, real_root):
    from src.datasets.registry import get_package

    pkg = get_package("o2c")
    out = ingest("o2c", IngestOptions(data_root=real_root))
    assert out.status in ("succeeded", "succeeded_with_warnings"), out.error_message
    assert len(out.table_counts) == 19
    base = real_root / "sap-o2c-data"
    for table in pkg.tables:
        lines = sum(
            1 for f in (base / table.source.path).glob("*.jsonl") for ln in f.read_text().splitlines() if ln.strip()
        )
        res = out.report["tables"][table.table]
        assert res["records"] == lines
        assert res["loaded"] == lines - res["rejected"] - res["duplicates"]
        assert db.scalar(f"SELECT count(*) FROM ds_o2c.{table.table}") == res["loaded"]
    assert sum(r["rejected"] for r in out.report["tables"].values()) == 0
    assert out.table_counts["product_storage_locations"] == 16723
    again = ingest("o2c", IngestOptions(data_root=real_root))
    assert again.status == "skipped"
