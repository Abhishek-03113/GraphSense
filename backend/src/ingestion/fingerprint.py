"""Source fingerprints: "is there anything new to load?".

The fingerprint covers the package (its content hash), the version of the load
logic and the name, size and sha256 of every source file, in sorted order.  Two
runs with the same fingerprint would build identical data, so the second is
skipped.  Only relative names are hashed, so moving the data root does not
change it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from src.datasets.models import DatasetPackage
from src.ingestion.readers import (
    SourceFile,
    file_sha256,
    resolve_source_dir,
    table_files,
)

# Bump when a change to coercion or loading would produce different rows from the same files.
LOADER_VERSION = "1"


@dataclass
class SourcePlan:
    fingerprint: str
    files: dict[str, list[SourceFile]] = field(default_factory=dict)  # table -> files (sorted)
    missing: list[str] = field(default_factory=list)  # tables whose directory does not exist
    hashes: dict[str, str] = field(default_factory=dict)  # relative path -> sha256

    @property
    def file_count(self) -> int:
        return sum(len(v) for v in self.files.values())

    @property
    def byte_count(self) -> int:
        return sum(f.size for v in self.files.values() for f in v)


def plan_sources(package: DatasetPackage, data_root: Path) -> SourcePlan:
    """List the source files of every table and compute the run's fingerprint."""
    base = resolve_source_dir(data_root, package)
    plan = SourcePlan(fingerprint="")
    digest = hashlib.sha256()
    digest.update(f"package:{package.content_hash}\nloader:{LOADER_VERSION}\n".encode())
    for table in sorted(package.tables, key=lambda t: t.table):
        files = table_files(base, data_root, table)
        if files is None:
            plan.missing.append(table.table)
            digest.update(f"table:{table.table}:missing\n".encode())
            continue
        plan.files[table.table] = files
        digest.update(f"table:{table.table}:{len(files)}\n".encode())
        for f in files:
            sha = file_sha256(f.path)
            plan.hashes[f.relative] = sha
            digest.update(f"file:{f.relative}:{f.size}:{sha}\n".encode())
    plan.fingerprint = digest.hexdigest()
    return plan
