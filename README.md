# DodgeAI

A graph-based data modeling and query system for SAP Order-to-Cash (O2C) data. Users explore interconnected business entities through an interactive graph visualization and query the dataset using natural language, powered by an LLM-backed text-to-SQL pipeline.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Graph Modeling](#graph-modeling)
- [Database Choice](#database-choice)
- [LLM Prompting Strategy](#llm-prompting-strategy)
- [Guardrails](#guardrails)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Example Queries](#example-queries)
- [Project Structure](#project-structure)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Knowledge Graph  │  │  Chat Panel      │  │  Inspector   │  │
│  │  (Cytoscape.js)   │  │  (NL queries)    │  │  (metadata)  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────────┘  │
└───────────┼─────────────────────┼──────────────────────────────┘
            │ REST                │ REST
┌───────────┼─────────────────────┼──────────────────────────────┐
│           ▼                     ▼          FastAPI Backend      │
│  ┌──────────────────┐  ┌──────────────────────────────────┐    │
│  │  Graph API        │  │  Chat Pipeline                   │    │
│  │  /api/graph/*     │  │  Guardrails → RAG → SQL → Answer │    │
│  └────────┬─────────┘  └──┬────────────┬────────────┬─────┘    │
│           │               │            │            │           │
│           ▼               ▼            ▼            ▼           │
│  ┌──────────────┐  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Graph Repo   │  │ pgvector │ │  Gemini  │ │  PostgreSQL  │  │
│  │  (traversal)  │  │ (vectors)│ │  (LLM)   │ │  (read-only) │  │
│  └──────┬───────┘  └──────────┘ └──────────┘ └──────────────┘  │
│         ▼                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │             PostgreSQL 16 + pgvector                      │   │
│  │   17 tables · SAP O2C entities · FK-based relationships   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

The system is split into three layers:

1. **Data Layer** — PostgreSQL stores normalized SAP O2C entities. The graph repository derives nodes and edges from foreign-key relationships at query time using SQL `UNION ALL` queries — no separate graph database is needed.

2. **AI Layer** — A five-stage text-to-SQL pipeline converts natural language questions into SQL, executes them against the database, and synthesizes answers using Google Gemini. pgvector provides RAG context (DDL schemas, domain docs, SQL examples) stored directly in PostgreSQL.

3. **Presentation Layer** — React frontend renders an interactive Cytoscape.js knowledge graph alongside a chat panel. Entities mentioned in query results are highlighted on the graph in real time.

---

## Graph Modeling

### Why derive a graph from a relational database?

SAP O2C data is inherently relational — orders reference customers, deliveries reference order items, invoices reference deliveries. Rather than duplicating this data into a dedicated graph database (Neo4j, etc.), we derive the graph representation at query time directly from PostgreSQL foreign keys. This approach:

- **Eliminates sync issues** — the graph always reflects the current database state
- **Reduces operational complexity** — one database to manage, not two
- **Leverages PostgreSQL's mature query optimizer** for traversals via CTEs

### Node types (11)

| Category | Types |
|----------|-------|
| Core flow | `Customer`, `SalesOrder`, `SalesOrderItem`, `Delivery`, `DeliveryItem`, `Invoice`, `InvoiceItem`, `JournalEntry`, `Payment` |
| Supporting | `Product`, `Address` |

### Edge types (11)

```
Customer       ──[PLACED]──────▶ SalesOrder
SalesOrder     ──[HAS_ITEM]────▶ SalesOrderItem
SalesOrderItem ──[INCLUDES]────▶ Product

Delivery       ──[HAS_ITEM]────▶ DeliveryItem
DeliveryItem   ──[FULFILLS]────▶ SalesOrderItem     (cross-document)

Invoice        ──[HAS_ITEM]────▶ InvoiceItem
InvoiceItem    ──[BILLS_FOR]───▶ DeliveryItem        (cross-document)
Invoice        ──[BILLED_TO]──▶ Customer

Invoice        ──[GENERATES]──▶ JournalEntry
Payment        ──[CLEARS]─────▶ JournalEntry

Customer       ──[HAS_ADDRESS]▶ Address
```

Edge direction follows **business causality** — a customer *places* an order, a delivery *fulfills* an order item, a payment *clears* a journal entry.

### Cross-document normalization

SAP uses different item number formats across documents:
- Source tables: zero-padded (`000010`, `000020`)
- Reference fields: short form (`10`, `20`)

We normalize with `REGEXP_REPLACE(column, '^0+', '')` and use composite IDs (`doc-item`) to match across documents reliably.

### Bidirectional traversal

The graph repository wraps all edges in a CTE that produces both forward and reverse directions, enabling depth-first traversal from any starting node — you can trace forwards from a sales order to payments, or backwards from a payment to the originating customer.

### Predefined O2C flows

Six predefined flows are available for focused exploration:

| Flow | Path | Purpose |
|------|------|---------|
| Sales | Customer → SalesOrder → Items → Product | Order creation |
| Fulfillment | SalesOrder → Items → DeliveryItem → Delivery | Shipment |
| Billing | Delivery → Items → InvoiceItem → Invoice → Customer | Invoicing |
| Financial | Invoice → JournalEntry → Payment | Accounting |
| Customer Master | Customer → Address | Profile |
| Full O2C | All 11 node types, all 11 edge types | End-to-end |

---

## Database Choice

### PostgreSQL 16 with pgvector

**Why PostgreSQL over a graph database (Neo4j, ArangoDB)?**

1. **The data is naturally tabular.** SAP exports are flat records with foreign keys. Loading them into PostgreSQL is zero-transformation — the tables map 1:1 to the source JSONL files.

2. **Graph traversal via CTEs performs well at this scale.** The dataset has thousands (not millions) of documents. Recursive CTEs with depth limits handle subgraph extraction in milliseconds — a dedicated graph engine would add operational cost without meaningful performance gain.

3. **The LLM generates SQL, not Cypher.** Text-to-SQL is a well-studied problem with abundant training data. LLMs produce more reliable SQL than Cypher or SPARQL, reducing hallucinated queries.

4. **One database simplifies deployment.** A single PostgreSQL instance serves both the graph API (relational traversal) and the chat pipeline (direct SQL execution). No graph-to-relational sync layer needed.

5. **pgvector extension** is used for all vector storage — embeddings for RAG context (DDL schemas, domain docs, SQL examples) live in the `rag_embeddings` table alongside relational data in the same PostgreSQL instance.

### pgvector for RAG vectors

All embeddings are stored in the `rag_embeddings` table using the pgvector extension. This was chosen over ChromaDB because:

- **Single database** — no separate vector store service to run or back up
- **Full ACID compliance** — embeddings are transactional alongside relational data
- **Joins with relational data** — similarity search can be combined with SQL filters
- **Single backup** — one `pg_dump` covers all data

Four embedding categories are stored:

| Category | Count | Content |
|----------|-------|---------|
| `schema` | 17 | Table `CREATE` statements (DDL) |
| `documentation` | 7 | Domain context docs (FK maps, status codes) |
| `sql_pair` | 15 | Question-SQL few-shot examples |
| `data_profile` | per-table | Statistical summaries of ingested data |

Similarity search uses cosine distance via the `<=>` operator:

```sql
SELECT content, 1 - (embedding <=> :query_vector::vector) AS similarity
FROM rag_embeddings
WHERE category = :category
ORDER BY embedding <=> :query_vector::vector
LIMIT :n;
```

---

## LLM Prompting Strategy

### Design: custom-built five-stage pipeline

The pipeline is hand-rolled rather than using a framework like Vanna.ai, for four reasons:

1. **Structured output control** — We need a strict JSON payload (`{answer, sql, data, entities}`) with entity extraction for graph highlighting.
2. **Pre-LLM guardrails** — `guardrails.py` rejects off-topic, injection, and mutation attempts before any LLM call, keeping latency near zero for rejected queries.
3. **Entity extraction for graph integration** — After SQL execution, result columns are mapped to graph node types (`sales_order` → `SalesOrder`, etc.) and returned as highlightable entities.
4. **Minimal dependencies** — Only `google-genai` + `psycopg2` + `pgvector` — no heavyweight framework transitive dependencies.

The three-source RAG design (DDL + docs + SQL pairs) ensures the LLM receives structural, semantic, and tactical context for every query.

### Model: Google Gemini 2.0 Flash

Selected for its free-tier availability, fast inference speed, and strong SQL generation capabilities. The pipeline makes two LLM calls per user question:

### Pipeline stages

```
User question
     │
     ▼
┌─────────────┐   reject   ┌──────────────────┐
│ 1. Guardrails├───────────▶│ Rejection message │
└──────┬──────┘            └──────────────────┘
       │ pass
       ▼
┌─────────────┐
│ 2. RAG       │  Query pgvector for relevant DDL, docs, SQL examples
│   Retrieval  │  (cosine similarity on rag_embeddings table)
└──────┬──────┘
       │ context
       ▼
┌─────────────┐            ┌──────────────────┐
│ 3. SQL       │ CANNOT    │ "Rephrase your   │
│   Generation ├───────────▶│  question..."    │
│   (Gemini)   │ GENERATE  └──────────────────┘
└──────┬──────┘
       │ SQL
       ▼
┌─────────────┐            ┌──────────────────┐
│ 4. SQL       │ error     │ "Query error,    │
│   Execution  ├───────────▶│  try rephrasing" │
│ (PostgreSQL) │           └──────────────────┘
└──────┬──────┘
       │ rows + columns
       ▼
┌─────────────┐
│ 5. Response  │  Gemini synthesizes natural language answer
│   Synthesis  │  from question + SQL + results
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 6. Entity    │  Map column names to graph node types
│   Extraction │  for frontend highlighting
└─────────────┘
```

### SQL generation prompt

The SQL generation prompt encodes 10 rules that constrain the LLM output:

```
You are an expert PostgreSQL SQL query generator for an SAP Order-to-Cash dataset.

RULES:
1. Generate ONLY valid PostgreSQL SELECT queries. Never INSERT/UPDATE/DELETE/DROP.
2. Use only tables and columns from the provided context.
3. Use REGEXP_REPLACE(column, '^0+', '') for cross-document item number joins.
4. Always use table aliases.
5. Default LIMIT 25 unless user asks for more.
6. sold_to_party = business_partners.customer (NOT business_partner).
7. Return ONLY the SQL query — no explanation, no markdown fences.
8. Return CANNOT_GENERATE if unable to produce valid SQL.
9. Include GROUP BY for aggregations.
10. Use LEFT JOIN when relationships might not exist.
```

Key design decisions in the prompt:

- **Rule 3** addresses the zero-padding normalization problem directly in the prompt, since this is the most common source of broken joins in SAP data.
- **Rule 6** prevents the most frequent FK confusion in the schema (business_partner vs customer column).
- **Rule 8** provides a clean escape hatch — `CANNOT_GENERATE` — rather than hallucinating invalid SQL.
- **Rule 10** prevents empty result sets when optional relationships (e.g., not all orders have deliveries) would cause INNER JOINs to drop rows.

### RAG context assembly

For each user question, the system retrieves from the `rag_embeddings` pgvector table:

1. **DDL schemas** (up to 5) — the most relevant table definitions, so the LLM knows exact column names and types
2. **Domain docs** (up to 5) — business context like "delivery status 'C' = completed" and FK relationship mappings
3. **SQL examples** (up to 5) — few-shot examples of similar questions with verified SQL answers
4. **Data profiles** (up to 3) — per-table statistical summaries derived from ingested data

This three-source RAG approach ensures the LLM has:
- **Structural knowledge** (DDL) — what tables/columns exist
- **Semantic knowledge** (docs) — what the data means in business terms
- **Tactical knowledge** (SQL pairs) — proven query patterns for common question types

### Response synthesis prompt

A second Gemini call converts raw query results into a natural language answer:

```
Rules:
1. Answer based ONLY on the data provided. Do not make up information.
2. If results are empty, say so clearly.
3. Include specific numbers, names, and values from results.
4. Keep the answer conversational but factual.
5. Include currency for amounts.
6. Format large numbers with commas.
7. Do not include the SQL query in response.
8. Highlight key findings or patterns.
```

Results are truncated to 50 rows before passing to the LLM to stay within token limits.

### Entity extraction

After query execution, the system scans result column names against a mapping table:

```python
"sales_order"        → SalesOrder
"delivery_document"  → Delivery
"billing_document"   → Invoice
"accounting_document"→ JournalEntry
"payment_document"   → Payment
"customer"           → Customer
"product"            → Product
```

Extracted entities are returned to the frontend as `{id, type, value}` objects. The graph visualization highlights matching nodes, visually connecting the chat answer to the knowledge graph.

---

## Guardrails

The guardrail system is a multi-layer filter that runs before any LLM call, keeping latency near zero for rejected queries.

### Layer 1: Input validation

Reject messages shorter than 3 characters.

### Layer 2: SQL injection detection

Pattern-matched rejection of data-modification keywords:

```
DROP TABLE, DELETE FROM, TRUNCATE, ALTER TABLE,
INSERT INTO, UPDATE ... SET, CREATE TABLE
```

This runs both in the guardrails (before the LLM) and as a post-generation safety check on the LLM's SQL output.

### Layer 3: Prompt injection detection

Rejects attempts to override system instructions:

```
"ignore previous instructions"
"forget all instructions"
"pretend you are"
"you are now"
"act as"
```

### Layer 4: Off-topic pattern matching

Regex-based detection of clearly non-domain queries:

```
Creative writing: "write a poem/story/essay"
General knowledge: "who is the president", "what is the capital"
Casual: "weather", "recipe", "joke", "news"
Games: "play chess", "tic tac toe"
```

### Layer 5: Domain relevance check

If no off-topic pattern matches, the system checks for at least one domain keyword (order, customer, delivery, invoice, payment, product, etc.) or analytical intent (`how many`, `show`, `list`, `top N`). Queries that match neither are rejected with:

> "This system is designed to answer questions related to the SAP Order-to-Cash dataset only."

### Post-generation SQL validation

Even after the LLM generates SQL, a regex check rejects any mutation statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`) as a defense-in-depth measure. The SQL is executed read-only against PostgreSQL.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | React 19, TypeScript | UI framework |
| Graph rendering | Cytoscape.js + cose-bilkent | Force-directed graph layout |
| State management | Zustand + TanStack React Query | Client + server state |
| Backend | FastAPI (Python 3.12) | REST API server |
| Database | PostgreSQL 16 + pgvector | Relational data + graph traversal |
| Migrations | Alembic | Schema versioning |
| LLM | Google Gemini 2.0 Flash | SQL generation + response synthesis |
| Vector store | pgvector (PostgreSQL extension) | RAG embeddings for DDL, docs, SQL pairs, data profiles |
| Logging | structlog | Structured backend logging |
| Validation | Pydantic (backend), Zod (frontend) | Request/response schemas |

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose
- Google Gemini API key ([free tier](https://ai.google.dev))

---

### Step 1: Clone the Repository

```bash
git clone https://github.com/Abhishek-03113/DodgeAI.git
cd DodgeAI
```

---

### Step 2: Start the Database (Docker)

Start PostgreSQL with pgvector extension:

```bash
docker-compose up -d
```

Verify the database is running:

```bash
docker-compose ps
```

---

### Step 3: Backend Setup

**3.1 Create and activate virtual environment:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

**3.2 Install dependencies:**

```bash
pip install -e .
```

**3.3 Configure environment variables:**

```bash
cp .env.example .env
```

Edit `.env` and add your Google Gemini API key:

```env
GEMINI_API_KEY=your_actual_api_key_here
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dodgeai
```

> **Get your API key:** Visit [Google AI Studio](https://ai.google.dev) to create a free API key.

**3.4 Run database migrations:**

Migrations create all 17 SAP O2C tables plus the `rag_embeddings` pgvector table:

```bash
python migrate.py apply
```

To check which migrations have been applied:

```bash
python migrate.py status
```

> **Note:** Migrations must be applied before starting the server or ingesting data. If you re-create the database container, run `migrate.py apply` again.

**3.5 Start the backend server:**

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

> **Keep this terminal open** — the backend server needs to stay running.

---

### Step 4: Frontend Setup

**Open a new terminal** and navigate to the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:5173`.

---

### Step 5: Ingest Data

**5.1 Place your data files:**

Put your JSONL data files in the `data/sap-o2c-data/` directory (at the project root, mounted into the backend).

Expected files match the 17 SAP O2C entity types (e.g. `sales_order_headers.jsonl`, `billing_document_items.jsonl`, etc.).

**5.2 Trigger data ingestion:**

```bash
curl -X POST http://localhost:8000/api/ingest
```

Ingestion runs as a background task. It parses JSONL files and populates all 17 tables. Check the backend logs to confirm completion.

> **Note:** Run ingestion before training the RAG pipeline — data profiles (statistical summaries per table) are generated from the ingested rows and embedded into pgvector during training.

---

### Step 6: Train the RAG Pipeline

Training embeds DDL schemas, domain docs, SQL question-answer pairs, and data profiles into the `rag_embeddings` pgvector table using Gemini `text-embedding-004`.

```bash
curl -X POST http://localhost:8000/api/chat/train
```

> **Run this once after ingestion.** The pipeline will not auto-train — the `rag_embeddings` table must be populated before the chat endpoint can generate accurate SQL.

To re-train after schema or data changes, call the same endpoint again. Existing embeddings are replaced.

---

### Step 7: Access the Application

Open your browser and navigate to:

**http://localhost:5173**

You should see:
- **Knowledge Graph** — Interactive Cytoscape.js visualization of SAP O2C entities
- **Chat Panel** — Natural language query interface for asking questions about your data
- **Inspector Panel** — Metadata and entity details

---

### Quick Start Script

For a faster setup, run all steps in sequence:

```bash
# From project root
docker-compose up -d

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env with your GEMINI_API_KEY
python migrate.py apply          # Create all 17 tables + rag_embeddings
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 &

# Ingest data, then train the RAG pipeline (requires server running)
curl -X POST http://localhost:8000/api/ingest   # Load JSONL data into tables
curl -X POST http://localhost:8000/api/chat/train  # Embed DDL, docs, SQL pairs into pgvector

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

---

### Troubleshooting

**Database connection issues:**

```bash
# Check if PostgreSQL is running
docker-compose ps

# View database logs
docker-compose logs postgres
```

**Backend errors:**

```bash
# Verify virtual environment is active
which python  # Should point to backend/.venv/bin/python

# Check if dependencies are installed
pip list | grep -E "(fastapi|psycopg2|google-genai)"
```

**Frontend build issues:**

```bash
# Clear cache and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

**API not responding:**

```bash
# Test health endpoint
curl http://localhost:8000/health
```

---

## API Reference

### Graph endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/graph/summary` | Node/edge counts by type |
| `GET` | `/api/graph/subgraph?root_type=X&root_id=Y&depth=2` | Subgraph from a root entity |
| `GET` | `/api/graph/entities/{node_type}?limit=50` | List entity IDs of a type |
| `GET` | `/api/graph/flows` | List predefined O2C flow definitions |
| `GET` | `/api/graph/flow?flow_id=full_o2c&limit=50` | Sampled subgraph for a flow |
| `GET` | `/api/graph/trace?doc_type=Invoice&doc_id=X&depth=4` | Document lifecycle trace |
| `GET` | `/api/graph/full?node_limit=20&type_filter=Customer,Invoice` | Sampled knowledge graph |

### Chat endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Natural language query → `{answer, sql, data, entities}` |
| `POST` | `/api/chat/train` | Reload RAG training data |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ingest` | Trigger JSONL data ingestion |
| `GET` | `/health` | Health check |

---

## Example Queries

The chat interface handles queries like:

- "Which products are associated with the highest number of billing documents?"
- "Trace the full flow of a billing document from sales order to payment"
- "Find sales orders that have been delivered but not billed"
- "What is the total revenue by customer?"
- "Show invoices that have not been paid yet"
- "Which customers have the most sales orders?"
- "What is the average order value?"
- "Show the monthly sales trend"
- "Find incomplete O2C flows where delivery exists but no invoice"

Off-topic queries like "write me a poem" or "who is the president" are rejected by the guardrail system.

---

## Project Structure

```
DodgeAI/
├── backend/
│   ├── src/
│   │   ├── ai/                    # LLM chat pipeline
│   │   │   ├── chat.py            # 5-stage text-to-SQL pipeline
│   │   │   ├── guardrails.py      # Multi-layer query validation
│   │   │   ├── training.py        # RAG training data (DDL, docs, SQL pairs, data profiles)
│   │   │   ├── embeddings.py      # pgvector embedding store (rag_embeddings table)
│   │   │   └── config.py          # AI settings (Gemini key, model, embedding dimensions)
│   │   ├── api/                   # FastAPI routers
│   │   │   ├── graph.py           # Graph traversal endpoints
│   │   │   ├── chat.py            # Chat endpoint
│   │   │   └── ingest.py          # Data ingestion trigger
│   │   ├── db/                    # Database layer
│   │   │   ├── models.py          # SQLAlchemy ORM models (17 tables)
│   │   │   ├── session.py         # Async session management
│   │   │   └── engine.py          # Engine configuration
│   │   ├── domain/                # Response schemas
│   │   │   ├── graph_models.py    # Pydantic models
│   │   │   └── flow_definitions.py # Predefined O2C flows
│   │   ├── repositories/          # Data access
│   │   │   └── graph_repository.py # Graph traversal queries
│   │   ├── ingestion/             # Data loading
│   │   │   └── jsonl_loader.py    # JSONL parser
│   │   └── main.py               # FastAPI app initialization
│   ├── migrations/                # Alembic migrations
│   ├── data/                      # JSONL data files
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── graph/             # GraphExplorer, InspectorPanel
│   │   │   ├── knowledge/         # KnowledgeGraph (main unified view)
│   │   │   ├── chat/              # ChatPanel (slide-out NL query interface)
│   │   │   ├── flows/             # FlowSelector, FlowExplorer
│   │   │   ├── trace/             # DocumentTracer
│   │   │   └── ui/                # Dashboard, EntitySelector
│   │   ├── store/                 # Zustand state (graph selection, chat, highlights)
│   │   ├── services/              # API client
│   │   ├── types/                 # TypeScript + Zod schemas
│   │   ├── constants/             # Node type colors, defaults
│   │   └── App.tsx                # Root component
│   └── package.json
├── docker-compose.yml             # PostgreSQL 16 + pgvector
└── README.md
```
