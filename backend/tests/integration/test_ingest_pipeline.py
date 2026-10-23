"""The ingestion pipeline against a real PostgreSQL: loading, skipping, atomic failure, rollback."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.ingestion.report import IngestBusy, IngestError
from src.ingestion.runner import IngestOptions, ingest, prepare_run
from src.storage import schema_manager as sm
from src.storage.engines import get_owner_sync_engine

pytestmark = pytest.mark.integration

TOY_COUNTS = {"authors": 3, "books": 3, "loans": 3, "members": 2}


def run_toy(root: Path, **kw):
    return ingest("toy_library", IngestOptions(data_root=root, **kw))


def count(db, table: str, schema: str = "ds_toy_library") -> int:
    return db.scalar(f'SELECT count(*) FROM "{schema}"."{table}"')


def test_toy_dataset_loads_with_the_expected_counts(db, toy_root):
    out = run_toy(toy_root)
    assert out.status == "succeeded", out.error_message
    assert out.table_counts == TOY_COUNTS
    for table, n in TOY_COUNTS.items():
        assert count(db, table) == n
    row = db.sql("SELECT status, active_run_id::text FROM app.datasets WHERE id = 'toy_library'")[0]
    assert row[0] == "ready" and row[1] == out.run_id
    run = db.sql("SELECT status, table_counts, phase FROM app.ingestion_runs WHERE id = :r", r=out.run_id)[0]
    assert run[0] == "succeeded" and run[1] == TOY_COUNTS and run[2] == "done"


def test_values_are_typed_and_coded_values_keep_their_form(db, toy_root):
    run_toy(toy_root)
    book = db.sql(
        "SELECT shelf_code, is_reference, price, published FROM ds_toy_library.books WHERE isbn = '9780000000028'"
    )[0]
    assert book[0] == "12" and book[1] is False and str(book[2]) == "18.00" and str(book[3]) == "1891-01-01"
    assert db.scalar("SELECT shelf_code FROM ds_toy_library.books WHERE isbn = '9780000000011'") == "05"


def test_an_unchanged_second_run_is_skipped_and_force_makes_a_new_generation(db, toy_root):
    first = run_toy(toy_root)
    second = run_toy(toy_root)
    assert second.status == "skipped" and second.report["skipped_reason"] == "unchanged"
    assert db.scalar("SELECT active_run_id::text FROM app.datasets WHERE id = 'toy_library'") == first.run_id
    assert sm.generations("toy_library") == {"live": True, "previous": False}

    forced = run_toy(toy_root, force=True)
    assert forced.status == "succeeded"
    assert db.scalar("SELECT active_run_id::text FROM app.datasets WHERE id = 'toy_library'") == forced.run_id
    assert db.scalar("SELECT previous_run_id::text FROM app.datasets WHERE id = 'toy_library'") == first.run_id
    assert sm.generations("toy_library") == {"live": True, "previous": True}


def test_changed_source_files_are_loaded(db, toy_root):
    run_toy(toy_root)
    extra = toy_root / "toy-library" / "members" / "part-0002.jsonl"
    first_member = (toy_root / "toy-library" / "members" / "part-0001.jsonl").read_text().splitlines()[0]
    record = json.loads(first_member)
    id_key = next(k for k in record if k.lower().endswith("id"))
    record[id_key] = "M99"
    extra.write_text(json.dumps(record) + "\n")
    out = run_toy(toy_root)
    assert out.status in ("succeeded", "succeeded_with_warnings")
    assert count(db, "members") == 3


def test_rejected_rows_are_counted_sampled_and_not_loaded(db, toy_root):
    path = toy_root / "toy-library" / "books" / "part-0002.jsonl"
    lines = path.read_text().splitlines()
    bad = json.loads(lines[0])
    bad["isbn"] = "9780000000099"
    bad["pageCount"] = "many"
    path.write_text("\n".join([*lines, json.dumps(bad)]) + "\n")
    out = run_toy(toy_root, max_reject_rate=0.5)
    assert out.status == "succeeded_with_warnings"
    assert out.report["tables"]["books"]["rejected"] == 1
    assert out.reject_counts == {"books": {"invalid_value": 1}}
    assert count(db, "books") == 3
    issue = db.sql(
        "SELECT severity, code, count, sample FROM app.ingestion_issues WHERE run_id = :r AND code = 'invalid_value'",
        r=out.run_id,
    )[0]
    assert issue[0] == "warning" and issue[2] == 1
    assert issue[3]["column"] == "page_count" and issue[3]["examples"][0]["line"] >= 1


def test_the_last_record_of_a_repeated_key_wins_and_is_reported(db, toy_root):
    path = toy_root / "toy-library" / "authors" / "part-0001.jsonl"
    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    again = dict(first, fullName="Renamed Author")
    (toy_root / "toy-library" / "authors" / "part-0002.jsonl").write_text(json.dumps(again) + "\n")
    out = run_toy(toy_root)
    assert out.status == "succeeded_with_warnings"
    assert out.report["tables"]["authors"]["duplicates"] == 1
    assert count(db, "authors") == 3
    assert db.scalar("SELECT count(*) FROM ds_toy_library.authors WHERE full_name = 'Renamed Author'") == 1


def test_unknown_fields_are_a_warning(db, toy_root):
    path = toy_root / "toy-library" / "members" / "part-0001.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[0]["surpriseField"] = "x"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = run_toy(toy_root)
    assert out.status == "succeeded_with_warnings"
    issues = db.sql("SELECT message FROM app.ingestion_issues WHERE run_id = :r AND code = 'unknown_field'", r=out.run_id)
    assert len(issues) == 1 and "surpriseField" in issues[0][0]


# --- failures leave the live data alone ------------------------------------------------


def snapshot(db):
    return {t: db.sql(f'SELECT * FROM ds_toy_library."{t}" ORDER BY 1') for t in TOY_COUNTS}


def schemas(db):
    return {r[0] for r in db.sql("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ds\\_%'")}


def test_a_failing_run_leaves_the_previous_generation_intact(db, toy_root):
    good = run_toy(toy_root)
    before = snapshot(db)
    # Corrupt a required column in every book record: far over the allowed reject rate.
    for path in (toy_root / "toy-library" / "books").glob("*.jsonl"):
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        for r in rows:
            r["pageCount"] = "not a number"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = run_toy(toy_root)
    assert out.status == "failed" and out.error_code == "validation_failed"
    assert "reject" in out.error_message.lower()
    assert snapshot(db) == before
    assert db.scalar("SELECT active_run_id::text FROM app.datasets WHERE id = 'toy_library'") == good.run_id
    assert schemas(db) == {"ds_toy_library"}  # no staging schema left behind
    run = db.sql("SELECT status, error_code FROM app.ingestion_runs WHERE id = :r", r=out.run_id)[0]
    assert tuple(run) == ("failed", "validation_failed")


def test_a_missing_table_directory_fails_the_run(db, toy_root):
    import shutil

    shutil.rmtree(toy_root / "toy-library" / "loans")
    out = run_toy(toy_root)
    assert out.status == "failed" and out.error_code == "validation_failed"
    assert "loans" in out.error_message
    assert schemas(db) == set()
    assert db.scalar("SELECT status FROM app.datasets WHERE id = 'toy_library'") == "failed"


def test_a_failing_first_run_does_not_make_a_partial_dataset_visible(db, toy_root):
    path = toy_root / "toy-library" / "loans" / "part-0001.jsonl"
    path.write_text("not json\n{broken\n")
    out = run_toy(toy_root)
    assert out.status == "failed"
    assert schemas(db) == set()


def test_failure_messages_do_not_leak_paths_or_sql(db, toy_root):
    path = toy_root / "toy-library" / "loans" / "part-0001.jsonl"
    path.write_text("not json\n")
    out = run_toy(toy_root)
    blob = json.dumps([out.error_message, [(i.message, i.sample) for i in out.issues]])
    assert str(toy_root) not in blob and "SELECT" not in blob and "Traceback" not in blob


# --- swap, rollback ---------------------------------------------------------------------


def test_rollback_restores_the_previous_generation_and_can_roll_forward(db, toy_root):
    run_toy(toy_root)
    extra = toy_root / "toy-library" / "members" / "part-0002.jsonl"
    record = json.loads((toy_root / "toy-library" / "members" / "part-0001.jsonl").read_text().splitlines()[0])
    id_key = next(k for k in record if k.lower().endswith("id"))
    record[id_key] = "M77"
    extra.write_text(json.dumps(record) + "\n")
    second = run_toy(toy_root)
    assert count(db, "members") == 3

    sm.rollback("toy_library")
    assert count(db, "members") == 2
    assert db.scalar("SELECT active_run_id::text FROM app.datasets WHERE id = 'toy_library'") != second.run_id
    sm.rollback("toy_library")  # roll forward
    assert count(db, "members") == 3
    assert db.scalar("SELECT active_run_id::text FROM app.datasets WHERE id = 'toy_library'") == second.run_id


def test_rollback_without_a_previous_generation_is_refused(db, toy_root):
    run_toy(toy_root)
    with pytest.raises(sm.SchemaError) as info:
        sm.rollback("toy_library")
    assert info.value.code == "no_previous_generation"


def test_a_pooled_connection_with_prepared_statements_sees_the_new_generation(db, toy_root):
    """The swap renames schemas: a connection that already planned the query must not keep reading the old tables."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.datasets.context import DatasetContext
    from src.datasets.registry import get_package
    from src.storage.session import use_dataset

    run_toy(toy_root)
    ctx = DatasetContext("toy_library", "ds_toy_library", get_package("toy_library"))

    async def read(engine) -> tuple[int, int]:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as session:
            await use_dataset(session, ctx)
            pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar()
            n = (await session.execute(text("SELECT count(*) FROM members"))).scalar()
            return pid, n

    async def go() -> list[tuple[int, int]]:
        engine = create_async_engine(db.dsn, pool_size=1, max_overflow=0)
        seen = [await read(engine), await read(engine)]  # the statement is now prepared on the pooled connection
        record = json.loads((toy_root / "toy-library" / "members" / "part-0001.jsonl").read_text().splitlines()[0])
        id_key = next(k for k in record if k.lower().endswith("id"))
        record[id_key] = "M55"
        (toy_root / "toy-library" / "members" / "part-0002.jsonl").write_text(json.dumps(record) + "\n")
        await asyncio.to_thread(run_toy, toy_root)
        seen.append(await read(engine))  # same connection, new generation
        await asyncio.to_thread(sm.rollback, "toy_library")
        seen.append(await read(engine))
        await engine.dispose()
        return seen

    seen = asyncio.run(go())
    assert len({pid for pid, _ in seen}) == 1, "the test must reuse one pooled connection"
    assert [n for _, n in seen] == [2, 2, 3, 2]


