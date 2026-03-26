# DodgeAI Architecture Documentation

This document provides a detailed explanation of the architectural decisions, database choices, LLM prompting strategy, and guardrails implemented in DodgeAI.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Architecture Decisions](#architecture-decisions)
- [Database Choice](#database-choice)
- [LLM Prompting Strategy](#llm-prompting-strategy)
- [Guardrails](#guardrails)
- [Security Considerations](#security-considerations)

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

The system follows a **three-tier architecture**:

1. **Presentation Layer** — React frontend with Cytoscape.js graph visualization and chat interface
2. **Application Layer** — FastAPI backend with graph traversal and text-to-SQL pipelines
3. **Data Layer** — PostgreSQL 16 with pgvector for both relational data and vector embeddings

---

## Architecture Decisions

### 1. Graph Derived from Relational Database

**Decision:** Instead of using a dedicated graph database (Neo4j, ArangoDB), we derive the graph representation at query time from PostgreSQL foreign keys.

**Rationale:**

| Factor                            | Reasoning                                                                                                                                |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Data is naturally tabular**     | SAP exports are flat records with foreign keys. Tables map 1:1 to source JSONL files with zero transformation.                           |
| **Scale is manageable**           | The dataset contains thousands (not millions) of documents. Recursive CTEs with depth limits handle subgraph extraction in milliseconds. |
| **LLM generates SQL, not Cypher** | Text-to-SQL is well-studied with abundant training data. LLMs produce more reliable SQL than Cypher or SPARQL.                           |
| **Operational simplicity**        | A single PostgreSQL instance serves both the graph API and chat pipeline. No graph-to-relational sync layer needed.                      |
| **No duplication**                | The graph always reflects the current database state — no eventual consistency issues.                                                   |

**Implementation:**

```python
# Graph traversal via recursive CTEs in SQL
WITH RECURSIVE graph_traversal AS (
    SELECT ... FROM sales_order_headers WHERE sales_order = :root_id
    UNION ALL
    SELECT ... FROM sales_order_items JOIN graph_traversal ON ...
    UNION ALL
    SELECT ... FROM outbound_delivery_items JOIN graph_traversal ON ...
)
SELECT * FROM graph_traversal WHERE depth <= :max_depth;
```

### 2. Five-Stage Text-to-SQL Pipeline

**Decision:** A hand-rolled pipeline with explicit stages rather than using a framework like Vanna.ai.

**Rationale:**

| Requirement              | Why Custom                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------- |
| **Structured output**    | Need strict JSON payload (`{answer, sql, data, entities}`) with entity extraction for graph highlighting. |
| **Pre-LLM guardrails**   | Domain restriction and injection detection before any LLM call (zero-latency rejection).                  |
| **Entity extraction**    | Map result columns to graph node types for real-time graph highlighting.                                  |
| **Minimal dependencies** | Only `google-genai` + `psycopg2` + `pgvector` — reduces install size and version conflicts.               |

**Pipeline Stages:**

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
│   Retrieval  │  (cosine similarity on embeddings)
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
│   Synthesis  │  with embedded graph node references
└─────────────┘
```

### 3. RAG with Three-Source Context

**Decision:** Retrieve from three distinct knowledge categories for each query.

**Knowledge Categories:**

| Category        | Content                                     | Purpose                                          |
| --------------- | ------------------------------------------- | ------------------------------------------------ |
| **DDL schemas** | Table CREATE statements, column definitions | Structural knowledge — what tables/columns exist |
| **Domain docs** | Business context, FK mappings, status codes | Semantic knowledge — what the data means         |
| **SQL pairs**   | Curated question-SQL examples               | Tactical knowledge — proven query patterns       |

**Why Three Sources?**

- **DDL alone** → LLM knows columns but not business meaning
- **Docs alone** → LLM understands concepts but not exact schema
- **SQL pairs alone** → LLM can copy patterns but can't adapt to novel queries
- **All three** → LLM has complete context for accurate query generation

### 4. Provider-Agnostic Design

**Decision:** Abstract LLM and embedding providers behind interfaces.

**Rationale:**

- **Future-proofing** — Easy to switch from Gemini to OpenAI, Anthropic, or local models
- **Testing** — Mock providers for unit tests without API calls
- **Cost optimization** — Use different providers for embeddings vs. generation

**Abstraction Layer:**

```python
# LLM Provider Interface
class LLMProvider(Protocol):
    def generate(self, prompt: str, system: str) -> str: ...
    def generate_structured(self, prompt: str, schema: dict) -> dict: ...

# Embedding Provider Interface
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

---

## Database Choice

### PostgreSQL 16 with pgvector

**Primary Database:** PostgreSQL 16 (via `pgvector/pgvector:pgvector:pg16` Docker image)

**Why PostgreSQL over a Graph Database?**

| Criterion                  | PostgreSQL                      | Neo4j                       | Decision Factor           |
| -------------------------- | ------------------------------- | --------------------------- | ------------------------- |
| **Data model**             | Native fit for SAP tabular data | Requires transformation     | ✅ PostgreSQL              |
| **Query language**         | SQL (LLM-friendly)              | Cypher (less training data) | ✅ PostgreSQL              |
| **Operational complexity** | Single database                 | Graph + relational sync     | ✅ PostgreSQL              |
| **Performance at scale**   | Excellent for thousands of rows | Excellent for millions      | ⚖️ PostgreSQL (sufficient) |
| **Vector search**          | pgvector built-in               | Requires separate index     | ✅ PostgreSQL              |
| **Team expertise**         | Common skill set                | Specialized                 | ✅ PostgreSQL              |

**Why pgvector over ChromaDB?**

The system originally used ChromaDB for vector storage but migrated to pgvector:

| Factor               | ChromaDB                       | pgvector                  | Winner     |
| -------------------- | ------------------------------ | ------------------------- | ---------- |
| **Infrastructure**   | Separate service or file-based | Extension in PostgreSQL   | ✅ pgvector |
| **Transactions**     | No ACID guarantees             | Full ACID compliance      | ✅ pgvector |
| **Query complexity** | Simple similarity search       | Join with relational data | ✅ pgvector |
| **Backup/restore**   | Separate backup                | Single database backup    | ✅ pgvector |
| **Latency**          | Network call (if server)       | In-process                | ✅ pgvector |

**Schema Design:**

The database contains 17 tables representing SAP O2C entities:

| Category        | Tables                                                                                                                                                                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Core flow**   | `sales_order_headers`, `sales_order_items`, `outbound_delivery_headers`, `outbound_delivery_items`, `billing_document_headers`, `billing_document_items`, `journal_entry_items_accounts_receivable`, `payments_accounts_receivable` |
| **Master data** | `business_partners`, `business_partner_addresses`, `products`, `product_descriptions`, `plants`                                                                                                                                     |
| **Assignments** | `customer_company_assignments`, `customer_sales_area_assignments`, `product_plants`, `product_storage_locations`                                                                                                                    |
| **RAG vectors** | `rag_embeddings` (pgvector table)                                                                                                                                                                                                   |

**Key Design Patterns:**

1. **Composite Primary Keys** — Documents use `(document_id, item_id)` composites
2. **Normalized Item Numbers** — Zero-padded in source tables (`000010`), short form in references (`10`)
3. **Cross-Document Joins** — Use `REGEXP_REPLACE(column, '^0+', '')` to normalize item numbers
4. **Soft Deletes** — `is_marked_for_deletion` and `deletion_indicator` flags instead of hard deletes
5. **Audit Trail** — `creation_date`, `created_by_user`, `last_change_datetime` on all tables

---

## LLM Prompting Strategy

### Model Selection: Google Gemini 2.0 Flash

**Selected Model:** `gemini-2.0-flash`

**Rationale:**

| Factor              | Gemini 2.0 Flash                             | Alternatives Considered   |
| ------------------- | -------------------------------------------- | ------------------------- |
| **Cost**            | Free tier available                          | GPT-4, Claude are paid    |
| **Latency**         | Fast inference (~500ms)                      | Some models 2-5x slower   |
| **SQL generation**  | Strong performance on text-to-SQL benchmarks | Comparable to GPT-3.5     |
| **Context window**  | 1M tokens (sufficient for RAG context)       | Most models 128K-200K     |
| **Embedding model** | `text-embedding-004` (3072 dimensions)       | OpenAI ada-002 (1536 dim) |

### SQL Generation Prompt

The SQL generation prompt encodes **10 rules** that constrain the LLM output:

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

**Key Design Decisions:**

| Rule        | Purpose                                                                                     |
| ----------- | ------------------------------------------------------------------------------------------- |
| **Rule 3**  | Addresses zero-padding normalization — the most common source of broken joins in SAP data   |
| **Rule 6**  | Prevents FK confusion (`business_partner` vs `customer` column)                             |
| **Rule 8**  | Provides a clean escape hatch (`CANNOT_GENERATE`) rather than hallucinating invalid SQL     |
| **Rule 10** | Prevents empty result sets when optional relationships would cause INNER JOINs to drop rows |

### Response Synthesis Prompt

A second Gemini call converts raw query results into natural language:

```
You are a helpful data analyst assistant for an SAP Order-to-Cash dataset.

Given a user question, the SQL query that was executed, and the query results, provide a clear,
concise natural language answer followed by a structured JSON block of graph entities.

RULES:
1. Answer based ONLY on the data provided. Do not make up information.
2. ALWAYS begin your answer by citing the data: e.g. "Based on 12 records found..."
3. If the results are empty, say clearly "No matching records were found in the dataset."
4. Include specific numbers, entity IDs, names, and values from the results.
5. Keep the answer conversational but factual.
6. If the data contains amounts, include the currency.
7. Format large numbers with commas for readability.
8. Do not include the SQL query in your response.
9. Highlight key findings or patterns in the data.
10. If you are showing top results from a larger set, note: "Showing top 25 results — there may be more."

GRAPH ENTITY EXTRACTION (MANDATORY):
After your natural language answer, you MUST append a JSON block in EXACTLY this format:

```graph_nodes
[
  {"id": "Invoice:90000001", "type": "Invoice", "label": "90000001"},
  {"id": "SalesOrder:10001", "type": "SalesOrder", "label": "10001"},
  {"id": "Customer:CUST001", "type": "Customer", "label": "CUST001"}
]
```
```

**Entity Type Mapping:**

| Column Pattern                         | Graph Node Type |
| -------------------------------------- | --------------- |
| `billing_document`, `invoice`          | `Invoice`       |
| `sales_order`                          | `SalesOrder`    |
| `delivery_document`, `delivery`        | `Delivery`      |
| `accounting_document`, `journal_entry` | `JournalEntry`  |
| `payment_document`                     | `Payment`       |
| `customer`, `sold_to_party`            | `Customer`      |
| `material`, `product`                  | `Product`       |

### RAG Context Assembly

For each user question, the system retrieves from pgvector:

```python
# Retrieval configuration
config = RetrievalConfig(
    schema_n=5,           # DDL schemas
    relationships_n=4,    # FK constraints + O2C chain narrative
    data_profile_n=3,     # Per-table statistical summaries
    sql_pair_n=5,         # Question-SQL examples
    documentation_n=5,    # Domain context documents
)
```

**Embedding Generation:**

```python
# Gemini text-embedding-004 produces 3072-dimensional vectors
def generate_embeddings(texts: list[str]) -> list[list[float]]:
    client = genai.Client(api_key=ai_settings.GEMINI_API_KEY)
    response = client.models.embed_content(
        model="text-embedding-004",
        contents=batch,  # Up to 100 texts per batch
    )
    return [e.values for e in response.embeddings]
```

**Similarity Search:**

```sql
SELECT content, metadata, 1 - (embedding <=> :query_vector::vector) AS similarity
FROM rag_embeddings
WHERE category = :category
ORDER BY embedding <=> :query_vector::vector
LIMIT :n_results;
```

---

## Guardrails

The guardrail system is a **multi-layer filter** that runs before any LLM call, keeping latency near zero for rejected queries.

### Layer 1: Input Validation

```python
if len(stripped) < 3:
    return "Please provide a more specific question about the dataset."
```

**Purpose:** Reject empty or trivial inputs.

### Layer 2: SQL Injection Detection

```python
mutation_pattern = re.compile(
    r"\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE)\b",
    re.I,
)
if mutation_pattern.search(stripped):
    return "This query appears to contain data-modification statements. Only read-only (SELECT) queries are supported."
```

**Blocked Patterns:**

- `DROP TABLE`
- `DELETE FROM`
- `TRUNCATE`
- `ALTER TABLE`
- `INSERT INTO`
- `UPDATE ... SET`
- `CREATE TABLE`

### Layer 3: Prompt Injection Detection

```python
injection_pattern = re.compile(
    r"\b(ignore\s+(all\s+)?previous|forget\s+(all\s+)?instructions|pretend\s+you|you\s+are\s+now|act\s+as)\b",
    re.I,
)
if injection_pattern.search(stripped):
    return REJECTION_MESSAGE
```

**Blocked Patterns:**

- "ignore previous instructions"
- "forget all instructions"
- "pretend you are"
- "you are now"
- "act as"

### Layer 4: Off-Topic Pattern Matching

```python
OFF_TOPIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(write|compose|create)\s+(a\s+)?(poem|story|essay|song|code|script)\b", re.I),
    re.compile(r"\b(who\s+is|what\s+is|tell\s+me\s+about)\s+(the\s+)?(president|capital|population)\b", re.I),
    re.compile(r"\b(weather|recipe|joke|riddle|trivia|news)\b", re.I),
    re.compile(r"\b(translate|summarize\s+this\s+article|explain\s+quantum)\b", re.I),
    re.compile(r"\b(play|game|chess|tic.tac.toe)\b", re.I),
]
```

**Blocked Categories:**

- **Creative writing:** "write a poem/story/essay"
- **General knowledge:** "who is the president", "what is the capital"
- **Casual queries:** "weather", "recipe", "joke", "news"
- **Games:** "play chess", "tic tac toe"

### Layer 5: Domain Relevance Check

```python
DOMAIN_KEYWORDS: set[str] = {
    "order", "orders", "sales", "customer", "customers", "delivery", "deliveries",
    "invoice", "invoices", "billing", "payment", "payments", "product", "products",
    "material", "journal", "entry", "accounting", "document", "revenue", "amount",
    "quantity", "address", "plant", "shipped", "delivered", "billed", "paid",
    "unpaid", "cancelled", "flow", "trace", "o2c", "sap", "supply chain",
    # ... (40+ keywords total)
}

has_domain_relevance = any(kw in lower for kw in DOMAIN_KEYWORDS)
has_analytical_intent = bool(analytical_patterns.search(stripped))

if not has_domain_relevance and not has_analytical_intent:
    return REJECTION_MESSAGE
```

**Domain Keywords:** 40+ SAP O2C-related terms

**Analytical Intent Patterns:**

- `how many`
- `show`
- `list`
- `find`
- `top N`
- `total`, `sum`, `avg`, `count`, `max`, `min`

**Fallback Message:**

> "This system is designed to answer questions related to the SAP Order-to-Cash dataset only. Please ask about sales orders, deliveries, invoices, payments, customers, products, or their relationships."

### Post-Generation SQL Validation

Even after the LLM generates SQL, a final safety check is applied:

```python
# Safety: reject any mutation
if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", sql, re.I):
    logger.warning("sql_generation.mutation_detected", sql=sql[:200])
    return None
```

**Defense in Depth:** This catches any mutations that might slip through the LLM despite Rule 1 of the prompt.

### Database-Level Protection

The SQL execution uses a **read-only connection**:

```python
# Database connection is configured for read-only access
# Even if a mutation query passes all guards, PostgreSQL will reject it
```

---

## Security Considerations

### 1. Read-Only Database Access

- PostgreSQL connection is configured with read-only permissions
- Even if guardrails fail, `INSERT`/`UPDATE`/`DELETE` statements will be rejected by the database

### 2. Parameterized Queries

- All user inputs are passed as parameters, not interpolated into SQL strings
- Prevents SQL injection at the database driver level

### 3. API Rate Limiting

- FastAPI middleware can be configured for rate limiting (not enabled in development)
- Recommended for production: `slowapi` or similar

### 4. Environment Variable Security

- API keys loaded from `.env` file (not committed to version control)
- `.env` is in `.gitignore`

### 5. Input Sanitization

- All user inputs are stripped and validated before processing
- Minimum length check prevents empty queries

### 6. Output Truncation

- Query results truncated to 50 rows before passing to LLM (token limit protection)
- Error messages truncated to 200-300 characters (prevents log flooding)

### 7. Structured Logging

- All operations logged with `structlog`
- Sensitive data (API keys, full SQL queries) redacted or truncated in logs

---

## Summary

| Decision          | Choice                  | Rationale                                                    |
| ----------------- | ----------------------- | ------------------------------------------------------------ |
| **Graph storage** | PostgreSQL FK traversal | No sync issues, simpler ops, LLM-friendly SQL                |
| **Vector store**  | pgvector                | Single database, ACID compliance, joins with relational data |
| **LLM**           | Gemini 2.0 Flash        | Free tier, fast inference, strong SQL generation             |
| **RAG sources**   | DDL + docs + SQL pairs  | Complete context (structural + semantic + tactical)          |
| **Pipeline**      | Custom 5-stage          | Structured output, guardrails, entity extraction             |
| **Guardrails**    | 5-layer regex + keyword | Zero-latency rejection, defense in depth                     |

This architecture balances **performance**, **simplicity**, and **safety** while providing a powerful natural language interface to SAP O2C data.
