# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DodgeAI is a graph-based data modeling and query system for SAP Order-to-Cash (O2C) data. It features:
- A FastAPI backend that exposes graph traversal and data ingestion APIs
- A React + TypeScript frontend for visualizing entity relationships as an interactive graph
- PostgreSQL database with pgvector extension for storing and querying relational data
- Data ingestion pipeline for loading JSONL-formatted SAP data

## Architecture

### Backend Structure (`/backend`)

The backend follows a layered architecture:

- **`src/api/`** - FastAPI routers and request handling
  - `graph.py` - Endpoints for graph queries (summary, subgraph, entity listing)
  - `ingest.py` - Endpoint to trigger background data ingestion

- **`src/db/`** - Database layer
  - `models.py` - SQLAlchemy ORM models (BillingDocumentHeader, BillingDocumentItem, etc.)
  - `session.py` - Database session and connection management
  - `engine.py` - SQLAlchemy engine configuration
  - `migration_runner.py` - Custom Alembic migration wrapper

- **`src/repositories/`** - Data access layer
  - `graph_repository.py` - Queries for graph traversal and entity lookups

- **`src/domain/`** - Response schemas and domain models
  - `graph_models.py` - Pydantic models for API responses

- **`src/ingestion/`** - Data loading utilities
  - `jsonl_loader.py` - JSONL file parsing and database insertion
  - `schemas.py` - Data schemas for ingestion validation

- **`main.py`** - FastAPI application initialization with CORS and router registration

Database models represent SAP O2C entities (BillingDocumentHeader, BillingDocumentItem, BillingDocumentCancellation, etc.) with relationships tracked via foreign keys.

### Frontend Structure (`/frontend`)

- **`src/App.tsx`** - Main app component managing view states (dashboard → selector → graph)
- **`src/services/api.ts`** - API client for backend communication
- **`src/components/graph/`** - Graph visualization components
  - `GraphExplorer.tsx` - Cytoscape-based interactive graph renderer
  - `InspectorPanel.tsx` - Selected node details panel
- **`src/components/ui/`** - UI components
  - `Dashboard.tsx` - Summary view with entity type cards
  - `EntitySelector.tsx` - Entity listing and selection interface
- **`src/store/`** - Zustand store for client-side state
- **`src/types/`** - TypeScript type definitions

Data flow: Dashboard → EntitySelector → GraphExplorer. State managed by Zustand, async data fetched via TanStack React Query.

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

The frontend connects to the backend at `http://localhost:8000` (configured in `src/services/api.ts`). CORS is enabled for `http://localhost:5173`.

### Testing & Linting

**Backend:**
- pytest configured in `pyproject.toml` with asyncio mode
- Run: `pytest` (from `/backend`)

**Frontend:**
```bash
npm run lint                   # ESLint check
npm run build                  # TypeScript + Vite build
```

## Key Concepts

### Graph API Endpoints

- `GET /api/graph/summary` - Returns node/edge counts by entity type
- `GET /api/graph/subgraph?root_type=SalesOrder&root_id=123&depth=2` - Returns nodes and edges reachable from a root entity
- `GET /api/graph/entities/{node_type}?limit=50` - Returns sample entity IDs of a given type

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
- Graph components use Cytoscape (rendered via `react-cytoscapejs`)
- Modify layout/styling in `GraphExplorer.tsx`
- Node/edge data comes from `GraphSubgraphResponse` from backend

## Important Notes

- Backend uses async SQLAlchemy (`sqlalchemy.ext.asyncio`) — always use `await` with database queries
- Frontend state management: Zustand for client state, React Query for server state
- Environment variables for backend: see `/backend/.env.example`
- Migrations are tracked in `/backend/migrations/` — review migration files before running `apply`
- CORS is restricted to `http://localhost:5173` in dev; update `src/main.py` for production URLs
