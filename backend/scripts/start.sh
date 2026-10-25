#!/bin/sh
# Container entry point: bring the database schema up to date, then serve.
#
#   graphsense db migrate        applies pending migrations (as the owner role)
#
# Loading data is a separate operator step: `graphsense ingest <dataset>`.
set -e

graphsense db migrate

exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
