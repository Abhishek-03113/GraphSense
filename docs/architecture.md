# Architecture: RAG-Powered Graph Chat System

## 1. Scope
A provider-agnostic, LLM-powered RAG layer natively integrating with the PostgreSQL graph backend to provide deterministic, schema-backed conversational querying.

## 2. Core Design
- **Graph-First**: Schema definitions and explicit graph relationships serve as the exclusive source of truth.
- **Provider-Agnostic**: Strict interface separation for LLMs, embedding models, and vector storage.
- **Deterministic**: LLM usage is constrained to intent parsing, SQL generation, and response synthesis.
- **Structural Embedding**: RAG vectorizes schemas (tables, columns, FKs), graph edges, and query patterns exclusively. Raw row data is never embedded.

## 3. RAG Retrieval Strategy
1. **Semantic Search**: Map query against structurally embedded schemas (`schema_embeddings` via PgVector).
2. **Graph Expansion**: Augment context by traversing to immediate graph neighbors (Depth=1) from semantic hits.
3. **Context Assembly**: Provide composite context (semantic hits + graph adjacencies) to prevent missing joins and reduce synthesis errors.

## 4. Query Pipeline
1. **Guardrails**: Filter inputs for domain restriction, SQL safety, and logic bounding.
2. **Intent Parsing (LLM)**: Extract strictly formatted operational logic: `{intent, entities, filters}`.
3. **RAG Retrieval**: Execute semantic schema search paired with graph expansion.
4. **SQL Generation (LLM)**: Draft queries bound strictly by retrieved schemas and intent.
5. **SQL Execution**: Execute read-only requests against underlying relational/graph datastores.
6. **Response Construction**: Enforce strict output structures based on executed results.

## 5. Abstractions
- **`LLMProvider`**: Interface exposing `generate`, `generate_stream`, and `generate_structured(schema)`.
- **`EmbeddingProvider`**: Interface exposing `embed` and `embed_batch`.
- **`VectorStore`**: Interface handling abstract persistence and vector execution.

## 6. Output & Graph Integration
- **Strict Output Format**: Pipeline synthesis guarantees a predefined dictionary payload: `{ answer, entities, relationships }`.
- **Unified Introspection**: Parsed entities and relationship paths natively feed back to the visualization layer to trigger dynamic node and edge representation, ensuring the chat and graph function as a singular linked interface.
