"""CLI: Schema migration runner for PostgreSQL.

Usage:
  python migrate.py apply                                  Apply all pending migrations
  python migrate.py status                                 Show migration status
  python migrate.py baseline --upto 20240324123000         Mark migrations as applied without executing
  python migrate.py create --name <desc> [--type schema|seed] Create a new migration file
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.db.engine import engine
from src.db.migration_runner import (
    apply_pending,
    baseline,
    create_migration,
    get_status,
)


async def _cmd_apply() -> int:
    print(f"Applying pending migrations to database ...")
    applied = await apply_pending(engine)
    if applied:
        print(f"\nDone. Applied {len(applied)} migration(s):")
        for mf in applied:
            print(f"  {mf.version}__{mf.name}")
    else:
        print("No pending migrations. Database is up to date.")
    return 0


async def _cmd_status() -> int:
    statuses = await get_status(engine)
    if not statuses:
        print("No migration files found in migrations/ directory.")
        return 0

    ver_w = max((len(s.version) for s in statuses), default=7)
    name_w = max((len(s.name) for s in statuses), default=4)
    stat_w = max((len(s.status) for s in statuses), default=6)

    header = (
        f"{'VERSION':<{ver_w}}  {'NAME':<{name_w}}  "
        f"{'STATUS':<{stat_w}}  APPLIED_AT"
    )
    print(f"\nMigration status for database:\n")
    print(header)
    print("-" * len(header))
    for s in statuses:
        applied = s.applied_at or ""
        print(
            f"{s.version:<{ver_w}}  {s.name:<{name_w}}  "
            f"{s.status:<{stat_w}}  {applied}"
        )
    print()

    pending = [s for s in statuses if s.status == "pending"]
    mismatched = [s for s in statuses if s.status == "checksum_mismatch"]
    if mismatched:
        print(f"WARNING: {len(mismatched)} migration(s) have checksum mismatches!")
    if pending:
        print(f"{len(pending)} migration(s) pending.")
    else:
        print("All migrations applied.")
    return 0


async def _cmd_baseline(args: argparse.Namespace) -> int:
    print(
        f"Baselining up to {args.upto} "
        f"(marking as applied without executing) ..."
    )
    baselined = await baseline(engine, args.upto)
    if baselined:
        print(f"Baselined {len(baselined)} migration(s):")
        for mf in baselined:
            print(f"  {mf.version}__{mf.name}")
    else:
        print("Nothing to baseline (already recorded or no matching files).")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    filepath = create_migration(name=args.name, category=args.type)
    print(f"Created migration: {filepath}")
    return 0


async def amain() -> int:
    parser = argparse.ArgumentParser(
        description="Schema migration runner for PostgreSQL."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # apply
    subparsers.add_parser(
        "apply", help="Apply all pending migrations to the database"
    )

    # status
    subparsers.add_parser(
        "status", help="Show migration status for the database"
    )

    # baseline
    baseline_parser = subparsers.add_parser(
        "baseline",
        help="Mark migrations up to a version as applied without executing",
    )
    baseline_parser.add_argument(
        "--upto",
        required=True,
        help="Version to baseline up to (e.g. 20240324123000)",
    )

    # create
    create_parser = subparsers.add_parser(
        "create", help="Create a new migration file with the next version number"
    )
    create_parser.add_argument(
        "--name",
        required=True,
        help="Migration description (e.g. 'add billing schema')",
    )
    create_parser.add_argument(
        "--type",
        choices=["schema", "seed"],
        default="schema",
        help="Migration category: schema (DDL) or seed (data). Default: schema",
    )

    args = parser.parse_args()

    try:
        if args.command == "apply":
            return await _cmd_apply()
        if args.command == "status":
            return await _cmd_status()
        if args.command == "baseline":
            return await _cmd_baseline(args)
        if args.command == "create":
            return _cmd_create(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        # Crucial: Dispose engine pools after script usage
        from src.db.engine import dispose_engine
        await dispose_engine()

    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
