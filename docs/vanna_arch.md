# Architecture: Vanna-Powered Graph Chat System

## 1. Scope
A Text-to-SQL RAG layer powered by the open-source Vanna framework, integrating with the PostgreSQL graph backend to provide deterministic, schema-backed conversational querying and visualization.

## 2. Core Vanna Integration Design
- **Vanna as the Core Engine**: Utilizing Vanna's end-to-end framework for embedding storage, prompt construction, and SQL generation.
- **Training Data Focus (No Row Embeddings)**: Vanna is trained strictly on architectural metadata: DDL (schema), explicit Documentation (graph relationships, domain context), and SQL Question-Answer pairs (join templates).
- **Modular Providers**: Leveraging Vanna's native modularity to inject chosen `LLM` (e.g., Gemini) and `VectorStore` (e.g., PgVector) classes.
- **Deterministic Execution**: LLM generates SQL; Vanna deterministically executes it against read-only PostgreSQL tables to retrieve factual data.

## 3. Vanna Setup & Training Strategy
Instead of building custom vectorization, we map our graph metadata into Vanna's native training modalities:
1. **DDL Training (`vn.train(ddl=...)`)**: Embed all relational table schemas, primary keys, and column constraints.
2. **Documentation Training (`vn.train(documentation=...)`)**: Embed explicit text defining the graph topology (e.g., "BillingDocuments connect to JournalEntries via the accountingDocument field"). This ensures the LLM understands how to navigate the graph without our custom expansion step.
3. **SQL Pair Training (`vn.train(sql=..., question=...)`)**: Embed exact, validated graph traversal sub-queries (e.g., multi-hop O2C flows) to heavily bias and guide the LLM's join generation.

## 4. Query & Generation Pipeline (Step-by-Step Vanna)
Our system wraps Vanna's constituent APIs rather than using its end-to-end `ask()` method, allowing us to intercept and structure the final output:
1. **Guardrails**: Pre-filter user input for domain relevance before passing to Vanna.
2. **Vanna Semantic Retrieval**: Vanna internally searches DDL, docs, and SQL pairs based on the user's question to assemble the prompt.
3. **Vanna SQL Generation**: Call `vn.generate_sql(question=input)` to draft the query using the optimized context.
4. **Execution**: Call `vn.run_sql(sql=query)` to run the drafted SQL against the PostgreSQL database.
5. **Structured Synthesis**: Pass the resulting dataframe and the original question to our chosen LLM to enforce our strict JSON payload, overriding Vanna's default charting or plain-text summaries.

## 5. System Abstractions
- **`VannaPgVector` / `VannaGemini`**: Custom classes instantiating Vanna with our exact Provider stack.
- **Custom System Prompt**: Override Vanna's default prompt to forcefully mandate the use of graph logic (e.g., leveraging the `graph_edges` table if applicable) during SQL generation.

## 6. Output & Graph Integration
- **Strict Output Format**: The custom synthesis step guarantees the predefined payload: `{ answer, entities, relationships }`.
- **Unified Introspection**: Parsed entities and relationships natively feed back to the visualization layer to trigger dynamic node and edge representation, ensuring the chat and graph function as an entirely integrated interface.
