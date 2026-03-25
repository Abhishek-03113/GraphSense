# DodgeAI — Solution v2: Progress, Requirements & Acceptance Criteria

This document provides an updated view of the DodgeAI solution, tracking completed components against the original architectural plan (`docs/solution.md`) and establishing refined functional, non-functional, and acceptance criteria based on the Forward Deployed Engineer task evaluation guidelines.

---

## 1. Completed Components (vs. Initial Solution Plan)

Based on the current architecture and development logs (`CLAUDE.md`), the following goals have been successfully implemented:

### ✅ Phase 0: Project Scaffolding

- **Backend Setup**: FastAPI project initialized with structured layering (`src/api`, `src/db`, `src/domain`, `src/repositories`, `src/ingestion`).
- **Frontend Setup**: React + TypeScript application via Vite.
- **Database & Migrations**: Custom Alembic migration system (`migration_runner.py`) established with strict separation of schema and seed migrations. PostgreSQL connection pooling configured.
- **Parallel Development**: Git worktrees (`backend` and `frontend`) set up for parallel development flows.

### ✅ Phase 1: Data Ingestion & Graph Construction

- **JSONL Ingestion Pipeline**: Robust, idempotent Python script for batch ingestion of 19 SAP O2C JSONL datasets into PostgreSQL.
- **Data Modeling**: Explicit DDL-based table schemas mapped to async SQLAlchemy models (`BillingDocumentHeader`, `SalesOrderHeader`, etc.), with Pydantic for validation.
- **Data Access Layer**: `graph_repository.py` implemented for data traversal, graph entity lookups, and dataset querying.

### ⏳ Phase 2: Graph Visualization UI (In Progress)

- **API Endpoints**: Graph discovery APIs (`GET /api/graph/summary`, `GET /api/graph/subgraph`, `GET /api/graph/entities/{node_type}`) are fully functional.
- **Frontend Foundation**: Zustand and TanStack React Query stores instantiated. API client established.
- **UI Components**: `Dashboard.tsx`, `EntitySelector.tsx`, and Cytoscape-powered `GraphExplorer.tsx` components are structured to support dynamic, data-driven visualization.

---

## 2. Updated Requirements

The following requirements translate the evaluation criteria into strict development guidelines.

### 2.1 Functional Requirements

1. **Graph Construction (Data Foundation)**
  - Ingest the provided SAP O2C JSONL dataset.
  - Construct a graph representation mapping business entities (Nodes) and associations (Edges) such as *Purchase Order → Purchase Order Item* or *Customer → Delivery*.
2. **Graph Visualization**
  - Provide an interactive web interface.
  - Allow users to expand nodes to discover neighbor nodes.
  - Allow users to inspect node metadata via a side panel on selection.
  - Visualize relationships explicitly.
3. **Conversational Query Interface (LLM)**
  - Provide a chat interface accepting Natural Language inputs.
  - Dynamically translate NL queries into structured data operations.
  - Provide data-backed responses that answer analytical or traceability questions (e.g., *Which products have the most billing documents?*, *Trace the flow of billing document X*).
4. **Guardrails (Domain Restriction)**
  - System MUST strictly restrict queries to the dataset and domain.
  - Reject general knowledge questions, creative writing requests, or irrelevant topics.
  - Rejection message should explicitly guide the user: *"This system is designed to answer questions related to the provided dataset only."*

### 2.2 Non-Functional Requirements

1. **Coding Style & Architecture (Strict Adherence to `user_global` rules)**
  - **Immutability**: Never mutate existing objects; return new copies.
  - **File Complexity**: Uphold high cohesion and low coupling. Prefer many small files (200-400 lines typical, 800 max) over a few large files. Organize by feature/domain.
  - **Error Handling & Validation**: Validate all limits at boundaries via Pydantic (backend) and Zod/TypeScript boundaries (frontend). Ensure fail-fast error mapping.
  - **Testing Quality**: Strive for 80%+ test coverage using the TDD approach (Red-Green-Refactor).
2. **Groundedness & Accuracy**
  - Responses must be exclusively derived from the database payloads. No zero-data hallucinations.
3. **Performance & UX (Bonus goals)**
  - Utilize Server-Sent Events (SSE) for real-time streaming of LLM responses.
  - Implement Conversation Memory for reliable follow-up insights.
4. **Deployment & Access**
  - The final product must be deployed on a live link with a public GitHub repo.
  - **No authentication** logic should be implemented.
5. **Cost Allocation**
  - Use free-tier LLM providers (e.g., Google Gemini) exclusively.

---

## 3. Acceptance Criteria (Evaluation-Aligned)

To consider the project ready for grading, the following criteria must be satisfied:

### 🎯 AC-1: Graph Modelling Quality

- Accurately identifies core O2C flows (Order → Delivery → Invoice → Payment) alongside supporting entities (Customer, Product, Address).
- Database schema tradeoffs (relational vs. graph representations) are clearly justified and implemented optimally.

### 🎯 AC-2: Insight Generation (NL to SQL)

- Successfully translates traceability queries into valid operations extending to complete end-to-end flows.
- Determines and executes aggregation / analytic queries (e.g., finding top-performing segments or missing flow sequences).
- Summarizes query outputs logically and clearly in the UI without generating phantom answers.

### 🎯 AC-3: Guardrails & Security

- Off-topic prompts (e.g., *"Write a poem"*) generate immediate scope-denial messages without crashing or exposing prompts.
- Strict isolation against any destructive queries (No DDL or Data manipulation in query endpoints).

### 🎯 AC-4: Usability & Code Delivery

- Graph UI handles zooming, panning, and click-to-expand interactively.
- Fully comprehensive `README.md` detailing architecture, DB choice, LLM prompting strategy, and guardrails implementation.
- Working Demo deployment handles multi-session load cleanly without requiring user sign-in.
- Submission bundle includes Markdown transcripts spanning code iteration cycles (demonstrating proper AI planning and session usage).

