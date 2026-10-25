"""SqlGuard: a corpus of hostile queries is refused, real queries pass, the row cap is enforced."""

import pytest

from src.catalog import CatalogSnapshot
from src.datasets.models import DatasetPackage
from src.intelligence.models import SqlRejected, ValidatedSql
from src.intelligence.sql.guard import SqlGuard

GUARD = SqlGuard()
SCHEMA = "ds_toy_library"


@pytest.fixture(scope="module")
def snap(toy_package) -> CatalogSnapshot:
    return CatalogSnapshot.from_package(toy_package)


def check(sql, snap, **kw):
    kw.setdefault("schema_name", SCHEMA)
    return GUARD.validate(sql, snap, **kw)


# ---------------------------------------------------------------------------
# Hostile corpus: every entry must be refused.  (label, sql)
# ---------------------------------------------------------------------------

HOSTILE = [
    # stacked statements and comment tricks
    ("stacked drop", "SELECT 1; DROP TABLE loans"),
    ("stacked select", "SELECT 1; SELECT 2"),
    ("stacked after comment", "SELECT 1 -- x\n; DELETE FROM loans"),
    ("stacked with block comment", "SELECT 1 /* a */; /* b */ UPDATE loans SET status = 'R'"),
    ("leading statement", "UPDATE loans SET status='R'; SELECT * FROM loans"),
    ("semicolon then insert", "SELECT * FROM loans;INSERT INTO loans(loan_id) VALUES ('x')"),
    # writes and DDL
    ("insert", "INSERT INTO loans (loan_id, loaned_on) VALUES ('x', '2025-01-01')"),
    ("insert select", "INSERT INTO loans SELECT * FROM loans"),
    ("update", "UPDATE loans SET status = 'R'"),
    ("delete", "DELETE FROM loans"),
    ("delete using", "DELETE FROM loans USING books WHERE loans.isbn = books.isbn"),
    ("truncate", "TRUNCATE loans"),
    ("drop table", "DROP TABLE loans"),
    ("drop schema", "DROP SCHEMA ds_toy_library CASCADE"),
    ("create table", "CREATE TABLE x AS SELECT * FROM loans"),
    ("create view", "CREATE VIEW v AS SELECT * FROM loans"),
    ("create extension", "CREATE EXTENSION dblink"),
    ("alter table", "ALTER TABLE loans ADD COLUMN z int"),
    ("alter role", "ALTER ROLE postgres SUPERUSER"),
    ("grant", "GRANT ALL ON loans TO PUBLIC"),
    ("merge", "MERGE INTO loans l USING books b ON l.isbn = b.isbn WHEN MATCHED THEN DELETE"),
    ("upsert", "INSERT INTO loans (loan_id) VALUES ('1') ON CONFLICT (loan_id) DO NOTHING"),
    # select with side effects
    ("select into", "SELECT * INTO backup FROM loans"),
    ("select into temp", "SELECT * INTO TEMP t FROM loans"),
    ("for update", "SELECT * FROM loans FOR UPDATE"),
    ("for share", "SELECT * FROM loans FOR SHARE"),
    ("for update in subquery", "SELECT * FROM loans WHERE loan_id IN (SELECT loan_id FROM loans FOR UPDATE)"),
    ("modifying cte delete", "WITH d AS (DELETE FROM loans RETURNING *) SELECT * FROM d"),
    ("modifying cte insert", "WITH i AS (INSERT INTO loans (loan_id) VALUES ('1') RETURNING *) SELECT * FROM i"),
    ("modifying cte update", "WITH u AS (UPDATE loans SET status='R' RETURNING *) SELECT * FROM u"),
    # utility statements
    ("copy to file", "COPY loans TO '/tmp/x'"),
    ("copy from program", "COPY loans FROM PROGRAM 'id'"),
    ("copy select", "COPY (SELECT * FROM loans) TO STDOUT"),
    ("set role", "SET ROLE postgres"),
    ("set statement_timeout", "SET statement_timeout = 0"),
    ("reset", "RESET ALL"),
    ("begin", "BEGIN"),
    ("commit", "COMMIT"),
    ("rollback", "ROLLBACK"),
    ("lock", "LOCK TABLE loans"),
    ("explain", "EXPLAIN SELECT * FROM loans"),
    ("explain analyze", "EXPLAIN ANALYZE DELETE FROM loans"),
    ("vacuum", "VACUUM loans"),
    ("analyze", "ANALYZE loans"),
    ("do block", "DO $$ BEGIN PERFORM pg_sleep(10); END $$"),
    ("call", "CALL pg_terminate_backend(1)"),
    ("listen", "LISTEN x"),
    ("notify", "NOTIFY x, 'y'"),
    ("prepare", "PREPARE p AS SELECT 1"),
    ("execute", "EXECUTE p"),
    ("show", "SHOW ALL"),
    ("values only", "VALUES (1)"),
    # functions
    ("pg_sleep", "SELECT pg_sleep(10)"),
    ("pg_sleep in where", "SELECT * FROM loans WHERE (SELECT pg_sleep(5)) IS NULL"),
    ("schema qualified pg_sleep", "SELECT pg_catalog.pg_sleep(10)"),
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd')"),
    ("pg_ls_dir", "SELECT * FROM pg_ls_dir('/')"),
    ("lo_import", "SELECT lo_import('/etc/passwd')"),
    ("lo_export", "SELECT lo_export(1, '/tmp/x')"),
    ("dblink", "SELECT * FROM dblink('host=x', 'select 1') AS t(a int)"),
    ("set_config", "SELECT set_config('statement_timeout', '0', false)"),
    ("current_setting", "SELECT current_setting('server_version')"),
    ("pg_terminate_backend", "SELECT pg_terminate_backend(pid) FROM loans"),
    ("pg_advisory_lock", "SELECT pg_advisory_lock(1)"),
    ("version", "SELECT version()"),
    ("current_user", "SELECT current_user"),
    ("session_user", "SELECT session_user"),
    ("current_database", "SELECT current_database()"),
    ("unknown function", "SELECT my_secret_function(loan_id) FROM loans"),
    ("uuid generator", "SELECT gen_random_uuid()"),
    ("function in table position", "SELECT * FROM pg_read_file('x')"),
    ("lateral function", "SELECT * FROM loans, LATERAL pg_read_file('x')"),
    ("function named like allowed one in other schema", "SELECT public.length('x')"),
    ("regclass cast", "SELECT 'pg_class'::regclass"),
    ("regproc cast", "SELECT 'pg_sleep'::regproc"),
    ("oid cast", "SELECT loan_id::oid FROM loans"),
    # tables and schemas
    ("pg_catalog table", "SELECT * FROM pg_catalog.pg_class"),
    ("pg_class", "SELECT * FROM pg_class"),
    ("pg_roles", "SELECT rolname FROM pg_roles"),
    ("pg_shadow", "SELECT * FROM pg_shadow"),
    ("pg_user", "SELECT * FROM pg_user"),
    ("information_schema", "SELECT * FROM information_schema.tables"),
    ("information_schema columns", "SELECT column_name FROM information_schema.columns"),
    ("app schema", "SELECT * FROM app.knowledge_items"),
    ("app query log", "SELECT question FROM app.query_log"),
    ("other dataset", "SELECT * FROM ds_other.loans"),
    ("public schema when dataset schema is set", "SELECT * FROM public.loans"),
    ("migrations table", "SELECT * FROM _schema_migrations"),
    ("cross database", "SELECT * FROM otherdb.ds_toy_library.loans"),
    ("quoted wrong case", 'SELECT * FROM "Loans"'),
    ("quoted pg_catalog", 'SELECT * FROM "pg_catalog"."pg_class"'),
    ("table in subquery", "SELECT * FROM loans WHERE loan_id IN (SELECT oid::text FROM pg_class)"),
    ("table in cte", "WITH x AS (SELECT * FROM pg_authid) SELECT * FROM x"),
    ("table in join", "SELECT * FROM loans l JOIN pg_stat_activity s ON true"),
    ("union with catalog", "SELECT loan_id FROM loans UNION SELECT rolname FROM pg_roles"),
    ("unknown table", "SELECT * FROM invoices"),
    # parameters
    ("named parameter", "SELECT * FROM loans WHERE loan_id = :id"),
    ("dollar parameter", "SELECT * FROM loans WHERE loan_id = $1"),
    ("question parameter", "SELECT * FROM loans WHERE loan_id = ?"),
    # not parseable / empty / abusive
    ("empty", ""),
    ("whitespace", "   \n  "),
    ("only a comment", "-- nothing"),
    ("gibberish", "SELEKT * FORM loans"),
    ("unbalanced parenthesis", "SELECT (1 FROM loans"),
    ("unterminated string", "SELECT 'abc FROM loans"),
    ("nul byte", "SELECT 1\x00; DROP TABLE loans"),
    ("too long", "SELECT " + ", ".join(["1"] * 12000)),
    ("deep nesting", "SELECT " + "(" * 3000 + "1" + ")" * 3000),
    ("markdown fence", "```sql\nSELECT * FROM loans\n```"),
    ("natural language", "Here is the query you asked for"),
    # unknown columns are refused before the database sees them
    ("unknown column", "SELECT nonsense FROM loans"),
    ("unknown column qualified", "SELECT l.nonsense FROM loans l"),
    ("ambiguous column", "SELECT isbn FROM loans l JOIN books b ON l.isbn = b.isbn"),
]


