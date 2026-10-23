"""Database roles and their privileges.

Three roles keep the blast radius of each part of the product small:

``owner``  (whatever ``OWNER_DATABASE_DSN`` / ``DATABASE_DSN`` connects as)
    creates schemas and tables, loads data, runs migrations.
``graphsense_app``
    the API: read the dataset schemas, read and write ``app.*``.
``graphsense_ro``
    generated SQL only: read the dataset schemas, nothing else; read-only
    transactions and a statement timeout are role defaults.

``provision_roles`` is idempotent.  The roles are optional: a development
database works with a single role, and schema creation grants to the roles
only when they exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from src.storage.schema_names import is_dataset_schema

APP_ROLE = "graphsense_app"
READONLY_ROLE = "graphsense_ro"
ROLES = (APP_ROLE, READONLY_ROLE)


@dataclass
class RolesReport:
    created: list[str] = field(default_factory=list)
    login_enabled: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def existing_roles(conn: Connection) -> list[str]:
    rows = conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"), {"names": list(ROLES)})
    found = {r[0] for r in rows}
    return [r for r in ROLES if r in found]


def grant_read(conn: Connection, schema: str, roles: list[str] | None = None) -> None:
    """Let the application roles read every table of ``schema`` (and see the schema)."""
    for role in roles if roles is not None else existing_roles(conn):
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{_checked(schema)}" TO "{role}"'))
        conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))


def _checked(schema: str) -> str:
    if not (is_dataset_schema(schema) or schema in ("public", "app")):
        raise ValueError("unexpected schema name")
    return schema


def _exec_format(conn: Connection, template: str, *args: object) -> None:
    """Run a statement built server-side by ``format`` (so identifiers and literals are quoted by PostgreSQL)."""
    placeholders = ", ".join(f":a{i}" for i in range(len(args)))
    statement = conn.execute(
        text(f"SELECT format(:t{', ' + placeholders if args else ''})"),
        {"t": template, **{f"a{i}": a for i, a in enumerate(args)}},
    ).scalar_one()
    # A raw cursor without parameters: nothing in the statement (a password may
    # contain "%") is interpreted by the driver.
    conn.connection.cursor().execute(statement)


def provision_roles(
    engine: Engine,
    *,
    app_password: str | None = None,
    readonly_password: str | None = None,
    statement_timeout_ms: int = 5000,
    legacy_tables: tuple[str, ...] = (),
) -> RolesReport:
    """Create the application roles and grant them what they need.  Safe to repeat.

    ``legacy_tables`` names dataset tables that may still sit in the ``public``
    schema (a database not yet adopted); the roles get SELECT on those.
    """
    report = RolesReport()
    passwords = {APP_ROLE: app_password, READONLY_ROLE: readonly_password}
    with engine.begin() as conn:
        database = conn.execute(text("SELECT current_database()")).scalar_one()
        have = set(existing_roles(conn))
        for role in ROLES:
            password = passwords[role]
            if role not in have:
                if password:
                    _exec_format(conn, "CREATE ROLE %I LOGIN PASSWORD %L", role, password)
                    report.login_enabled.append(role)
                else:
                    _exec_format(conn, "CREATE ROLE %I NOLOGIN", role)
                    report.notes.append(
                        f"{role} was created without a password and cannot log in yet: "
                        "run this command again with its password option."
                    )
                report.created.append(role)
            elif password:
                _exec_format(conn, "ALTER ROLE %I LOGIN PASSWORD %L", role, password)
                report.login_enabled.append(role)
            _exec_format(conn, "GRANT CONNECT ON DATABASE %I TO %I", database, role)

        # Generated SQL: read-only transactions and short statements, whatever the application does.
        conn.execute(text(f'ALTER ROLE "{READONLY_ROLE}" SET default_transaction_read_only = on'))
        conn.execute(text(f'ALTER ROLE "{READONLY_ROLE}" SET statement_timeout = {int(statement_timeout_ms)}'))
        conn.execute(text(f'ALTER ROLE "{READONLY_ROLE}" SET lock_timeout = 2000'))
        conn.execute(text(f'ALTER ROLE "{READONLY_ROLE}" SET idle_in_transaction_session_timeout = 15000'))

        # app.*: the API reads and writes; generated SQL cannot even see the schema.
        has_app = conn.execute(text("SELECT to_regnamespace('app') IS NOT NULL")).scalar_one()
        if has_app:
            conn.execute(text(f'GRANT USAGE ON SCHEMA app TO "{APP_ROLE}"'))
            conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO "{APP_ROLE}"'))
            conn.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO "{APP_ROLE}"'))
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{APP_ROLE}"'))
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO "{APP_ROLE}"'))
            conn.execute(text(f'REVOKE ALL ON SCHEMA app FROM "{READONLY_ROLE}"'))
        else:
            report.notes.append("schema app does not exist yet: run `graphsense db migrate`, then this command again.")

        for table in legacy_tables:
            exists = conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{table}"}).scalar_one()
            if exists:
                for role in ROLES:
                    _exec_format(conn, "GRANT SELECT ON public.%I TO %I", table, role)

        # Dataset schemas that exist now (new generations are granted when they are staged).
        schemas = [
            r[0]
            for r in conn.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ds\\_%'"))
        ]
        for schema in schemas:
            if is_dataset_schema(schema):
                grant_read(conn, schema, list(ROLES))
    return report
