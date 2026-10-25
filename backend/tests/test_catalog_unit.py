"""Catalog building blocks that need no database: SQL builders, assembly, sensitivity, drift, caching."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.catalog import catalog_payload, router
from src.catalog import CatalogSnapshot, ValueCount
from src.catalog.builder import apply_profile, relationship_key
from src.catalog.introspect import LiveColumn, detect_drift
from src.catalog.profiler import (
    ColumnProfile,
    ProfileConfig,
    TableProfile,
    stats_query,
    values_query,
    wants_top_values,
)
from src.catalog.relationships import RelationshipStat, coverage_query, match_query
from src.catalog.safety import redact_for_llm, sensitive_columns, strip_sensitive_values
from src.catalog.service import CatalogService, CatalogStatus, get_catalog_service
from src.datasets.ddl import schema_ddl

# --- profile SQL ---------------------------------------------------------------------------------


def test_stats_query_never_selects_ordered_values_of_a_sensitive_column(toy_package):
    members = toy_package.table("members")
    sql = stats_query("ds_toy_library", members, members.stored_columns(), 1000)
    assert 'count(DISTINCT "email")' in sql and 'count(*) FILTER (WHERE "email" IS NULL)' in sql
    assert 'min("email")' not in sql and 'max("email")' not in sql
    assert 'min("full_name")::text' in sql
    assert 'ORDER BY "member_id" LIMIT 1000' in sql
    assert '"ds_toy_library"."members"' in sql


def test_stats_query_skips_min_max_for_unordered_types(toy_package):
    books = toy_package.table("books")
    sql = stats_query("ds_toy_library", books, books.stored_columns(), 10)
    assert 'min("is_reference")' not in sql and 'count(DISTINCT "is_reference")' in sql
    assert 'min("price")::text' in sql


def test_values_query_unions_one_limited_branch_per_column(toy_package):
    loans = toy_package.table("loans")
    sql = values_query("ds_toy_library", loans, [("status", 10), ("copy_number", 5)], 500, 80)
    assert sql.startswith("WITH s AS (SELECT")
    assert sql.count("UNION ALL") == 1
    assert "LIMIT 10)" in sql and "LIMIT 5)" in sql
    assert 'GROUP BY "status"' in sql and 'left("copy_number"::text, 81)' in sql


def test_top_values_only_for_repeating_or_coded_small_domains(toy_package):
    loans = toy_package.table("loans")
    cols = {c.name: c for c in loans.stored_columns()}
    cfg = ProfileConfig(enum_max_distinct=50)
    pk = loans.primary_key
    assert wants_top_values(cols["status"], pk, 3, 3, cfg)  # coded, even though each value occurs once
    assert not wants_top_values(cols["loan_id"], pk, 3, 3, cfg)  # the key is not a domain
    assert not wants_top_values(cols["due_on"], pk, 3, 3, cfg)  # all different: samples, not a domain
    assert wants_top_values(cols["due_on"], pk, 3, 30, cfg)  # repeats
    assert not wants_top_values(cols["status"], pk, 51, 100, cfg)  # too many distinct values
    assert not wants_top_values(cols["status"], pk, 0, 0, cfg)


def test_relationship_sql_counts_keyed_and_matched_rows(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    rel = next(r for r in snap.relationships if r.expression == "loans.isbn = books.isbn")
    sql = match_query("ds_toy_library", toy_package, rel, 100)
    assert 'f."isbn" IS NOT NULL' in sql
    assert 'EXISTS (SELECT 1 FROM "ds_toy_library"."books" t WHERE t."isbn" = f."isbn")' in sql
    assert sql.startswith('WITH f AS (SELECT "isbn" FROM "ds_toy_library"."loans" ORDER BY "loan_id" LIMIT 100)')
    back = coverage_query("ds_toy_library", toy_package, rel, 100)
    assert 'EXISTS (SELECT 1 FROM "ds_toy_library"."loans" f WHERE f."isbn" = t."isbn")' in back
    assert back.startswith('WITH t AS (SELECT "isbn" FROM "ds_toy_library"."books" ORDER BY "isbn" LIMIT 100)')


def test_relationship_lookups_stand_in_where_clauses_so_they_become_joins(toy_package):
    """An EXISTS inside count(*) FILTER is evaluated per row; in WHERE it can be a hash semi-join."""
    snap = CatalogSnapshot.from_package(toy_package)
    rel = next(r for r in snap.relationships if r.expression == "loans.isbn = books.isbn")
    for sql in (match_query("ds_x", toy_package, rel, 10), coverage_query("ds_x", toy_package, rel, 10)):
        assert "FILTER" not in sql
        assert "AND EXISTS (SELECT 1 FROM" in sql and "WHERE" in sql.split("EXISTS")[0]


def test_composite_relationship_joins_every_column(toy_package):
    from src.catalog.model import RelationshipInfo

    rel = RelationshipInfo("loans", ("isbn", "copy_number"), "books", ("isbn", "shelf_code"))
    sql = match_query("ds_x", toy_package, rel, 10)
    assert 't."isbn" = f."isbn" AND t."shelf_code" = f."copy_number"' in sql
    assert 'f."isbn" IS NOT NULL AND f."copy_number" IS NOT NULL' in sql


def test_relationship_stat_rates():
    stat = RelationshipStat(from_rows=10, keyed_rows=8, matched_rows=6, to_rows=4, referenced_rows=3)
    assert stat.match_rate == 0.75 and stat.coverage == 0.75
    assert RelationshipStat(5, 0, 0).match_rate is None
    assert RelationshipStat(5, 5, 5).coverage is None
    assert RelationshipStat(5, 5, 5, to_rows=0, referenced_rows=0).coverage is None


# --- assembly --------------------------------------------------------------------------------------


def _profiles():
    return {
        "loans": TableProfile(
            "loans",
            row_count=3,
            profiled_rows=3,
            columns={
                "status": ColumnProfile(
                    "status", 0.0, 3, "L", "R", top_values=(("R", 2), ("X", 1)), sample_values=()
                ),
                "loan_id": ColumnProfile("loan_id", 0.0, 3, "L1", "L3", sample_values=("L1", "L2")),
            },
        ),
        "members": TableProfile(
            "members",
            2,
            2,
            {
                "email": ColumnProfile(
                    "email", 0.0, 2, "ada@example.test", "bo@example.test",
                    top_values=(("ada@example.test", 1),), sample_values=("ada@example.test",),
                ),
                "tier": ColumnProfile("tier", 0.0, 2, "B", "G", top_values=(("G", 1), ("B", 1))),
            },
        ),
    }


def test_apply_profile_labels_top_values_from_the_package(toy_package):
    base = CatalogSnapshot.from_package(toy_package)
    snap = apply_profile(base, _profiles(), {}, run_id="r1")
    status = snap.table("loans").column("status")
    assert status.top_values == (ValueCount("R", 2, "Returned"), ValueCount("X", 1, None))
    assert (status.null_rate, status.distinct_count, status.min_value, status.max_value) == (0.0, 3, "L", "R")
    assert snap.table("loans").row_count == 3
    assert snap.table("loans").column("loan_id").sample_values == ("L1", "L2")
    assert (snap.run_id, snap.source) == ("r1", "live")
    # tables without a profile keep the package-only view
    assert snap.table("books").row_count is None


def test_apply_profile_never_copies_values_into_a_sensitive_column(toy_package):
    snap = apply_profile(CatalogSnapshot.from_package(toy_package), _profiles(), {}, run_id="r1")
    email = snap.table("members").column("email")
    assert email.sensitive
    assert email.top_values == () and email.sample_values == ()
    assert email.min_value is None and email.max_value is None
    assert (email.null_rate, email.distinct_count) == (0.0, 2)  # aggregates are fine
    assert snap.table("members").column("tier").top_values[0] == ValueCount("G", 1, "Gold")


def test_apply_profile_ignores_columns_and_tables_the_package_does_not_have(toy_package):
    extra = {"ghost": TableProfile("ghost", 1, 1, {}), "loans": TableProfile("loans", 1, 1, {"nope": ColumnProfile("nope", 0, 1)})}
    snap = apply_profile(CatalogSnapshot.from_package(toy_package), extra, {}, run_id="r")
    assert snap.table_names == ("authors", "books", "loans", "members")
    assert snap.table("loans").row_count == 1


def test_apply_profile_sets_match_rate_and_coverage(toy_package):
    base = CatalogSnapshot.from_package(toy_package)
    rel = next(r for r in base.relationships if r.expression == "loans.isbn = books.isbn")
    stat = RelationshipStat(3, 3, 3, to_rows=4, referenced_rows=2)
    snap = apply_profile(base, {}, {relationship_key(rel): stat}, run_id="r")
    out = next(r for r in snap.relationships if r.expression == rel.expression)
    assert (out.match_rate, out.coverage) == (1.0, 0.5)
    assert all(r.match_rate is None for r in snap.relationships if r.expression != rel.expression)


# --- sensitivity -------------------------------------------------------------------------------------


def _leaky(toy_package) -> CatalogSnapshot:
    """A snapshot that (wrongly) holds values for a sensitive column, to prove the filters work."""
    snap = CatalogSnapshot.from_package(toy_package)
    members = snap.table("members")
    leaked = dataclasses.replace(
        members.column("email"),
        min_value="a@x", max_value="z@x", top_values=(ValueCount("a@x", 1),), sample_values=("a@x",),
    )
    tier = dataclasses.replace(
        members.column("tier"), top_values=(ValueCount("G", 4, "Gold"),), sample_values=("G",), min_value="B"
    )
    columns = tuple(leaked if c.name == "email" else tier if c.name == "tier" else c for c in members.columns)
    tables = tuple(dataclasses.replace(members, columns=columns) if t.name == "members" else t for t in snap.tables)
    return dataclasses.replace(snap, tables=tables)


def test_sensitive_columns_lists_flagged_columns(toy_package):
    assert CatalogSnapshot.from_package(toy_package).sensitive_columns() == {("members", "email")}
    assert sensitive_columns(CatalogSnapshot.from_package(toy_package)) == {("members", "email")}


def test_strip_sensitive_values_keeps_everything_else(toy_package):
    out = strip_sensitive_values(_leaky(toy_package))
    email = out.table("members").column("email")
    assert (email.min_value, email.max_value, email.top_values, email.sample_values) == (None, None, (), ())
    tier = out.table("members").column("tier")
    assert tier.top_values == (ValueCount("G", 4, "Gold"),) and tier.min_value == "B"


def test_llm_safe_view_removes_values_and_labels_of_sensitive_columns(toy_package):
    snap = _leaky(toy_package)
    safe = snap.llm_safe_view()
    assert safe == redact_for_llm(snap)
    email = safe.table("members").column("email")
    assert email.top_values == () and email.sample_values == () and email.min_value is None
    assert email.value_labels == {} and email.description == snap.table("members").column("email").description
    assert safe.table("members").column("tier").top_values  # other columns untouched
    # the input is not modified
    assert snap.table("members").column("email").top_values


def test_llm_safe_view_leaves_a_clean_snapshot_unchanged(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    assert snap.llm_safe_view() == snap


def test_llm_safe_view_holds_no_example_value_anywhere(toy_package):
    text = repr(_leaky(toy_package).llm_safe_view())
    assert "a@x" not in text and "z@x" not in text


# --- drift ------------------------------------------------------------------------------------------------


def _live_from_package(pkg):
    live = {}
    for table in pkg.tables:
        live[table.table] = {}
        for col in table.stored_columns():
            kind = col.sql_type.kind
            udt = {
                "text": "text", "integer": "int4", "bigint": "int8", "boolean": "bool", "date": "date",
                "time": "time", "timestamp": "timestamptz", "json": "jsonb", "decimal": "numeric",
            }[kind]
            live[table.table][col.name] = LiveColumn(
                col.name, kind, udt, col.sql_type.precision, col.sql_type.scale, col.nullable
            )
    return live


def test_no_drift_when_the_database_matches(toy_package):
    assert detect_drift(toy_package, _live_from_package(toy_package)) == []


def test_drift_reports_missing_extra_and_changed_columns(toy_package):
    live = _live_from_package(toy_package)
    del live["books"]["page_count"]
    live["books"]["colour"] = LiveColumn("colour", "text", "text")
    live["loans"]["late_fee"] = LiveColumn("late_fee", "text", "text")
    del live["members"]
    live["stray"] = {"x": LiveColumn("x", "text", "text")}
    issues = {(i.kind, i.table, i.column): i for i in detect_drift(toy_package, live)}
    assert issues[("missing_column", "books", "page_count")].severity == "error"
    assert issues[("extra_column", "books", "colour")].severity == "warning"
    assert issues[("type_mismatch", "loans", "late_fee")].actual == "text"
    assert issues[("missing_table", "members", None)].severity == "error"
    assert issues[("extra_table", "stray", None)].severity == "warning"
    assert len(issues) == 5


def test_varchar_counts_as_text_and_unconstrained_numeric_as_any_decimal(toy_package):
    live = _live_from_package(toy_package)
    live["books"]["title"] = LiveColumn("title", "character varying", "varchar")
    live["books"]["price"] = LiveColumn("price", "numeric", "numeric")
    assert detect_drift(toy_package, live) == []
    live["books"]["price"] = LiveColumn("price", "numeric", "numeric", 18, 4)
    assert [i.kind for i in detect_drift(toy_package, live)] == ["type_mismatch"]


def test_tables_the_package_does_not_know_are_reported(toy_package):
    live = _live_from_package(toy_package)
    live["_schema_migrations"] = {"version": LiveColumn("version", "text", "text")}
    assert [i.kind for i in detect_drift(toy_package, live)] == ["extra_table"]


# --- DDL consistency (the builder trusts the generated column order) -------------------------------------


def test_every_ddl_column_is_a_stored_column(toy_package):
    ddl = "\n".join(schema_ddl(toy_package, "ds_toy_library"))
    for table in toy_package.tables:
        for col in table.stored_columns():
            assert f'"{col.name}"' in ddl


# --- service cache ---------------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _CountingService(CatalogService):
    """A service whose database is a dictionary: dataset -> run id."""

    def __init__(self, runs: dict[str, str | None], **kw):
        super().__init__(engine=lambda: None, **kw)
        self.runs = runs
        self.run_checks = 0
        self.loads = 0

    async def _current_run(self, pkg):
        self.run_checks += 1
        return self.runs.get(pkg.id)

    async def _read_stored(self, pkg, run_key):
        self.loads += 1
        from src.catalog.builder import BuildInfo
        from src.catalog.repository import StoredCatalog

        info = BuildInfo(pkg.id, run_key, pkg.version, pkg.content_hash, "ds", built_at=datetime(2026, 1, 1), sample_rows=1)
        return StoredCatalog(info, _profiles() if pkg.id == "toy_library" else {}, {})

    async def _build_live(self, pkg):
        return None


async def test_snapshot_is_cached_until_the_active_run_changes(toy_package):
    clock = _Clock()
    runs: dict[str, str | None] = {"toy_library": "run-1"}
    svc = _CountingService(runs, ttl_seconds=5, clock=clock, package_resolver=lambda _id: toy_package)
    first = await svc.get_snapshot("toy_library")
    assert first.run_id == "run-1" and first.source == "live" and svc.loads == 1
    assert first.table("loans").row_count == 3
    assert await svc.get_snapshot("toy_library") is first  # inside the TTL: no database access
    assert svc.run_checks == 1

    clock.now = 6
    again = await svc.get_snapshot("toy_library")  # TTL over, same run: re-validated, not reloaded
    assert again is first and svc.run_checks == 2 and svc.loads == 1

    runs["toy_library"] = "run-2"
    clock.now = 12
    swapped = await svc.get_snapshot("toy_library")
    assert swapped.run_id == "run-2" and swapped is not first and svc.loads == 2
    status = await svc.get_status("toy_library")
    assert status.origin == "stored" and status.run_id == "run-2" and not status.stale


async def test_invalidate_forces_a_reload(toy_package):
    svc = _CountingService({"toy_library": "r"}, package_resolver=lambda _id: toy_package)
    await svc.get_snapshot("toy_library")
    svc.invalidate("toy_library")
    await svc.get_snapshot("toy_library")
    assert svc.loads == 2
    svc.invalidate()
    await svc.get_snapshot("toy_library")
    assert svc.loads == 3


async def test_without_a_database_the_package_snapshot_is_returned(toy_package):
    svc = _CountingService({}, package_resolver=lambda _id: toy_package)
    snap = await svc.get_snapshot("toy_library")
    assert snap == CatalogSnapshot.from_package(toy_package)
    assert (await svc.get_status("toy_library")).origin == "package"


async def test_an_unreachable_database_never_raises(toy_package):
    def no_engine():
        raise RuntimeError("DATABASE_DSN is not set")

    svc = CatalogService(engine=no_engine, package_resolver=lambda _id: toy_package)
    assert await svc.get_snapshot("toy_library") == CatalogSnapshot.from_package(toy_package)


async def test_a_package_edit_marks_the_stored_catalog_stale(toy_package, package_copy):
    from src.datasets import load_package

    svc = _CountingService({"toy_library": "r"}, package_resolver=lambda _id: toy_package)
    original_read = svc._read_stored

    async def old_build(pkg, run_key):
        stored = await original_read(pkg, run_key)
        return dataclasses.replace(stored, info=dataclasses.replace(stored.info, package_hash="old"))

    svc._read_stored = old_build
    assert (await svc.get_status("toy_library")).stale
    edited = load_package(package_copy(edits={"package.yaml": ('version: "1.0.0"', 'version: "1.0.1"')}))
    svc2 = _CountingService({"toy_library": "r"}, package_resolver=lambda _id: edited)
    assert not (await svc2.get_status("toy_library")).stale


# --- API -------------------------------------------------------------------------------------------------


class _FixedService:
    def __init__(self, snapshot: CatalogSnapshot, status: CatalogStatus) -> None:
        self.snapshot, self.status = snapshot, status

    async def get_snapshot(self, _dataset_id: str) -> CatalogSnapshot:
        return self.snapshot

    async def get_status(self, _dataset_id: str) -> CatalogStatus:
        return self.status


def _client(service) -> TestClient:
    from src.api.errors import install_error_handling

    app = FastAPI()
    install_error_handling(app)
    app.include_router(router)
    app.dependency_overrides[get_catalog_service] = lambda: service
    return TestClient(app)


def test_catalog_endpoint_omits_values_of_sensitive_columns(toy_package, tmp_path):
    import shutil

    from src.config import override_settings
    from tests.conftest import TOY_DIR

    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    leaky = apply_profile(_leaky(toy_package), _profiles(), {}, run_id="r1")
    leaky_email = dataclasses.replace(leaky.table("members").column("email"), top_values=(ValueCount("a@x", 1),), sample_values=("a@x",))
    members = leaky.table("members")
    members = dataclasses.replace(members, columns=tuple(leaky_email if c.name == "email" else c for c in members.columns))
    leaky = dataclasses.replace(leaky, tables=tuple(members if t.name == "members" else t for t in leaky.tables))
    service = _FixedService(leaky, CatalogStatus("toy_library", "stored", "r1"))
    with override_settings(PACKAGES_DIR=tmp_path):
        response = _client(service).get("/api/datasets/toy_library/catalog")
    assert response.status_code == 200
    body = response.json()
    assert "a@x" not in response.text and "ada@example.test" not in response.text
    members_out = next(t for t in body["tables"] if t["name"] == "members")
    email = next(c for c in members_out["columns"] if c["name"] == "email")
    assert email["sensitive"] is True and email["top_values"] == [] and email["sample_values"] == []
    assert email["min_value"] is None and email["max_value"] is None
    assert body["build"]["origin"] == "stored" and body["build"]["run_id"] == "r1"
    status = next(t for t in body["tables"] if t["name"] == "loans")
    top = next(c for c in status["columns"] if c["name"] == "status")["top_values"]
    assert top[0] == {"value": "R", "count": 2, "label": "Returned"}


def test_catalog_endpoint_unknown_dataset_is_404():
    response = _client(_FixedService(None, None)).get("/api/datasets/nope/catalog")  # type: ignore[arg-type]
    assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_catalog_payload_reports_drift_and_notes(toy_package):
    from src.catalog.introspect import DriftIssue

    drift = DriftIssue("missing_column", "error", "books", "title", "text", None, "column books.title is missing")
    status = CatalogStatus("toy_library", "live", drift=(drift,), notes=("table x could not be profiled",), stale=True)
    out = catalog_payload(CatalogSnapshot.from_package(toy_package), status)
    assert out.build.drift[0].message == "column books.title is missing" and out.build.stale
    assert out.build.notes == ["table x could not be profiled"]
    assert [t.name for t in out.tables] == ["authors", "books", "loans", "members"]


@pytest.mark.parametrize("module", ["builder", "introspect", "profiler", "relationships", "repository", "service", "refresh", "hooks", "safety"])
def test_catalog_modules_import_without_a_database(module):
    __import__(f"src.catalog.{module}")