@pytest.mark.parametrize("label,sql", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_hostile_query_is_refused(label, sql, snap):
    result = check(sql, snap)
    assert isinstance(result, SqlRejected), f"{label} was accepted: {getattr(result, 'sql', '')}"
    assert result.message and result.code
    # a refusal never repeats raw secrets or driver text
    assert "\x1b" not in result.message


def test_the_hostile_corpus_is_large_enough():
    assert len(HOSTILE) >= 60


# ---------------------------------------------------------------------------
# Valid queries: the package's own examples and common PostgreSQL idioms
# ---------------------------------------------------------------------------

VALID = [
    "SELECT * FROM books",
    "SELECT title, price FROM books WHERE price > 10 ORDER BY price DESC LIMIT 5",
    "SELECT b.title, COUNT(*) AS n FROM loans l JOIN books b ON l.isbn = b.isbn GROUP BY b.title ORDER BY n DESC",
    "SELECT DISTINCT ON (isbn) isbn, loaned_on FROM loans ORDER BY isbn, loaned_on DESC",
    "SELECT COUNT(*) FILTER (WHERE status = 'L') AS late, COUNT(*) AS total FROM loans",
    "SELECT loan_id::text, late_fee::numeric(10,2) FROM loans",
    "SELECT CAST(page_count AS bigint) FROM books",
    "SELECT title FROM books WHERE title ILIKE '%history%'",
    "SELECT title FROM books WHERE title ~ '^The'",
    "SELECT title FROM books WHERE title NOT ILIKE 'a%' AND language IN ('EN', 'NO')",
    "SELECT status, ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY loaned_on) AS rn FROM loans",
    "SELECT member_id, SUM(late_fee) OVER (PARTITION BY member_id) FROM loans",
    "SELECT RANK() OVER w FROM loans WINDOW w AS (ORDER BY loaned_on)",
    "SELECT DATE_TRUNC('month', loaned_on) AS m, COUNT(*) FROM loans GROUP BY m ORDER BY m",
    "SELECT EXTRACT(YEAR FROM loaned_on) AS y, COUNT(*) FROM loans GROUP BY 1",
    "SELECT TO_CHAR(loaned_on, 'YYYY-MM') FROM loans",
    "SELECT loaned_on + INTERVAL '14 days' AS due FROM loans",
    "SELECT AGE(NOW(), joined_at) FROM members",
    "SELECT COALESCE(late_fee, 0), NULLIF(status, 'O'), GREATEST(1, 2), LEAST(1, 2) FROM loans",
    "SELECT CASE WHEN status = 'L' THEN 'late' ELSE 'ok' END AS bucket FROM loans",
    "SELECT UPPER(title), LOWER(title), LENGTH(title), SUBSTRING(title, 1, 3), TRIM(title) FROM books",
    "SELECT ROUND(AVG(price), 2), MIN(price), MAX(price), STDDEV(price) FROM books",
    "SELECT STRING_AGG(title, ', ') FROM books",
    "SELECT ARRAY_AGG(title ORDER BY title) FROM books",
    "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) FROM books",
    "SELECT a.full_name, (SELECT COUNT(*) FROM books b WHERE b.author_id = a.author_id) AS n FROM authors a",
    "SELECT * FROM books WHERE EXISTS (SELECT 1 FROM loans l WHERE l.isbn = books.isbn)",
    "SELECT * FROM books WHERE isbn NOT IN (SELECT isbn FROM loans)",
    "SELECT x.n FROM (SELECT COUNT(*) AS n FROM loans) x",
    "WITH c AS (SELECT isbn, COUNT(*) n FROM loans GROUP BY isbn) SELECT b.title, c.n FROM c JOIN books b ON b.isbn = c.isbn",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT n FROM r",
    "SELECT title FROM books UNION SELECT full_name FROM authors",
    "SELECT isbn FROM books EXCEPT SELECT isbn FROM loans",
    "SELECT l.loan_id FROM loans l LEFT JOIN books b ON b.isbn = l.isbn WHERE b.isbn IS NULL",
    "SELECT * FROM loans CROSS JOIN LATERAL (SELECT title FROM books WHERE books.isbn = loans.isbn) t",
    "SELECT * FROM books WHERE shelf_code = ANY(ARRAY['A1', 'B2'])",
    "SELECT d FROM GENERATE_SERIES(1, 5) AS d",
    "SELECT title, price FROM books ORDER BY price DESC NULLS LAST",
    "SELECT status, COUNT(*) FROM loans GROUP BY ROLLUP (status)",
    "SELECT title FROM books FETCH FIRST 5 ROWS ONLY",
    "SELECT title FROM books LIMIT 5 OFFSET 10",
    "SELECT loan_id FROM loans WHERE returned_at IS NULL AND due_on < CURRENT_DATE",
    "SELECT is_reference, COUNT(*) FROM books GROUP BY is_reference HAVING COUNT(*) > 1",
    "select\n  title -- the title\n from books /* all */ ;",
    f"SELECT title FROM {SCHEMA}.books",
    'SELECT "title" FROM "books"',
    "(SELECT title FROM books)",
]


@pytest.mark.parametrize("sql", VALID, ids=[f"valid{i}" for i in range(len(VALID))])
def test_valid_query_is_accepted(sql, snap):
    result = check(sql, snap)
    assert isinstance(result, ValidatedSql), getattr(result, "message", "")
    # what runs has no comment, a single statement and a limit
    assert "--" not in result.sql and "/*" not in result.sql
    assert result.sql.upper().count("LIMIT") >= 1 or "FETCH" in result.sql.upper()


def test_every_package_example_passes_for_both_packages(snap, o2c_package):
    for pkg_snap, schema in ((snap, SCHEMA), (CatalogSnapshot.from_package(o2c_package), "ds_o2c")):
        for example in pkg_snap.examples:
            result = GUARD.validate(example.sql, pkg_snap, schema_name=schema)
            assert isinstance(result, ValidatedSql), f"{example.id}: {getattr(result, 'message', '')}"


def test_o2c_examples_without_a_schema_name(o2c_package):
    o2c = CatalogSnapshot.from_package(o2c_package)
    for example in o2c.examples:
        assert isinstance(GUARD.validate(example.sql, o2c), ValidatedSql), example.id


# ---------------------------------------------------------------------------
# Row cap, rejection categories, extra functions
# ---------------------------------------------------------------------------


def test_missing_limit_gets_the_row_cap_plus_one(snap):
    result = check("SELECT * FROM books", snap, max_rows=200)
    assert result.row_cap == 200 and result.fetch_limit == 201 and result.user_limit is None
    assert result.sql.endswith("LIMIT 201")


def test_a_small_limit_is_kept(snap):
    result = check("SELECT * FROM books LIMIT 5", snap, max_rows=200)
    assert result.fetch_limit == 5 and result.user_limit == 5


def test_a_large_limit_is_lowered(snap):
    result = check("SELECT * FROM books LIMIT 100000", snap, max_rows=200)
    assert result.fetch_limit == 201 and result.user_limit is None
    assert "100000" not in result.sql


def test_limit_all_and_expressions_are_replaced(snap):
    assert check("SELECT * FROM books LIMIT ALL", snap, max_rows=50).fetch_limit == 51
    assert check("SELECT * FROM books LIMIT (SELECT 99999)", snap, max_rows=50).fetch_limit == 51


def test_fetch_first_becomes_a_limit(snap):
    result = check("SELECT * FROM books FETCH FIRST 7 ROWS ONLY", snap, max_rows=50)
    assert result.fetch_limit == 7 and "FETCH" not in result.sql.upper()
    assert check("SELECT * FROM books FETCH FIRST 90 PERCENT ROWS ONLY", snap, max_rows=50).fetch_limit == 51


def test_the_cap_applies_to_the_whole_union(snap):
    result = check("SELECT title FROM books UNION ALL SELECT full_name FROM authors", snap, max_rows=10)
    assert result.sql.endswith("LIMIT 11")


def test_offset_survives(snap):
    assert "OFFSET 10" in check("SELECT title FROM books LIMIT 5 OFFSET 10", snap).sql


def test_default_cap_comes_from_settings(snap):
    from src.config import override_settings

    with override_settings(SQL_MAX_ROWS=25):
        assert check("SELECT * FROM books", snap).fetch_limit == 26


def test_unknown_column_message_lists_real_columns(snap):
    result = check("SELECT titel FROM books", snap)
    assert result.category == "unknown_column" and result.repairable
    assert "titel" in result.message and "title" in result.message  # names the typo and the real columns


def test_unknown_table_message_lists_real_tables(snap):
    result = check("SELECT * FROM shelves", snap)
    assert result.category == "unknown_table" and "books" in result.message and result.repairable


def test_syntax_errors_are_repairable_and_clean(snap):
    result = check("SELECT FROM WHERE", snap)
    assert result.category == "syntax" and result.repairable
    assert "\x1b" not in result.message


def test_policy_refusals_are_not_repairable(snap):
    for sql in ("DELETE FROM loans", "SELECT pg_sleep(1)", "SELECT * FROM pg_class"):
        result = check(sql, snap)
        assert result.category in ("policy", "unknown_table") and not (result.category == "policy" and result.repairable)


def test_a_package_can_allow_extra_functions(snap):
    sql = "SELECT sparkline(page_count) FROM books"
    assert isinstance(check(sql, snap), SqlRejected)
    assert isinstance(check(sql, snap, extra_functions=("sparkline",)), ValidatedSql)
    # ...but the built-in blocklist still wins
    assert isinstance(check("SELECT pg_sleep(1)", snap, extra_functions=("pg_sleep",)), SqlRejected)


def test_without_a_dataset_schema_no_qualifier_is_allowed(snap):
    assert isinstance(GUARD.validate("SELECT * FROM books", snap, schema_name=None), ValidatedSql)
    assert isinstance(GUARD.validate("SELECT * FROM public.books", snap, schema_name=None), SqlRejected)
    assert isinstance(GUARD.validate(f"SELECT * FROM {SCHEMA}.books", snap, schema_name=None), SqlRejected)


def test_cte_may_shadow_nothing_dangerous(snap):
    # a CTE named like a system table is just a CTE
    result = check("WITH pg_class AS (SELECT 1 AS a) SELECT a FROM pg_class", snap)
    assert isinstance(result, ValidatedSql)
    assert result.tables == ()


def test_validated_sql_is_one_statement_without_comments(snap):
    result = check("SELECT title FROM books -- drop everything\n", snap)
    assert result.sql.count(";") == 0 and "drop" not in result.sql.lower()


def test_unquoted_identifiers_are_case_insensitive(snap):
    assert isinstance(check("SELECT TITLE FROM BOOKS", snap), ValidatedSql)


def test_validation_never_raises(snap):
    for weird in (chr(0x202E), "SELECT '" + chr(0x1F600) + "'", "SELECT 1 FROM " + "loans," * 400 + "books", None):
        assert isinstance(check(weird, snap), SqlRejected | ValidatedSql)


def test_package_copy_semantics_independent(toy_package: DatasetPackage):
    # the same guard instance serves different snapshots
    other = CatalogSnapshot.from_package(toy_package)
    assert isinstance(GUARD.validate("SELECT * FROM books", other), ValidatedSql)
