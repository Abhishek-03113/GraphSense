# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DodgeAI is a graph-based data modeling and query system for SAP Order-to-Cash (O2C) data. It features:
- A FastAPI backend that exposes graph traversal and data ingestion APIs
- A React + TypeScript frontend for visualizing entity relationships as an interactive graph
- PostgreSQL database with pgvector extension for storing and querying relational data
- Data ingestion pipeline for loading JSONL-formatted SAP data
- **LLM-powered conversational query interface** using Gemini + pgvector RAG for text-to-SQL

## Architecture

### Backend Structure (`/backend`)

The backend follows a layered architecture:

- **`src/api/`** - FastAPI routers and request handling
  - `graph.py` - Endpoints for graph queries (summary, subgraph, flows, trace, full graph, entity listing)
  - `ingest.py` - Endpoint to trigger background data ingestion
  - `chat.py` - Chat endpoint (`POST /api/chat`) and training trigger (`POST /api/chat/train`)

- **`src/db/`** - Database layer
  - `models.py` - SQLAlchemy ORM models (BillingDocumentHeader, BillingDocumentItem, etc.)
  - `session.py` - Database session and connection management
  - `engine.py` - SQLAlchemy engine configuration
  - `migration_runner.py` - Custom Alembic migration wrapper

- **`src/repositories/`** - Data access layer
  - `graph_repository.py` - Queries for graph traversal and entity lookups

- **`src/domain/`** - Response schemas and domain models
  - `graph_models.py` - Pydantic models for API responses (`Node`, `Edge`, `GraphSubgraphResponse`, `FlowDefinition`, `FlowListResponse`, etc.)
  - `flow_definitions.py` - `FLOW_DEFINITIONS` constant: predefined O2C flow metadata (node types, edge types per flow)

- **`src/ai/`** - LLM-powered chat pipeline (text-to-SQL RAG)
  - `config.py` - AI settings (Gemini API key, model, embedding model)
  - `embeddings.py` - pgvector embedding store using Gemini text-embedding-004 (DDL, docs, SQL pairs, data summaries)
  - `training.py` - Training data: 17 DDL schemas, 7 domain docs, 15 SQL question-answer pairs
  - `guardrails.py` - Domain restriction: rejects off-topic queries, SQL injection, prompt injection
  - `chat.py` - Full pipeline: guardrails → RAG retrieval → SQL generation → execution → synthesis

- **`src/ingestion/`** - Data loading utilities
  - `jsonl_loader.py` - JSONL file parsing and database insertion
  - `schemas.py` - Data schemas for ingestion validation

- **`main.py`** - FastAPI application initialization with CORS and router registration

Database models represent SAP O2C entities (BillingDocumentHeader, BillingDocumentItem, BillingDocumentCancellation, etc.) with relationships tracked via foreign keys.

### Frontend Structure (`/frontend`)

React 19 + TypeScript + Vite, React Router for real URLs, TanStack Query for server state, Zustand for client state, Cytoscape for graphs, Zod for response validation. Styling is CSS Modules on top of design tokens (`src/styles/tokens.css`, `--gs-*` custom properties, light and dark). Full docs: `frontend/README.md`.

- **`src/app/`** - `App.tsx` (providers + routes, pages lazy-loaded), `Shell.tsx` (sidebar, page frame, command palette host), `Sidebar.tsx`, `Page.tsx` (header with title, subtitle, actions), `nav.ts`, `useCommandItems.tsx`
- **`src/features/`** - one folder per screen:
  - `overview/` (`/`), `explore/` (`/explore`, graph + filters), `ask/` (`/ask` and the Explore side panel), `flows/` (`/flows`, `/flows/:flowId`), `trace/` (`/trace?type=&id=`), `records/` (`/records/:type?`)
  - `inspector/` - `RecordInspector`, the details panel shared by Explore, Flows, Trace and Records
  - `onboarding/` - first-run "Load data" state (`POST /api/ingest`)
- **`src/components/ui/`** - Button, IconButton, Card, Badge, TypeBadge, Input/Select, SegmentedControl, Checkbox, Slider, Table, Sheet, Tooltip, EmptyState/ErrorState, Skeleton, Kbd, Combobox, Disclosure, CommandPalette
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

**Backend:**
```bash
cd backend
python -m venv .venv          # or use uv to manage deps
source .venv/bin/activate
uv pip install -e .            # Install from pyproject.toml
```

**Frontend:**
```bash
cd frontend
npm install
```

**Database:**
```bash
docker-compose up -d           # Starts PostgreSQL with pgvector
```

### Database Migrations

Backend uses Alembic migrations in `/backend/migrations/versions/`.

```bash
cd backend
python migrate.py status                              # Show pending migrations
python migrate.py apply                               # Apply all pending migrations
python migrate.py create --name <description>         # Create a new migration
python migrate.py baseline --upto <timestamp>         # Mark migrations as applied without executing
```

### Running Services

