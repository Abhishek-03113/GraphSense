# Data Ingestion Task

## Goal
Create a one-time script for data ingestion into PostgreSQL.

## Behavior Contract
- **Given:** Provided SAP O2C JSONL files in `data/sap-o2c-data/` and `data modelling/ddl.sql`.
- **When:** Running the ingestion script on a PostgreSQL database.
- **Then:** All 19 tables are created exactly as specified in `ddl.sql` and populated with JSONL data without errors. Duplicate runs should upsert data safely or truncate before load.
- **Out of Scope:** Graph edge generation, API endpoints, AI query sandbox, chat functionalities.

## Baseline Snapshot
- Currently empty database with no tables or data.

## Implementation Checklist
- [ ] Set up PostgreSQL docker container or local DB connection.
- [ ] Connect Python script (using psycopg2/asyncpg or SQLAlchemy) to the DB.
- [ ] Run `data modelling/ddl.sql` to initialize the 19 tables. 
- [ ] Write reading logic for each of the 19 JSONL entity files.
- [ ] Write bulk insert logic mapping JSONL formats to the target tables (handling specific formatting for types where needed).
- [ ] Verify idempotency (e.g., TRUNCATE CASCADE before load for the one-time script).

## Acceptance Checks
```bash
# Verify ingestion script
python scripts/ingest_data.py

# Check database table counts
psql -c "SELECT tablename, n_live_tup FROM pg_stat_user_tables ORDER BY tablename;"
```

## Evidence Bundle
- `[ ]` Logs of the script parsing files successfully.
- `[ ]` `psql` output showing non-zero row counts for all 19 created tables mapping perfectly to the JSONL dataset files.