# --- concurrency -------------------------------------------------------------------------


def test_a_second_concurrent_run_is_refused(db, toy_root):
    first = prepare_run("toy_library", IngestOptions(data_root=toy_root))
    try:
        with pytest.raises(IngestBusy):
            prepare_run("toy_library", IngestOptions(data_root=toy_root))
    finally:
        first.release()
    # the lock is released: a run can start again
    assert run_toy(toy_root).status == "succeeded"


def test_a_stale_running_run_is_reaped_on_the_next_start(db, toy_root):
    db.sql(
        "INSERT INTO app.ingestion_runs (id, dataset_id, kind, status, phase, started_at, heartbeat_at) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'toy_library', 'ingest', 'running', 'load', "
        "now() - interval '2 hours', now() - interval '1 hour')"
    )
    out = run_toy(toy_root)
    assert out.status == "succeeded"
    row = db.sql(
        "SELECT status, error_code FROM app.ingestion_runs WHERE id = '00000000-0000-0000-0000-000000000001'"
    )[0]
    assert tuple(row) == ("failed", "stale_run")


def test_the_run_needs_a_migrated_database(db, toy_root):
    db.sql("DROP SCHEMA app CASCADE")
    with pytest.raises(IngestError) as info:
        run_toy(toy_root)
    assert info.value.code == "not_migrated"


