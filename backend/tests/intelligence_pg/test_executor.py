"""The read-only executor against a real PostgreSQL: privileges, read-only, timeout, row cap."""

import asyncpg
import pytest

from src.catalog import CatalogSnapshot
from src.config import override_settings
from src.intelligence.models import ExecutionError, ValidatedSql
from src.intelligence.sql.executor import ReadOnlyExecutor, assert_ready_for_production
from src.intelligence.sql.guard import SqlGuard

pytestmark = pytest.mark.integration


def validated(sql: str, snap: CatalogSnapshot, schema: str = "ds_toy_library", **kw) -> ValidatedSql:
    result = SqlGuard().validate(sql, snap, schema_name=schema, **kw)
    assert isinstance(result, ValidatedSql), getattr(result, "message", "")
    return result


def raw(sql: str, cap: int = 200) -> ValidatedSql:
    """A statement that did NOT pass the guard (to prove the database refuses it on its own)."""
    return ValidatedSql(sql=sql, original=sql, tables=(), projections=(), row_cap=cap, fetch_limit=cap + 1)


@pytest.fixture
def snap(toy_package):
    return CatalogSnapshot.from_package(toy_package)


@pytest.fixture
def ro_executor(pg):
    return ReadOnlyExecutor(dsn=pg.ro_dsn)


@pytest.fixture
def admin_executor(pg):
    """Even with a superuser DSN, the executor's transaction is read-only."""
    return ReadOnlyExecutor(dsn=pg.admin_dsn)


async def test_a_query_runs_under_the_read_only_role(ro_executor, snap):
    try:
        result = await ro_executor.execute("ds_toy_library", validated("SELECT title, price FROM books ORDER BY title", snap))
    finally:
        await ro_executor.close()
    assert result.columns == ("title", "price")
    assert len(result.rows) == 3
    assert result.truncated is False
    assert result.column_types[0] == "text"


async def test_zero_rows_still_report_columns(ro_executor, snap):
    try:
        result = await ro_executor.execute("ds_toy_library", validated("SELECT title FROM books WHERE 1 = 0", snap))
    finally:
        await ro_executor.close()
    assert result.rows == [] and result.columns == ("title",)


async def test_duplicate_output_names_are_made_unique(ro_executor, snap):
    sql = "SELECT l.isbn, b.isbn FROM loans l JOIN books b ON b.isbn = l.isbn"
    try:
        result = await ro_executor.execute("ds_toy_library", validated(sql, snap))
    finally:
        await ro_executor.close()
    assert result.columns == ("isbn", "isbn_2")


async def test_the_role_cannot_write(ro_executor):
    try:
        with pytest.raises(ExecutionError) as err:
            await ro_executor.execute("ds_toy_library", raw("DELETE FROM loans"))
    finally:
        await ro_executor.close()
    assert err.value.category == "other"  # never the database's own message
    assert "permission" not in str(err.value.category)


async def test_the_role_cannot_read_app_tables(ro_executor):
    try:
        with pytest.raises(ExecutionError):
            await ro_executor.execute("ds_toy_library", raw("SELECT question FROM app.query_log"))
        with pytest.raises(ExecutionError):
            await ro_executor.execute("ds_toy_library", raw("SELECT * FROM app.knowledge_items"))
    finally:
        await ro_executor.close()


async def test_a_write_fails_even_with_a_privileged_role(admin_executor, pg):
    """The transaction is read only, so a query that slipped past the guard still cannot change data."""
    try:
        for sql in (
            "DELETE FROM loans",
            "UPDATE books SET title = 'x'",
            "INSERT INTO authors (author_id, full_name) VALUES ('zz', 'zz')",
            "CREATE TABLE should_not_exist (a int)",
            "TRUNCATE loans",
            "WITH d AS (DELETE FROM loans RETURNING *) SELECT * FROM d",
        ):
            with pytest.raises(ExecutionError) as err:
                await admin_executor.execute("ds_toy_library", raw(sql))
            assert err.value.category == "other", sql
    finally:
        await admin_executor.close()
    conn = await asyncpg.connect(pg.admin_dsn)
    try:
        assert await conn.fetchval("SELECT COUNT(*) FROM ds_toy_library.loans") == 3
        assert await conn.fetchval("SELECT to_regclass('ds_toy_library.should_not_exist')") is None
    finally:
        await conn.close()


async def test_set_commands_cannot_lift_the_limits(admin_executor):
    try:
        with pytest.raises(ExecutionError):
            await admin_executor.execute("ds_toy_library", raw("SET TRANSACTION READ WRITE"))
        with pytest.raises(ExecutionError):
            await admin_executor.execute("ds_toy_library", raw("SELECT 1; DROP TABLE loans"))
    finally:
        await admin_executor.close()


