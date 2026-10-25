"""Creating, swapping, rolling back and dropping the schema generations of a dataset.

A load builds a complete new generation in a *staging* schema, then ``swap``
renames schemas inside one transaction::

    ds_x__prev  <- dropped
    ds_x        -> ds_x__prev      (the old live generation is kept for rollback)
    ds_x__r1234 -> ds_x            (the new generation goes live)

PostgreSQL DDL is transactional, so a reader sees the old generation or the new
one, never a mixture.  Renaming a schema takes no lock on its tables, so the
swap does not wait for running queries (it only waits for them when it has to
drop the generation before last, bounded by a lock timeout).

Everything here runs on the *owner* engine (see ``src.storage.engines``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from sqlalchemy import Connection, Engine, text

from src.datasets.ddl import index_ddl, quote_ident, table_ddl, table_indexes
from src.datasets.models import DatasetPackage
from src.storage.engines import get_owner_sync_engine
from src.storage.roles import existing_roles, grant_read
from src.storage.schema_names import (
    live_schema,
    previous_schema,
    staging_prefix,
    staging_schema,
)

SWAP_LOCK_TIMEOUT = "15s"


class SchemaError(RuntimeError):
    """A schema operation could not be carried out.  The message is safe to show to an operator."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _engine(engine: Engine | None) -> Engine:
    return engine or get_owner_sync_engine()


def _q(schema: str) -> str:
    return quote_ident(schema)


def schema_exists(conn: Connection, schema: str) -> bool:
    return bool(conn.execute(text("SELECT to_regnamespace(:s) IS NOT NULL"), {"s": schema}).scalar())


def tables_in(conn: Connection, schema: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relkind IN ('r', 'p') ORDER BY c.relname"
        ),
        {"s": schema},
    )
    return [r[0] for r in rows]


def has_app_schema(conn: Connection) -> bool:
    return schema_exists(conn, "app")


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------


class DatasetLock:
    """A session-level advisory lock on one dataset, held on a connection of its own.

    A crashed process loses its connection and with it the lock, so a lock can
    never be left behind.  (It needs a direct connection: a transaction-pooling
    proxy in front of PostgreSQL would hand the lock to the wrong session.)
    """

    def __init__(self, engine: Engine, dataset_id: str, purpose: str = "ingest"):
        self.engine = engine
        self.key = f"graphsense:{purpose}:{dataset_id}"
        self._conn: Connection | None = None

    def acquire(self) -> bool:
        conn = self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            got = conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": self.key}).scalar()
        except Exception:
            conn.close()
            raise
        if not got:
            conn.close()
            return False
        self._conn = conn
        return True

    def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": self.key})
        except Exception:
            conn.invalidate()  # closing the physical connection frees the lock
        finally:
            conn.close()

    def __enter__(self) -> Self:
        if not self.acquire():
            raise SchemaError("busy", "Another operation is running on this dataset.")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def create_staging(pkg: DatasetPackage, run_id: str, *, engine: Engine | None = None) -> str:
    """Create the empty tables of a new generation and return the staging schema name.

    Secondary indexes are added later by :func:`create_indexes`, once the data is in.
    The application roles (if they exist) are granted read access now, so the swap
    needs no grants: privileges travel with the schema.
    """
    schema = staging_schema(pkg.id, run_id)
    with _engine(engine).begin() as conn:
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {_q(schema)} CASCADE")
        conn.exec_driver_sql(f"CREATE SCHEMA {_q(schema)}")
        for table in pkg.tables:
            conn.exec_driver_sql(table_ddl(table, schema))
        grant_read(conn, schema, existing_roles(conn))
    return schema


def create_indexes(pkg: DatasetPackage, schema: str, *, engine: Engine | None = None) -> int:
    """Create the secondary indexes of every table in ``schema``.  Returns how many."""
    count = 0
    with _engine(engine).begin() as conn:
        for table in pkg.tables:
            for columns in table_indexes(pkg, table):
                conn.exec_driver_sql(index_ddl(table, columns, schema))
                count += 1
    return count


def analyze(pkg: DatasetPackage, schema: str, *, engine: Engine | None = None) -> None:
    """Collect planner statistics so the first queries after a swap are planned well."""
    with _engine(engine).connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in pkg.tables:
            conn.exec_driver_sql(f"ANALYZE {_q(schema)}.{quote_ident(table.table)}")


def drop_schema(schema: str, *, engine: Engine | None = None) -> None:
    with _engine(engine).begin() as conn:
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {_q(schema)} CASCADE")


