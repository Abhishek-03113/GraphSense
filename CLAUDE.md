# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GraphSense (DodgeAI) turns a relational dataset into an explorable graph and a conversational query interface. The engine is dataset-agnostic: everything specific to a dataset lives in a **dataset package** (YAML under `backend/dataset_packages/<id>/`). The shipped package is `o2c` (SAP Order-to-Cash); `backend/tests/fixtures/packages/toy_library` is a second, unrelated package the tests use to prove the engine names no dataset.

- FastAPI backend: graph traversal, dataset status, Ask (text-to-SQL), operator API
- React + TypeScript frontend that renders whatever the schema endpoint describes
- PostgreSQL with pgvector: each dataset in its own schema `ds_<id>`, application tables in `app`
- `graphsense` CLI for operators: migrations, ingestion, catalog, knowledge, evaluation

## Architecture

### Backend Structure (`/backend`)

- **`dataset_packages/<id>/`** - one package per dataset: `package.yaml`, `tables/*.yaml` (columns, types, roles, `normalize` steps), `graph.yaml` (node types, edge types, flows), `semantics/` (glossary, value sets, vocabulary, examples, suggested questions)
- **`src/datasets/`** - the package engine (no database needed): loading and validation (`loader.py`, `models.py`, `validate.py`), the registry (`registry.py`: `get_package()`, `PACKAGES_DIR` then the shipped packages), generated DDL (`ddl.py`), value coercion and normalisers (`coerce.py`, `normalizers.py`), `DatasetContext`
- **`src/domain/`** - `graph_schema.py` (`NodeTypeDef`, `EdgeTypeDef`, `GraphDataset`, validated on construction), `graph_models.py` (API response models), `graph_registry.py` (`get_dataset()`; default from `DEFAULT_DATASET`)
- **`src/repositories/`** - `graph_sql.py` (`GraphSqlBuilder`: every node/edge SQL statement, generated from the dataset; `composite()` builds multi-column ids) and `graph_repository.py` (runs them and shapes results)
- **`src/storage/`** - dataset schemas and generations (`schema_manager.py`: staging, atomic swap, rollback, drop), `search_path` scoping (`session.py`, `schema_names.py`), database roles (`roles.py`), run records (`runs.py`)
- **`src/ingestion/`** - `graphsense ingest`: reads a package's JSONL sources, coerces and normalises rows, loads a staging generation, validates, runs hooks, swaps it live
- **`src/catalog/`** - the semantic catalog: introspection, drift detection, profiling, stored builds (`app.catalog_*`)
- **`src/intelligence/`** - the Ask pipeline: scope guardrails and injection checks, hybrid retrieval over `app.knowledge_items`, prompt rendering (`prompts/*.j2`), `sql/guard.py` (sqlglot allowlists, tables limited to the dataset catalog), `sql/executor.py` (read-only role, timeouts, row cap), entity extraction, the evaluation harness (`eval/`)
- **`src/api/`** - routers: `graph.py`, `chat.py`, `datasets.py`, `catalog.py`, `admin.py` (mounted only with `ADMIN_TOKEN`); `deps.py` resolves the dataset of a request
- **`src/cli/`** - the `graphsense` command
- **`migrations/schema/`** - SQL migrations for the `app` schema only. Dataset tables are never created by migrations: ingestion generates them from the package

### Frontend Structure (`/frontend`)

React 19 + TypeScript + Vite, React Router for real URLs, TanStack Query for server state, Zustand for client state, Cytoscape for graphs, Zod for response validation. Styling is CSS Modules on top of design tokens (`src/styles/tokens.css`, `--gs-*` custom properties, light and dark). Full docs: `frontend/README.md`.

- **`src/app/`** - `App.tsx` (providers + routes, pages lazy-loaded), `Shell.tsx` (sidebar, page frame, command palette host), `Sidebar.tsx`, `Page.tsx` (header with title, subtitle, actions), `nav.ts`, `useCommandItems.tsx`
- **`src/features/`** - one folder per screen:
  - `overview/` (`/`), `explore/` (`/explore`, graph + filters), `ask/` (`/ask` and the Explore side panel), `flows/` (`/flows`, `/flows/:flowId`), `trace/` (`/trace?type=&id=`), `records/` (`/records/:type?`)
  - `inspector/` - `RecordInspector`, the details panel shared by Explore, Flows, Trace and Records
  - `onboarding/` - first-run "Load data" state (`POST /api/ingest`)