**Backend (FastAPI server):**
```bash
cd backend
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend (Vite dev server):**
```bash
cd frontend
npm run dev
```

The frontend connects to the backend at `http://localhost:8000/api` (override with `VITE_API_BASE_URL`; see `src/lib/api/client.ts`). CORS is enabled for `http://localhost:5173`.

### Testing & Linting

**Backend:**
- pytest configured in `pyproject.toml` with asyncio mode
- Run: `pytest` (from `/backend`)

**Frontend:**
```bash
npm run lint                   # ESLint check
npm run build                  # TypeScript + Vite build
npm run e2e:screens -- ./e2e/screens   # Playwright screenshots against mocked API routes (see frontend/README.md)
```

## Key Concepts

### Graph API Endpoints

- `GET /api/graph/summary` - Returns node/edge counts by entity type
- `GET /api/graph/subgraph?root_type=SalesOrder&root_id=123&depth=2` - Returns nodes and edges reachable from a root entity (depth 1–5)
- `GET /api/graph/entities/{node_type}?limit=50` - Returns sample entity IDs of a given type
- `GET /api/graph/flows` - Lists all predefined O2C flow definitions (id, label, description, node/edge types)
- `GET /api/graph/flow?flow_id=full_o2c&limit=50` - Returns a sampled subgraph for a named flow (`sales`, `fulfillment`, `billing`, `financial`, `full_o2c`)
- `GET /api/graph/trace?doc_type=Invoice&doc_id=X&depth=4` - Traces the full O2C lifecycle for a document (reuses subgraph traversal at depth 4)
- `GET /api/graph/full?node_limit=20&type_filter=Customer,Invoice` - Returns a sampled knowledge graph (up to `node_limit` entities per type)

### Conversational Query (Chat) API

- `POST /api/chat` - Accepts `{ message }`, returns `{ answer, sql, data, entities, error }`
- `POST /api/chat/train` - Triggers (re-)training of the RAG pipeline

**Pipeline**: Guardrails → pgvector RAG retrieval (DDL + docs + SQL pairs + data summaries) → Gemini SQL generation → PostgreSQL execution → Gemini response synthesis

**Architecture**:
- **pgvector** stores embeddings (Gemini text-embedding-004, 768 dims) for 17 DDL schemas, 7 domain docs, 15 SQL question-answer pairs, and data summaries derived from ingested data
- **Google Gemini** (`gemini-2.0-flash`) generates SQL from RAG context and synthesizes natural language answers
- **Guardrails** reject off-topic queries, SQL injection, and prompt injection attempts
- Entities extracted from query results are highlighted on the graph visualization

### Data Ingestion

- `POST /api/ingest` - Triggers background ingestion from JSONL files in `data/sap-o2c-data/`
- Ingestion runs asynchronously and populates database tables via `ingestion/jsonl_loader.py`

### Database Schema

SAP O2C entities are modeled as database tables with foreign key relationships:
- BillingDocumentHeader/Item/Cancellation
- SalesOrderHeader/Item
- MaterialInfo
- PartyInfo
- And others (see `src/db/models.py`)

The graph API traverses these relationships to build subgraphs for visualization.

## Common Tasks

**Adding a new API endpoint:**
1. Create handler in `src/api/` (or add to existing router file)
2. Add repository method in `src/repositories/graph_repository.py` if querying data
3. Define response schema in `src/domain/graph_models.py`
4. Register router in `src/main.py` if new file

**Adding a new database model:**
1. Define SQLAlchemy class in `src/db/models.py`
2. Create migration: `python migrate.py create --name <desc>`
3. Update migration file in `/backend/migrations/versions/`
4. Run migrations: `python migrate.py apply`

**Updating frontend visualization:**
- Graph rendering lives in `src/components/graph/GraphCanvas.tsx` (Cytoscape, no wrapper library); node/edge styling is in `graphStyle.ts`, layouts in `layouts.ts`
- Colours come from design tokens, resolved at runtime by `useThemeColors.ts` so the canvas follows light/dark
- Node/edge data is a `GraphData` (`lib/api/schemas.ts`); feed it to `GraphCanvas` and the Explore, Flow and Trace screens all work the same way
- Never hard-code a record type name or colour: use `useSchema()` (`colorForType`, `typeLabel`, `edgeLabel`)

**Adding a new O2C flow:**
1. Add an entry to `backend/src/domain/flow_definitions.py` (`FLOW_DEFINITIONS` dict)
2. The `/api/graph/flows` endpoint and the Flows page (`src/features/flows/`) pick it up automatically. List `node_types` in process order: the UI uses that order for steps and layout

## Important Notes

- Backend uses async SQLAlchemy (`sqlalchemy.ext.asyncio`) — always use `await` with database queries
- Frontend state management: Zustand for client state, React Query for server state
- Environment variables for backend: see `/backend/.env.example`
- Migrations are tracked in `/backend/migrations/` — review migration files before running `apply`
- CORS is restricted to `http://localhost:5173` in dev; update `src/main.py` for production URLs