# --- paths ---------------------------------------------------------------------------------


def test_a_symlink_leading_out_of_the_data_root_is_refused(db, toy_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "part-0001.jsonl").write_text('{"memberId": "X"}\n')
    members = toy_root / "toy-library" / "members"
    for f in members.iterdir():
        f.unlink()
    members.rmdir()
    os.symlink(outside, members)
    out = run_toy(toy_root)
    assert out.status == "failed" and out.error_code == "path_outside_data_root"
    assert str(outside) not in (out.error_message or "")


def test_the_data_root_is_required(db):
    with pytest.raises(IngestError) as info:
        ingest("toy_library", IngestOptions(data_root=None))
    assert info.value.code == "data_root_not_configured"


def test_an_unknown_dataset_is_refused(db, toy_root):
    with pytest.raises(IngestError) as info:
        ingest("nope", IngestOptions(data_root=toy_root))
    assert info.value.code == "unknown_dataset"


def test_a_dry_run_records_and_swaps_nothing(db, toy_root):
    out = run_toy(toy_root, dry_run=True)
    assert out.status == "succeeded" and out.dry_run
    assert out.table_counts == TOY_COUNTS
    assert schemas(db) == set()
    assert db.scalar("SELECT count(*) FROM app.ingestion_runs") == 0
    assert db.scalar("SELECT count(*) FROM app.datasets") == 0


def test_dropping_a_dataset_removes_every_generation(db, toy_root):
    run_toy(toy_root)
    run_toy(toy_root, force=True)
    assert set(sm.drop_dataset("toy_library")) == {"ds_toy_library", "ds_toy_library__prev"}
    assert schemas(db) == set()
    assert db.scalar("SELECT count(*) FROM app.datasets") == 0
    assert db.scalar("SELECT count(*) FROM app.ingestion_runs") == 2  # history is kept


def test_the_owner_engine_is_what_loads(db, toy_root):
    run_toy(toy_root)
    with get_owner_sync_engine().connect() as conn:
        assert sm.tables_in(conn, "ds_toy_library") == sorted(TOY_COUNTS)
