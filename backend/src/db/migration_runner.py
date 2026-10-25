"""Database migration logic for PostgreSQL."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.utils.logger import get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_CREATE_EXTENSION = re.compile(r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", re.IGNORECASE)


@dataclass
class MigrationFile:
    version: str
    name: str
    category: str
    filepath: Path


@dataclass
class MigrationStatus:
    version: str
    name: str
    status: str
    applied_at: str | None
    checksum: str | None


def _get_checksum(content: str) -> str:
    """Compute SHA-256 checksum of SQL content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _ensure_migrations_table(conn) -> None:
    """Create the _schema_migrations table if it doesn't exist."""
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                version VARCHAR(14) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                category VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(64) NOT NULL
            )
            """
        )
    )


def _get_local_migrations() -> list[MigrationFile]:
    """Discover all migration files from migrations/schema and migrations/seed."""
    migrations = []
    for category in ["schema", "seed"]:
        cat_dir = MIGRATIONS_DIR / category
        if cat_dir.exists():
            for filepath in cat_dir.glob("V*__*.sql"):
                # Filename format: V{version}__{name}.sql
                filename = filepath.name
                if filename.startswith("V") and "__" in filename:
                    version = filename[1:].split("__")[0]
                    name = filename.split("__", 1)[1].removesuffix(".sql")
                    migrations.append(
                        MigrationFile(
                            version=version,
                            name=name,
                            category=category,
                            filepath=filepath,
                        )
                    )
    # Sort strictly by version
    migrations.sort(key=lambda m: m.version)
    return migrations


async def get_status(engine: AsyncEngine) -> list[MigrationStatus]:
    """Get the current state of migrations."""
    local_migs = _get_local_migrations()
    
    applied = {}
    async with engine.begin() as conn:
        await _ensure_migrations_table(conn)
        result = await conn.execute(
            text("SELECT version, name, status, applied_at, checksum FROM _schema_migrations")
        )
        for row in result:
            applied[row.version] = row

    statuses = []
    for m in local_migs:
        content = m.filepath.read_text(encoding="utf-8")
        current_checksum = _get_checksum(content)

        if m.version in applied:
            row = applied[m.version]
            if row.checksum != current_checksum and row.status != "baselined":
                status = "checksum_mismatch"
            else:
                status = row.status
            statuses.append(
                MigrationStatus(
                    version=m.version,
                    name=m.name,
                    status=status,
                    applied_at=str(row.applied_at),
                    checksum=row.checksum,
                )
            )
        else:
            statuses.append(
                MigrationStatus(
                    version=m.version,
                    name=m.name,
                    status="pending",
                    applied_at=None,
                    checksum=None,
                )
            )
    return statuses


async def _missing_extensions(conn, content: str) -> list[str]:
    """Extensions a migration creates that this server does not offer (for example pgvector)."""
    wanted = {m.group(1).lower() for m in _CREATE_EXTENSION.finditer(content)}
    if not wanted:
        return []
    result = await conn.execute(text("SELECT name FROM pg_available_extensions"))
    available = {row[0].lower() for row in result}
    return sorted(wanted - available)


async def apply_pending(engine: AsyncEngine, skipped: list[str | None] = None) -> list[MigrationFile]:
    """Apply all pending migrations in version order.

    A migration that needs a PostgreSQL extension the server does not provide is
    not applied and stays pending (its version is appended to ``skipped``), so the
    rest of the schema can still be created; it is applied by a later run once the
    extension is installed.
    """
    local_migs = _get_local_migrations()
    applied_this_run = []

    async with engine.begin() as conn:
        await _ensure_migrations_table(conn)

    for m in local_migs:
        # Wrap each migration in its own transaction block
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT status FROM _schema_migrations WHERE version = :v"),
                {"v": m.version},
            )
            row = result.fetchone()
            if row:
                continue  # already applied or baselined

            content = m.filepath.read_text(encoding="utf-8")
            checksum = _get_checksum(content)

            missing = await _missing_extensions(conn, content)
            if missing:
                logger.warning(
                    "Skipping %s__%s: PostgreSQL extension(s) %s not available on this server. It stays pending.",
                    m.version, m.name, ", ".join(missing),
                )
                if skipped is not None:
                    skipped.append(m.version)
                continue

            logger.info("Applying %s__%s (%s)...", m.version, m.name, m.category)

            # Apply the SQL file — split by semicolons because asyncpg
            # does not support multiple statements in a single prepared stmt.
            if content.strip():
                # Strip comments and split on semicolons
                lines = [line for line in content.splitlines() if not line.strip().startswith("--")]
                clean_sql = "\n".join(lines)
                for stmt in clean_sql.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conn.execute(text(stmt))
            
            # Record it
            await conn.execute(
                text(
                    """
                    INSERT INTO _schema_migrations
                    (version, name, category, status, checksum)
                    VALUES (:v, :n, :c, 'applied', :chk)
                    """
                ),
                {"v": m.version, "n": m.name, "c": m.category, "chk": checksum},
            )
            applied_this_run.append(m)

    return applied_this_run


async def baseline(engine: AsyncEngine, upto: str) -> list[MigrationFile]:
    """Mark all migrations up to a certain version as applied without executing them."""
    local_migs = _get_local_migrations()
    baselined_this_run = []

    async with engine.begin() as conn:
        await _ensure_migrations_table(conn)
        
        for m in local_migs:
            if m.version > upto:
                break
                
            result = await conn.execute(
                text("SELECT status FROM _schema_migrations WHERE version = :v"),
                {"v": m.version},
            )
            if result.fetchone():
                continue  # already applied or baselined
                
            content = m.filepath.read_text(encoding="utf-8")
            checksum = _get_checksum(content)
            
            await conn.execute(
                text(
                    """
                    INSERT INTO _schema_migrations
                    (version, name, category, status, checksum)
                    VALUES (:v, :n, :c, 'baselined', :chk)
                    """
                ),
                {"v": m.version, "n": m.name, "c": m.category, "chk": checksum},
            )
            baselined_this_run.append(m)

    return baselined_this_run


def create_migration(name: str, category: str) -> str:
    """Create a new migration file."""
    if category not in ("schema", "seed"):
        raise ValueError(f"Invalid category: {category}")
        
    cat_dir = MIGRATIONS_DIR / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    
    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    clean_name = name.lower().replace(" ", "_").replace("-", "_")
    
    filename = f"V{version}__{clean_name}.sql"
    filepath = cat_dir / filename
    
    filepath.write_text(f"-- Migration: {name}\n-- Category: {category}\n\n", encoding="utf-8")
    
    return str(filepath)
