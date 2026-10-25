#!/bin/sh
# Container entry point: bring the database schema up to date, then serve.
#
#   graphsense db migrate        applies pending migrations (as the owner role)
#
# Loading data is a separate operator step: `graphsense ingest <dataset>`.
#
# WEB_CONCURRENCY server processes share the port (default: one per CPU, at most 2).
# Each opens its own database pools, up to DB_POOL_SIZE + DB_MAX_OVERFLOW + SQL_POOL_SIZE
# connections, and keeps its own chat rate limiter.
set -e

graphsense db migrate

if [ -z "${WEB_CONCURRENCY:-}" ]; then
    cpus=$(nproc 2>/dev/null || echo 1)
    WEB_CONCURRENCY=$(( cpus < 2 ? cpus : 2 ))
fi

exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "$WEB_CONCURRENCY"
