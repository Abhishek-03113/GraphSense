# Database Migrations

This folder relies on a custom PostgreSQL migration runner leveraging the async SQLAlchemy engine.

## General Usage

Run these commands from `backend/`:

- **Show Status:** `uv run python migrate.py status`
- **Apply Migrations:** `uv run python migrate.py apply`
- **Create Schema Migration:** `uv run python migrate.py create --name "create_users_table" --type schema`
- **Create Seed Migration:** `uv run python migrate.py create --name "seed_users" --type seed` 
- **Baseline DB:** `uv run python migrate.py baseline --upto 20240324123456`

## Idempotency is Critical

While the runner tracks successfully applied migrations using the `_schema_migrations` table, **you are highly encouraged to write idempotent SQL commands** where possible to avoid half-applied transactional issues or side effects while working in development.

- **Prefer** `CREATE TABLE IF NOT EXISTS` over `CREATE TABLE`.
- **Prefer** `INSERT INTO ... ON CONFLICT DO NOTHING` instead of a plain `INSERT`.
- **Prefer** idempotent column additions by checking constraints first if your dialect/version supports it (or wrap cleanly in DDL updates).

*Note:* Seed scripts are often run alongside schema updates. Separate them properly during generation so they run nicely and can also easily be ignored in a production environment if desired.