def drop_orphan_staging(dataset_id: str, *, keep: str | None = None, engine: Engine | None = None) -> list[str]:
    """Drop staging schemas left behind by runs that died.  Call while holding the dataset lock."""
    prefix = staging_prefix(dataset_id)
    dropped = []
    with _engine(engine).begin() as conn:
        names = [r[0] for r in conn.execute(text("SELECT nspname FROM pg_namespace"))]
        for name in names:
            if name.startswith(prefix) and name != keep and len(name) == len(prefix) + 8:
                conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {_q(name)} CASCADE")
                dropped.append(name)
    return dropped


# ---------------------------------------------------------------------------
# Compatibility views (stage-1 images read the dataset tables from ``public``)
# ---------------------------------------------------------------------------


def drop_compat_views(conn: Connection, tables: list[str]) -> None:
    """Drop ``public.<table>`` where it is a view.  A real table of that name is never touched."""
    for table in tables:
        kind = conn.execute(
            text("SELECT c.relkind FROM pg_class c WHERE c.oid = to_regclass(:n)"), {"n": f"public.{quote_ident(table)}"}
        ).scalar()
        if kind == "v":
            conn.exec_driver_sql(f"DROP VIEW public.{quote_ident(table)}")


def create_compat_views(conn: Connection, schema: str, tables: list[str]) -> None:
    roles = existing_roles(conn)
    for table in tables:
        conn.exec_driver_sql(
            f"CREATE VIEW public.{quote_ident(table)} AS SELECT * FROM {_q(schema)}.{quote_ident(table)}"
        )
        for role in roles:
            conn.exec_driver_sql(f'GRANT SELECT ON public.{quote_ident(table)} TO "{role}"')


# ---------------------------------------------------------------------------
# Swap, rollback, drop
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwapResult:
    live: str
    previous: str | None
    had_previous: bool


def _dataset_row(conn: Connection, dataset_id: str):
    if not has_app_schema(conn):
        return None
    return conn.execute(
        text(
            "SELECT compat_views, active_run_id, previous_run_id, status FROM app.datasets WHERE id = :id FOR UPDATE"
        ),
        {"id": dataset_id},
    ).first()


def _begin_exclusive(conn: Connection, dataset_id: str) -> None:
    conn.exec_driver_sql(f"SET LOCAL lock_timeout = '{SWAP_LOCK_TIMEOUT}'")
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"graphsense:swap:{dataset_id}"})


def swap(
    dataset_id: str,
    staging: str,
    *,
    package: DatasetPackage | None = None,
    run_id: str | None = None,
    engine: Engine | None = None,
) -> SwapResult:
    """Make ``staging`` the live generation of ``dataset_id`` (atomically).

    When ``package`` and ``run_id`` are given the dataset record in ``app.datasets``
    is updated in the same transaction, so the record and the schemas never disagree.
    """
    live, prev = live_schema(dataset_id), previous_schema(dataset_id)
    with _engine(engine).begin() as conn:
        _begin_exclusive(conn, dataset_id)
        if not schema_exists(conn, staging):
            raise SchemaError("staging_missing", "The new generation is missing.")
        row = _dataset_row(conn, dataset_id)
        compat = bool(row and row.compat_views)
        live_exists = schema_exists(conn, live)

        if compat:
            drop_compat_views(conn, tables_in(conn, live) if live_exists else [])
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {_q(prev)} CASCADE")
        if live_exists:
            conn.exec_driver_sql(f"ALTER SCHEMA {_q(live)} RENAME TO {_q(prev)}")
        conn.exec_driver_sql(f"ALTER SCHEMA {_q(staging)} RENAME TO {_q(live)}")
        if compat:
            create_compat_views(conn, live, tables_in(conn, live))

        if has_app_schema(conn):
            _upsert_dataset(
                conn, dataset_id, package=package, run_id=run_id,
                previous_run_id=row.active_run_id if row else None, status="ready",
                keep_previous=run_id is None,
            )
    return SwapResult(live=live, previous=prev if live_exists else None, had_previous=live_exists)