- **`src/components/ui/`** - Button, IconButton, Card, Badge, TypeBadge, Input/Select, Checkbox, Slider, Table, Sheet, Tooltip, EmptyState/ErrorState, Skeleton, Kbd, Combobox, Disclosure, CommandPalette
- **`src/components/graph/`** - `GraphCanvas` (the only Cytoscape wrapper; used by Explore, Flows and Trace), `CanvasToolbar`, `Legend`, `layouts.ts`, `graphStyle.ts`, `useThemeColors.ts`
- **`src/lib/api/`** - `client.ts` (fetch + `VITE_API_BASE_URL`), `schemas.ts` (Zod), `queries.ts` (TanStack Query hooks)
- **`src/lib/schema/`** - `useSchema()` and helpers (`getTypeMeta`, `colorForType`, `typeLabel`, `edgeLabel`); built from `GET /api/graph/schema`, with a fallback derived from `/summary` and `/flows`
- **`src/lib/format/`** - `humanize`, value/number/date formatting, CSV
- **`src/store/`** - `workspace.ts` (sidebar, palette, highlighted records), `ask.ts` (conversation state)
- **`e2e/`** - mocked-API fixtures and the Playwright screenshot script (not bundled)

The UI contains no dataset-specific type names. Record type labels, colours, primary types, display properties, relationship labels and flows all come from the schema endpoint. When adding UI, read these from `useSchema()` rather than naming a type.

Data flow: `SchemaProvider` loads schema + summary once; pages fetch their own data through the hooks in `lib/api/queries.ts`; `GraphCanvas` renders any `{nodes, edges}` payload; `RecordInspector` fetches a record's neighbourhood via `/graph/subgraph`.

## Development

### Environment Setup

```bash
cd backend && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
cd frontend && npm install
docker-compose up -d           # local PostgreSQL with pgvector (or point DATABASE_DSN at any Postgres)
```

Copy `backend/.env.example` to `backend/.env`. Only `DATABASE_DSN` is required; a plain `postgresql://` URL is accepted.

### Database and data

```bash
cd backend
graphsense db migrate                         # create/upgrade the app schema
graphsense db status                          # migration status
graphsense ingest o2c --data-root <dir>       # load a dataset into ds_o2c (DATA_ROOT may be set instead)
graphsense dataset list | status | rollback | drop
graphsense package lint <id-or-dir>           # validate a package
```

Migrations are plain SQL files `V<timestamp>__<name>.sql`; statements are split on semicolons, so comments must not contain any.

### Running Services

```bash
cd backend && uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

The frontend connects to `http://localhost:8000/api` (override with `VITE_API_BASE_URL`).

### Testing & Linting

**Backend** (from `/backend`):
- `pytest`: unit tests need no database; PostgreSQL tests run when `TEST_DATABASE_DSN` is set (a server where the test user can create databases)
- `ruff check src tests scripts`
- `tests/test_graph_sql_equivalence.py` compares generated graph SQL to `tests/fixtures/graph_sql_baseline.json`; regenerate only for an intentional change: `python -m tests.sql_snapshot tests/fixtures/graph_sql_baseline.json` (toy: add `tests/fixtures/packages/toy_library` and write `graph_sql_baseline_toy_library.json`)
- `tests/test_toy_package.py` fails if engine code mentions dataset names or business vocabulary

**Frontend:**
```bash
npm run lint
npm run build
npm run e2e:screens -- ./e2e/screens   # Playwright screenshots against mocked API routes
```

## Key Concepts

### Datasets and requests

- A request names its dataset with the `X-GraphSense-Dataset` header or `?dataset=`; otherwise `DEFAULT_DATASET` is used. Unknown ids answer 404
- A request's transaction runs with `search_path = ds_<id>` and nothing else, so graph SQL uses plain table names and a dataset that is not loaded answers `409 dataset_not_ready`, never another schema's rows
- Ingestion builds a complete new generation in `ds_<id>__r<run>` and swaps it in atomically; the previous one is kept as `ds_<id>__prev` for rollback
- Dataset status (`GET /api/datasets/{id}/status`): `empty`, `loading`, `ready`, `failed`

### Graph model rules

- `id_columns`: one column, or several for a composite id rendered as the values joined with `-`, exactly as stored. Values are never rewritten at query time: canonical forms (e.g. item numbers without leading zeros) come from the column's `normalize` steps at ingestion
- An edge endpoint has one column per id column of the node type it points at, in the same order, normalised the same way (`GraphDataset` and `graphsense package lint` enforce both)
- `terminal: true` marks shared reference records (parties, catalogue items, addresses): traversal reaches them but does not expand through them unless one is the root
- `category` is a free-form label for clients; it has no effect on queries