async def test_statement_timeout_is_a_timeout_category(pg):
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    try:
        with override_settings(SQL_STATEMENT_TIMEOUT_MS=300), pytest.raises(ExecutionError) as err:
            await executor.execute("ds_toy_library", raw("SELECT pg_sleep(5)"))
    finally:
        await executor.close()
    assert err.value.category == "timeout"
    assert not err.value.repairable


async def test_a_slow_cross_join_times_out(pg):
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    sql = "SELECT COUNT(*) FROM generate_series(1, 100000000) a, generate_series(1, 100000000) b"
    try:
        with override_settings(SQL_STATEMENT_TIMEOUT_MS=400), pytest.raises(ExecutionError) as err:
            await executor.execute("ds_toy_library", raw(sql))
    finally:
        await executor.close()
    assert err.value.category == "timeout"


async def test_the_row_cap_truncates(ro_executor, snap):
    sql = validated("SELECT g FROM generate_series(1, 50) AS g", snap, max_rows=10)
    try:
        result = await ro_executor.execute("ds_toy_library", sql)
    finally:
        await ro_executor.close()
    assert len(result.rows) == 10 and result.truncated is True


async def test_exactly_the_cap_is_not_truncated(ro_executor, snap):
    sql = validated("SELECT g FROM generate_series(1, 10) AS g", snap, max_rows=10)
    try:
        result = await ro_executor.execute("ds_toy_library", sql)
    finally:
        await ro_executor.close()
    assert len(result.rows) == 10 and result.truncated is False


async def test_the_cap_holds_even_when_the_sql_has_no_limit(ro_executor):
    try:
        result = await ro_executor.execute("ds_toy_library", raw("SELECT g FROM generate_series(1, 1000) g", cap=7))
    finally:
        await ro_executor.close()
    assert len(result.rows) == 7 and result.truncated is True


async def test_error_categories(ro_executor):
    cases = {
        "SELECT FROM WHERE": "syntax",
        "SELECT nope FROM books": "unknown_column",
        "SELECT * FROM nope_table": "unknown_table",
        "SELECT 1 / 0": "type",
        "SELECT 'abc'::int": "type",
        "SELECT title + 1 FROM books": "type",
    }
    try:
        for sql, category in cases.items():
            with pytest.raises(ExecutionError) as err:
                await ro_executor.execute("ds_toy_library", raw(sql))
            assert err.value.category == category, sql
    finally:
        await ro_executor.close()


async def test_missing_dataset_tables_mean_not_ready(ro_executor):
    try:
        with pytest.raises(ExecutionError) as err:
            await ro_executor.execute("ds_nothing_here", raw("SELECT * FROM books"))
    finally:
        await ro_executor.close()
    assert err.value.not_ready and not err.value.repairable


async def test_search_path_is_the_dataset_schema(ro_executor, snap):
    try:
        result = await ro_executor.execute("ds_toy_library", validated("SELECT COUNT(*) AS n FROM authors", snap))
    finally:
        await ro_executor.close()
    assert result.rows == [(3,)]


async def test_a_bad_schema_name_is_refused_before_connecting(ro_executor):
    with pytest.raises(ExecutionError):
        await ro_executor.execute("x; DROP SCHEMA public", raw("SELECT 1"))


async def test_the_executor_survives_a_failed_query(ro_executor, snap):
    try:
        with pytest.raises(ExecutionError):
            await ro_executor.execute("ds_toy_library", raw("SELECT nope FROM books"))
        result = await ro_executor.execute("ds_toy_library", validated("SELECT COUNT(*) FROM books", snap))
    finally:
        await ro_executor.close()
    assert result.rows == [(3,)]


async def test_without_a_read_only_dsn_it_degrades_to_the_app_role(pg, snap):
    executor = ReadOnlyExecutor(dsn=None)
    with override_settings(DATABASE_DSN=pg.app_dsn_sqlalchemy, READONLY_DATABASE_DSN=None):
        try:
            result = await executor.execute("ds_toy_library", validated("SELECT COUNT(*) FROM books", snap))
            assert result.rows == [(3,)] and executor.degraded
            with pytest.raises(ExecutionError):
                await executor.execute("ds_toy_library", raw("DELETE FROM books"))
        finally:
            await executor.close()


def test_production_requires_the_read_only_dsn():
    with override_settings(GRAPHSENSE_ENV="production", READONLY_DATABASE_DSN=None), pytest.raises(
        RuntimeError, match="READONLY_DATABASE_DSN"
    ):
        assert_ready_for_production()
    with override_settings(GRAPHSENSE_ENV="production", READONLY_DATABASE_DSN="postgresql://ro@h/db"):
        assert_ready_for_production()
    with override_settings(GRAPHSENSE_ENV="dev", READONLY_DATABASE_DSN=None):
        assert_ready_for_production()