def _upsert_dataset(
    conn: Connection,
    dataset_id: str,
    *,
    package: DatasetPackage | None,
    run_id: str | None,
    previous_run_id: str | None,
    status: str,
    keep_previous: bool = False,
    compat_views: bool | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO app.datasets
                (id, package_id, package_version, package_hash, schema_name, status,
                 active_run_id, previous_run_id, compat_views)
            VALUES (:id, :pid, :ver, :hash, :schema, :status, :run, :prev, COALESCE(:compat, false))
            ON CONFLICT (id) DO UPDATE SET
                package_id = EXCLUDED.package_id,
                package_version = EXCLUDED.package_version,
                package_hash = EXCLUDED.package_hash,
                schema_name = EXCLUDED.schema_name,
                status = EXCLUDED.status,
                active_run_id = COALESCE(EXCLUDED.active_run_id, app.datasets.active_run_id),
                previous_run_id = CASE WHEN :keep THEN app.datasets.previous_run_id ELSE EXCLUDED.previous_run_id END,
                compat_views = COALESCE(:compat, app.datasets.compat_views),
                updated_at = now()
            """
        ),
        {
            "id": dataset_id,
            "pid": package.id if package else dataset_id,
            "ver": package.version if package else "0.0.0",
            "hash": package.content_hash if package else "",
            "schema": live_schema(dataset_id),
            "status": status,
            "run": run_id,
            "prev": previous_run_id,
            "keep": keep_previous,
            "compat": compat_views,
        },
    )


def register_dataset(
    conn: Connection, dataset_id: str, package: DatasetPackage, *, status: str, run_id: str | None,
    compat_views: bool,
) -> None:
    """Create or update the dataset record inside the caller's transaction (used by adoption)."""
    _upsert_dataset(
        conn, dataset_id, package=package, run_id=run_id, previous_run_id=None, status=status,
        compat_views=compat_views,
    )


def rollback(dataset_id: str, *, engine: Engine | None = None) -> SwapResult:
    """Exchange the live and the previous generation.

    Running it twice undoes it (a roll forward), as long as no new load happened in between.
    """
    live, prev = live_schema(dataset_id), previous_schema(dataset_id)
    tmp = f"{live}__swap"
    with _engine(engine).begin() as conn:
        _begin_exclusive(conn, dataset_id)
        if not schema_exists(conn, prev):
            raise SchemaError("no_previous_generation", "There is no previous generation to roll back to.")
        row = _dataset_row(conn, dataset_id)
        compat = bool(row and row.compat_views)
        live_exists = schema_exists(conn, live)

        if compat:
            drop_compat_views(conn, tables_in(conn, live) if live_exists else [])
        if live_exists:
            conn.exec_driver_sql(f"ALTER SCHEMA {_q(live)} RENAME TO {_q(tmp)}")
            conn.exec_driver_sql(f"ALTER SCHEMA {_q(prev)} RENAME TO {_q(live)}")
            conn.exec_driver_sql(f"ALTER SCHEMA {_q(tmp)} RENAME TO {_q(prev)}")
        else:
            conn.exec_driver_sql(f"ALTER SCHEMA {_q(prev)} RENAME TO {_q(live)}")
        if compat:
            create_compat_views(conn, live, tables_in(conn, live))

        if row is not None:
            new_active = row.previous_run_id
            kind = None
            if new_active:
                kind = conn.execute(
                    text("SELECT kind FROM app.ingestion_runs WHERE id = :r"), {"r": str(new_active)}
                ).scalar()
            conn.execute(
                text(
                    "UPDATE app.datasets SET active_run_id = :a, previous_run_id = :p, status = :s, "
                    "updated_at = now() WHERE id = :id"
                ),
                {
                    "a": str(new_active) if new_active else None,
                    "p": str(row.active_run_id) if row.active_run_id else None,
                    "s": "legacy" if kind == "adopt" else "ready",
                    "id": dataset_id,
                },
            )
    return SwapResult(live=live, previous=prev if live_exists else None, had_previous=live_exists)


def drop_dataset(dataset_id: str, *, engine: Engine | None = None) -> list[str]:
    """Remove every generation of a dataset and its record.  Run history is kept."""
    live, prev = live_schema(dataset_id), previous_schema(dataset_id)
    dropped: list[str] = []
    with _engine(engine).begin() as conn:
        _begin_exclusive(conn, dataset_id)
        row = _dataset_row(conn, dataset_id)
        if schema_exists(conn, live):
            if row and row.compat_views:
                drop_compat_views(conn, tables_in(conn, live))
            conn.exec_driver_sql(f"DROP SCHEMA {_q(live)} CASCADE")
            dropped.append(live)
        if schema_exists(conn, prev):
            conn.exec_driver_sql(f"DROP SCHEMA {_q(prev)} CASCADE")
            dropped.append(prev)
        if has_app_schema(conn):
            conn.execute(text("DELETE FROM app.datasets WHERE id = :id"), {"id": dataset_id})
            # Derived data other features keep per dataset (catalog builds and the like).
            derived = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns WHERE table_schema = 'app' "
                    "AND column_name = 'dataset_id' AND table_name LIKE 'catalog\\_%'"
                )
            )
            for (name,) in derived.all():
                conn.execute(text(f'DELETE FROM app."{name}" WHERE dataset_id = :id'), {"id": dataset_id})
    dropped += drop_orphan_staging(dataset_id, engine=engine)
    return dropped


def generations(dataset_id: str, *, engine: Engine | None = None) -> dict[str, bool]:
    """Which generations exist: ``{"live": bool, "previous": bool}``."""
    with _engine(engine).connect() as conn:
        return {
            "live": schema_exists(conn, live_schema(dataset_id)),
            "previous": schema_exists(conn, previous_schema(dataset_id)),
        }
