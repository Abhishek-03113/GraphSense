#!/bin/sh
# Container entry point: bring the database schema up to date, adopt a stage-1
# database if there is one, then serve.
#
#   graphsense db migrate        applies pending migrations (as the owner role)
#   dataset adopt-legacy         moves stage-1 dataset tables into ds_<id> (no-op otherwise)
#
# Loading data is a separate operator step: `graphsense ingest <dataset>`.
set -e

graphsense db migrate
graphsense dataset adopt-legacy "${DEFAULT_DATASET:-${GRAPH_DATASET:-o2c}}" --if-needed

exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
