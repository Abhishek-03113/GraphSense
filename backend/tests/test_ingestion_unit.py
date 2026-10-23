"""Ingestion without a database: reading, fingerprints, paths, accounting, hooks, names."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.ingestion.fingerprint import LOADER_VERSION, plan_sources
from src.ingestion.hooks import (
    HookContext,
    HookResult,
    hook,
    load_hooks,
    run_hooks,
)
from src.ingestion.loader import copy_field
from src.ingestion.readers import (
    read_records,
    resolve_data_root,
    resolve_source_dir,
    table_files,
)
from src.ingestion.report import SAMPLE_CAP, IngestError, IssueCollector, TableResult
from src.ingestion.validate import check_tables
from src.storage.schema_names import (
    check_dataset_id,
    is_dataset_schema,
    live_schema,
    previous_schema,
    search_path_for,
    staging_schema,
)
from tests.conftest import TOY_DATA_DIR

# --- reading ---------------------------------------------------------------------------------


def test_files_are_listed_in_sorted_name_order(toy_package, tmp_path):
    root = tmp_path / "root"
    books = root / "toy-library" / "books"
    books.mkdir(parents=True)
    for name in ("part-b.jsonl", "part-10.jsonl", "part-a.jsonl", "notes.txt"):
        (books / name).write_text("{}\n")
    base = resolve_source_dir(root, toy_package)
    files = table_files(base, root, toy_package.table("books"))
    assert [f.name for f in files] == ["part-10.jsonl", "part-a.jsonl", "part-b.jsonl"]
    assert files[0].relative == "books/part-10.jsonl"


def test_a_missing_table_directory_is_reported_as_none(toy_package, tmp_path):
    (tmp_path / "toy-library").mkdir()
    base = resolve_source_dir(tmp_path, toy_package)
    assert table_files(base, tmp_path, toy_package.table("books")) is None


def test_records_problems_and_blank_lines(tmp_path):
    path = tmp_path / "f.jsonl"
    path.write_bytes(b'\xef\xbb\xbf{"a": 1}\n\n   \nnot json\n[1, 2]\n\xff\xfe\n{"b": "x"}\n')
    got = list(read_records(path))
    assert [(n, r, p.code if p else None) for n, r, p in got] == [
        (1, {"a": 1}, None),
        (4, None, "invalid_json"),
        (5, None, "not_an_object"),
        (6, None, "invalid_encoding"),
        (7, {"b": "x"}, None),
    ]


def test_the_digest_covers_every_byte_read(tmp_path):
    import hashlib

    path = tmp_path / "f.jsonl"
    path.write_bytes(b'{"a": 1}\n\n{"b": 2}\n')
    digest = hashlib.sha256()
    list(read_records(path, digest))
    assert digest.hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()


# --- paths -----------------------------------------------------------------------------------


def test_data_root_must_be_configured_and_exist(tmp_path):
    for bad in (None, "", "   "):
        with pytest.raises(IngestError) as info:
            resolve_data_root(bad)
        assert info.value.code == "data_root_not_configured"
    with pytest.raises(IngestError) as info:
        resolve_data_root(tmp_path / "missing")
    assert info.value.code == "data_root_missing"
    assert str(tmp_path) not in info.value.message


def test_the_package_location_cannot_leave_the_data_root(toy_package, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    os.symlink(outside, root / "toy-library")  # the package's subdirectory is a link out of the root
    with pytest.raises(IngestError) as info:
        resolve_source_dir(root, toy_package)
    assert info.value.code == "path_outside_data_root"
    assert str(outside) not in info.value.message


def test_a_table_directory_or_file_linking_out_is_refused(toy_package, tmp_path):
    root = tmp_path / "root"
    base = root / "toy-library"
    base.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.jsonl").write_text("{}\n")
    os.symlink(outside, base / "books")
    with pytest.raises(IngestError) as info:
        table_files(resolve_source_dir(root, toy_package), root, toy_package.table("books"))
    assert info.value.code == "path_outside_data_root"

    (base / "books").unlink()
    (base / "books").mkdir()
    os.symlink(outside / "x.jsonl", base / "books" / "part.jsonl")
    with pytest.raises(IngestError):
        table_files(resolve_source_dir(root, toy_package), root, toy_package.table("books"))


def test_dotdot_in_a_package_path_is_rejected_by_the_package_itself(package_copy):
    from src.datasets import PackageError, load_package

    bad = package_copy(edits={"tables/books.yaml": ("source: {path: books}", "source: {path: ../../etc}")})
    with pytest.raises(PackageError):
        load_package(bad)


# --- fingerprints ----------------------------------------------------------------------------


def test_fingerprint_is_stable_and_follows_content(toy_package, tmp_path):
    import shutil

    root = tmp_path / "root"
    shutil.copytree(TOY_DATA_DIR, root / "toy-library")
    first = plan_sources(toy_package, root)
    assert plan_sources(toy_package, root).fingerprint == first.fingerprint
    assert first.file_count == 5 and first.missing == []

    other = tmp_path / "moved"
    shutil.copytree(root, other)
    assert plan_sources(toy_package, other).fingerprint == first.fingerprint  # only relative names count

    with (root / "toy-library" / "authors" / "part-0001.jsonl").open("a") as handle:
        handle.write("\n")
    assert plan_sources(toy_package, root).fingerprint != first.fingerprint


def test_fingerprint_follows_the_package_and_the_loader_version(toy_package, package_copy, tmp_path):
    import shutil

    from src.datasets import load_package

    root = tmp_path / "root"
    shutil.copytree(TOY_DATA_DIR, root / "toy-library")
    base = plan_sources(toy_package, root).fingerprint
    edited = load_package(package_copy(edits={"package.yaml": ('version: "1.0.0"', 'version: "1.0.1"')}))
    assert plan_sources(edited, root).fingerprint != base
    assert LOADER_VERSION  # bumping it invalidates every fingerprint


def test_missing_tables_are_listed_in_the_plan(toy_package, tmp_path):
    (tmp_path / "toy-library" / "books").mkdir(parents=True)
    plan = plan_sources(toy_package, tmp_path)
    assert plan.missing == ["authors", "loans", "members"]


# --- COPY format, findings, checks ---------------------------------------------------------------


def test_copy_text_format():
    import datetime as dt
    from decimal import Decimal

    assert copy_field(None) == "\\N"
    assert copy_field("a\tb\nc\\d\re") == "a\\tb\\nc\\\\d\\re"
    assert copy_field("\\N") == "\\\\N"  # a text value spelled like NULL stays text
    assert copy_field(True) == "t" and copy_field(False) == "f"
    assert copy_field(Decimal("1E+3")) == "1E+3" and copy_field(12) == "12"
    assert copy_field(dt.date(2025, 1, 6)) == "2025-01-06"
    assert copy_field(dt.datetime(2025, 1, 6, 9, 30, tzinfo=dt.UTC)).startswith("2025-01-06T09:30:00")
    assert copy_field(dt.time(6, 49, 13)) == "06:49:13"
    # JSON escapes the tab as \t, then COPY escapes that backslash
    assert copy_field({"a": "x\ty"}) == '{"a":"x\\\\ty"}'


def test_issues_are_aggregated_and_samples_are_capped():
    issues = IssueCollector()
    for i in range(SAMPLE_CAP + 50):
        issues.add("t", "warning", "invalid_value", "bad", column=f"c{i % 30}", sample={"line": i})
    assert issues.count("warning", "t", "invalid_value") == SAMPLE_CAP + 50
    kept = sum(len(r.sample["examples"]) for r in issues.rows())
    assert kept == SAMPLE_CAP
    assert len(issues.rows()) == 30  # one row per (code, column), not per occurrence
    assert issues.reject_counts() == {"t": {"invalid_value": SAMPLE_CAP + 50}}


def test_a_table_over_the_reject_rate_or_below_min_rows_is_an_error(toy_package):
    issues = IssueCollector()
    def seen(name):
        return {c.source for c in toy_package.table(name).columns}

    results = {
        "books": TableResult("books", records=100, rejected=3, loaded=97, columns_seen=seen("books")),
        "authors": TableResult("authors", records=1000, rejected=1, loaded=999, columns_seen=seen("authors")),
    }
    check_tables(toy_package, results, [], issues, max_reject_rate=0.01)
    errors = [(r.table_name, r.code) for r in issues.rows() if r.severity == "error"]
    assert errors == [("books", "reject_rate_exceeded")]
    again = IssueCollector()
    check_tables(toy_package, results, [], again, max_reject_rate=0.05)
    assert again.count("error") == 0
    missing = IssueCollector()
    check_tables(toy_package, {}, ["loans"], missing)
    assert [(r.table_name, r.code) for r in missing.rows()] == [("loans", "source_missing")]


def test_a_required_column_in_no_record_is_an_error(toy_package):
    issues = IssueCollector()
    results = {"authors": TableResult("authors", records=3, loaded=3, columns_seen={"fullName"})}
    check_tables(toy_package, results, [], issues)
    absent = [r for r in issues.rows() if r.code == "required_column_absent"]
    assert absent and absent[0].table_name == "authors"


# --- hooks -----------------------------------------------------------------------------------


def make_ctx(toy_package) -> HookContext:
    from src.config import get_settings

    return HookContext("toy_library", "run-1", toy_package, "ds_x", engine=None, settings=get_settings())  # type: ignore[arg-type]


async def test_hooks_run_in_order_and_only_in_their_phase(toy_package):
    seen: list[str] = []

    @hook(phase="pre_swap", name="a")
    async def a(ctx):
        seen.append(f"a:{ctx.phase}")

    @hook(phase="post_swap", name="b")
    async def b(ctx):
        seen.append(f"b:{ctx.phase}")
        return HookResult(status="warning", message="careful")

    @hook(phase="pre_swap", name="c")
    async def c(ctx):
        seen.append("c")

    ctx = make_ctx(toy_package)
    pre = await run_hooks([a, b, c], "pre_swap", ctx)
    post = await run_hooks([a, b, c], "post_swap", ctx)
    assert seen == ["a:pre_swap", "c", "b:post_swap"]
    assert [(r.name, r.phase, r.status) for r in pre] == [("a", "pre_swap", "ok"), ("c", "pre_swap", "ok")]
    assert [(r.name, r.status, r.message) for r in post] == [("b", "warning", "careful")]


async def test_results_of_other_types_are_read_by_duck_typing(toy_package):
    class Theirs:
        name = "theirs"
        status = "failed"
        message = "no"
        details = {"x": 1}

    @hook(phase="post_swap")
    async def h(ctx):
        return Theirs()

    [result] = await run_hooks([h], "post_swap", make_ctx(toy_package))
    assert (result.name, result.status, result.message, result.details) == ("theirs", "failed", "no", {"x": 1})


async def test_a_raising_hook_becomes_a_failed_result_without_its_message(toy_package):
    @hook(phase="post_swap")
    async def boom(ctx):
        raise ValueError("/secret/path SELECT 1")

    [result] = await run_hooks([boom], "post_swap", make_ctx(toy_package))
    assert result.status == "failed" and "secret" not in result.message and "SELECT" not in result.message


def test_unavailable_hook_modules_are_skipped_not_fatal():
    loaded = load_hooks(["tests.fake_hooks:fake_pre", "no.such.module:thing", "tests.fake_hooks:missing_attr", "bad"])
    assert [h.name for h in loaded.hooks] == ["fake_pre"]
    by_name = {r.name: r for r in loaded.skipped}
    assert by_name["no.such.module:thing"].status == "skipped"
    assert by_name["tests.fake_hooks:missing_attr"].status == "warning"
    assert by_name["bad"].status == "skipped"


def test_hooks_may_be_instances_classes_or_decorated_functions():
    class Cls:
        name = "cls"
        phase = "post_swap"

        async def run(self, ctx):
            return None

    import sys
    import types

    module = types.ModuleType("tmp_hook_module")
    module.cls = Cls
    module.inst = Cls()
    sys.modules["tmp_hook_module"] = module
    try:
        loaded = load_hooks(["tmp_hook_module:cls", "tmp_hook_module:inst"])
        assert [h.name for h in loaded.hooks] == ["cls", "cls"] and not loaded.skipped
    finally:
        del sys.modules["tmp_hook_module"]


def test_hook_specs_come_from_the_setting(monkeypatch):
    from src.config import override_settings

    with override_settings(POST_INGEST_HOOKS=["tests.fake_hooks:fake_post"]):
        assert [h.name for h in load_hooks().hooks] == ["fake_post"]


# --- names -----------------------------------------------------------------------------------


def test_schema_names():
    run = "0123abcd-ffff-4000-8000-000000000000"
    assert live_schema("o2c") == "ds_o2c" and previous_schema("o2c") == "ds_o2c__prev"
    assert staging_schema("o2c", run) == "ds_o2c__r0123abcd"
    assert is_dataset_schema("ds_toy_library") and not is_dataset_schema("public") and not is_dataset_schema("ds_A")
    assert search_path_for("ds_o2c") == "ds_o2c, public"
    for bad in ("o2c; drop", "A", "a__b", "", "x" * 40):
        with pytest.raises(ValueError):
            check_dataset_id(bad)
    with pytest.raises(ValueError):
        search_path_for("public; DROP SCHEMA x")


def test_dsn_forms():
    from src.storage.engines import async_dsn, sync_dsn

    assert sync_dsn("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
    assert async_dsn("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_the_source_plan_never_exposes_absolute_paths(toy_package, tmp_path):
    import shutil

    root = tmp_path / "root"
    shutil.copytree(TOY_DATA_DIR, root / "toy-library")
    plan = plan_sources(toy_package, root)
    assert str(root) not in json.dumps(plan.hashes)
    assert all(not Path(rel).is_absolute() for rel in plan.hashes)
