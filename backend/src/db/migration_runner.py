"""Database migration logic for PostgreSQL."""

import asyncio
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


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
    applied_at: Optional[str]
    checksum: Optional[str]


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


def _get_local_migrations() -> List[MigrationFile]:
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


async def get_status(engine: AsyncEngine) -> List[MigrationStatus]:
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


async def apply_pending(engine: AsyncEngine) -> List[MigrationFile]:
    """Apply all pending migrations in version order."""
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

            print(f"Applying {m.version}__{m.name} ({m.category})...")
            content = m.filepath.read_text(encoding="utf-8")
            checksum = _get_checksum(content)

            # Apply the SQL file — split by semicolons because asyncpg
            # does not support multiple statements in a single prepared stmt.
            if content.strip():
                # Strip comments and split on semicolons
                lines = [l for l in content.splitlines() if not l.strip().startswith("--")]
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


async def baseline(engine: AsyncEngine, upto: str) -> List[MigrationFile]:
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
    
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    clean_name = name.lower().replace(" ", "_").replace("-", "_")
    
    filename = f"V{version}__{clean_name}.sql"
    filepath = cat_dir / filename
    
    filepath.write_text(f"-- Migration: {name}\n-- Category: {category}\n\n", encoding="utf-8")
    
    return str(filepath)