### Graph API Endpoints

- `GET /api/graph/schema` - describes the dataset (no DB access): `domain`, `node_types` (key, label, plural, description, category, accent, icon, is_primary, display_properties, value_labels), `edge_types`, `flows`. Join with `/summary` for counts
- `GET /api/graph/summary` - node/edge counts by type
- `GET /api/graph/subgraph?root_type=&root_id=&depth=` - records reachable from a root (depth 1-5). Every graph endpoint fills `Node.properties` and, where the type declares a natural name, `Node.label`; details are fetched with one batched query per node type
- `GET /api/graph/entities/{node_type}?limit=` - sample records: `{id, label}` plus the type's `display_properties`
- `GET /api/graph/flows`, `GET /api/graph/flow?flow_id=&limit=` - the package's flows and a sampled subgraph for one
- `GET /api/graph/trace?doc_type=&doc_id=&depth=` - subgraph traversal from a record (default depth 4)
- `GET /api/graph/full?node_limit=&type_filter=` - sampled graph, up to `node_limit` records per type

### Ask (`POST /api/chat`)

Accepts `{ message }`, returns `{ answer, sql, data, entities, graph_nodes, error, row_count, summary }`. Pipeline: scope and injection guardrails, retrieval over the dataset's knowledge items, SQL generation, the SQL guard, execution on the read-only role, synthesis. `error` is `null` or a stable code (`guardrail`, `sql_generation_failed`, `sql_rejected`, `sql_execution_error: <category>`, `not_configured`, `dataset_not_ready`, `rate_limited`, `provider_unavailable`, `internal_error`). Knowledge is refreshed after each load by the post-ingest hooks or with `graphsense knowledge refresh <id>`; `POST /api/chat/train` and `POST /api/ingest` answer 410.

## Common Tasks

**Adding a new dataset:**
1. Create `backend/dataset_packages/<id>/` (or a directory under `PACKAGES_DIR`) with `package.yaml`, one `tables/<table>.yaml` per table, `graph.yaml` and `semantics/`
2. Declare per column its type, `role` and any `normalize` steps (e.g. `strip_leading_zeros` for item numbers that some sources pad)
3. Run `graphsense package lint <id>` until it has no errors, then `graphsense ingest <id> --data-root <dir>`
4. No engine code changes: graph SQL, catalog, prompts, guardrail vocabulary and evaluations all derive from the package

**Adding a node type, edge type or flow:** edit the package's `graph.yaml`. Edge order is the order of the UNION ALL blocks; node order is the order of keys in `/api/graph/summary`; list a flow's `node_types` in process order (the UI uses it for steps and layout). Validation fails on unregistered types, unknown columns, endpoint/id column-count mismatches and normalisation mismatches.

**Adding an API endpoint:** handler in `src/api/`, repository method in `graph_repository.py` (SQL from `GraphSqlBuilder`, never hand-written per type), response model in `graph_models.py`, router registered in `src/main.py`. Take the dataset from `get_dataset_context` / `get_dataset_db`.

**Changing the app schema:** add a new `migrations/schema/V<timestamp>__<name>.sql` (later timestamp than the existing ones) and update `src/storage/app_tables.py` to match.

**Updating frontend visualization:**
- Graph rendering lives in `src/components/graph/GraphCanvas.tsx` (Cytoscape, no wrapper library); node/edge styling is in `graphStyle.ts`, layouts in `layouts.ts`
- Colours come from design tokens, resolved at runtime by `useThemeColors.ts` so the canvas follows light/dark
- Node/edge data is a `GraphData` (`lib/api/schemas.ts`); feed it to `GraphCanvas` and the Explore, Flow and Trace screens all work the same way
- Never hard-code a record type name or colour: use `useSchema()` (`colorForType`, `typeLabel`, `edgeLabel`)

## Important Notes

- Backend uses async SQLAlchemy - always `await` database calls
- Environment variables: see `backend/.env.example`
- In production (`GRAPHSENSE_ENV=production`) `READONLY_DATABASE_DSN` is required and a CORS wildcard is ignored; `graphsense db provision-roles` creates the roles
- The frontend currently never sends `X-GraphSense-Dataset`, so it shows the server's default dataset
