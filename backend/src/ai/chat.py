"""Text-to-SQL chat pipeline using Gemini + pgvector RAG.

Pipeline:
1. Guardrails → reject off-topic queries
2. RAG retrieval → fetch relevant DDL, docs, SQL pairs, data summaries from pgvector
3. SQL generation → Gemini generates SQL from context + question
4. SQL execution → execute against PostgreSQL (read-only)
5. Response synthesis → Gemini produces natural language answer from results
"""

import re
from dataclasses import dataclass, field

import pandas as pd
import structlog
from google import genai
from sqlalchemy import create_engine, text

from .config import ai_settings
from .embeddings import generate_embedding
from .guardrails import check_guardrails
from .retrieval import RetrievalConfig, retrieve_schema_context
from .training import train_all

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GraphNodeRef:
    """A reference to a graph node extracted from query results."""
    id: str        # e.g. "Invoice:5001"
    type: str      # e.g. "Invoice"
    label: str     # e.g. "5001"


@dataclass(frozen=True)
class ChatResponse:
    answer: str
    sql: str | None = None
    data: list[dict] | None = None
    entities: list[dict] = field(default_factory=list)
    graph_nodes: list[dict] = field(default_factory=list)
    error: str | None = None
    row_count: int = 0
    summary: str = ""


# ---------------------------------------------------------------------------
# Singleton engine for synchronous SQL execution (read-only)
# ---------------------------------------------------------------------------

_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        from src.db.config import db_settings

        dsn = str(db_settings.DATABASE_DSN)
        sync_dsn = dsn.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        _sync_engine = create_engine(sync_dsn, pool_pre_ping=True, pool_size=3)
    return _sync_engine


# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

_gemini_client = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        if not ai_settings.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Please set it in backend/.env"
            )
        _gemini_client = genai.Client(api_key=ai_settings.GEMINI_API_KEY)
    return _gemini_client


# ---------------------------------------------------------------------------
# Ensure training data is loaded
# ---------------------------------------------------------------------------

_trained = False


def _ensure_trained():
    global _trained
    if not _trained:
        # Check if embeddings already exist in pgvector
        engine = _get_sync_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM rag_embeddings"))
            count = result.scalar()
        if count == 0:
            train_all()
        _trained = True


# ---------------------------------------------------------------------------
# RAG retrieval (pgvector cosine similarity)
# ---------------------------------------------------------------------------

def _retrieve_context(question: str, n_results: int = 5) -> str:
    """Retrieve relevant schema, relationships, data profiles, SQL pairs, and docs from pgvector."""
    _ensure_trained()

    engine = _get_sync_engine()
    question_embedding = generate_embedding(question)

    config = RetrievalConfig(
        schema_n=n_results,
        relationships_n=4,
        data_profile_n=3,
        sql_pair_n=n_results,
        documentation_n=n_results,
    )
    return retrieve_schema_context(engine, question_embedding, config)


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

_SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL SQL query generator for an SAP Order-to-Cash dataset.

RULES:
1. Generate ONLY valid PostgreSQL SELECT queries. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, or any data-modification statements.
2. Use only the tables and columns provided in the context. Do not invent tables or columns.
3. When joining across documents (e.g., delivery items to sales order items), use REGEXP_REPLACE(column, '^0+', '') to normalize item numbers that may have different zero-padding.
4. Always use table aliases for clarity.
5. Use LIMIT to prevent returning too many rows (default LIMIT 25 unless the user asks for more).
6. For customer lookups, remember: sales_order_headers.sold_to_party = business_partners.customer (NOT business_partner).
7. Return ONLY the SQL query, no explanation. Do not wrap in markdown code blocks.
8. If you cannot generate a valid query for the question, return exactly: CANNOT_GENERATE
9. For aggregations, include relevant GROUP BY clauses.
10. Use LEFT JOIN when the relationship might not exist (e.g., not all orders have deliveries).
"""


def _generate_sql(question: str, context: str) -> str | None:
    """Use Gemini to generate SQL from question + RAG context."""
    client = _get_gemini_client()

    prompt = f"""{_SQL_SYSTEM_PROMPT}

CONTEXT:
{context}

USER QUESTION: {question}

Generate a PostgreSQL SELECT query to answer this question:"""

    response = client.models.generate_content(
        model=ai_settings.GEMINI_MODEL,
        contents=prompt,
    )

    sql = response.text.strip() if response.text else None
    if not sql or sql == "CANNOT_GENERATE":
        return None

    # Clean up markdown code fences if present
    sql = re.sub(r"^```(?:sql)?\s*\n?", "", sql)
    sql = re.sub(r"\n?```\s*$", "", sql)
    sql = sql.strip()

    # Safety: reject any mutation
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", sql, re.I):
        logger.warning("sql_generation.mutation_detected", sql=sql[:200])
        return None

    return sql


# ---------------------------------------------------------------------------
# SQL execution
# ---------------------------------------------------------------------------

def _execute_sql(sql: str) -> tuple[list[dict], list[str]]:
    """Execute SQL and return (rows_as_dicts, column_names)."""
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
    return rows, columns


# ---------------------------------------------------------------------------
# Response synthesis
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM_PROMPT = """You are a helpful data analyst assistant for an SAP Order-to-Cash dataset.

Given a user question, the SQL query that was executed, and the query results, provide a clear,
concise natural language answer followed by a structured JSON block of graph entities.

RULES:
1. Answer based ONLY on the data provided. Do not make up information.
2. ALWAYS begin your answer by citing the data: e.g. "Based on 12 records found..." or "From the 0 results returned...".
3. If the results are empty, say clearly "No matching records were found in the dataset." and explain what was searched.
4. Include specific numbers, entity IDs, names, and values from the results.
5. Keep the answer conversational but factual.
6. If the data contains amounts, include the currency.
7. Format large numbers with commas for readability.
8. Do not include the SQL query in your response.
9. Highlight key findings or patterns in the data.
10. If you are showing top results from a larger set (the row count is at the LIMIT of 25), note: "Showing top 25 results — there may be more in the dataset."

GRAPH ENTITY EXTRACTION (MANDATORY):
After your natural language answer, you MUST append a JSON block in EXACTLY this format:

```graph_nodes
[
  {"id": "Invoice:90000001", "type": "Invoice", "label": "90000001"},
  {"id": "SalesOrder:10001", "type": "SalesOrder", "label": "10001"},
  {"id": "Customer:CUST001", "type": "Customer", "label": "CUST001"}
]
```

Entity type mapping (use EXACTLY these type names):
- Billing/Invoice document numbers → type: "Invoice"
- Sales order numbers → type: "SalesOrder"
- Delivery document numbers → type: "Delivery"
- Accounting/journal entry numbers → type: "JournalEntry"
- Payment document numbers → type: "Payment"
- Customer/business partner IDs → type: "Customer"
- Material/product codes → type: "Product"

The "id" field MUST be "{type}:{value}" (e.g. "Invoice:90000001").
The "label" field is just the raw value (e.g. "90000001").
Only include entities that appear in the actual query results.
Include up to 25 entities maximum.
If there are no entities, output an empty array: ```graph_nodes\n[]\n```
"""


def _synthesize_response(
    question: str,
    sql: str,
    data: list[dict],
    columns: list[str],
) -> tuple[str, list[dict]]:
    """Use Gemini to produce a natural language answer and extract structured graph nodes.

    Returns (answer_text, graph_nodes) where graph_nodes is a list of
    {"id": "Type:value", "type": "Type", "label": "value"} dicts.
    """
    client = _get_gemini_client()

    # Truncate data for the prompt if too large
    display_data = data[:50]
    df = pd.DataFrame(display_data, columns=columns) if display_data else pd.DataFrame()

    prompt = f"""{_SYNTHESIS_SYSTEM_PROMPT}

USER QUESTION: {question}

SQL EXECUTED:
{sql}

QUERY RESULTS ({len(data)} total rows, showing first {len(display_data)}):
{df.to_string(index=False) if not df.empty else "(no results)"}

Provide a natural language answer followed by the graph_nodes JSON block:"""

    response = client.models.generate_content(
        model=ai_settings.GEMINI_MODEL,
        contents=prompt,
    )

    raw = response.text.strip() if response.text else ""
    return _parse_synthesis_response(raw)


def _parse_synthesis_response(raw: str) -> tuple[str, list[dict]]:
    """Split the LLM output into (answer_text, graph_nodes)."""
    import json

    graph_nodes: list[dict] = []

    # Extract the ```graph_nodes ... ``` block
    block_match = re.search(r"```graph_nodes\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if block_match:
        json_str = block_match.group(1).strip()
        try:
            nodes = json.loads(json_str)
            if isinstance(nodes, list):
                # Validate each node has required fields
                graph_nodes = [
                    {"id": n["id"], "type": n["type"], "label": str(n.get("label", ""))}
                    for n in nodes
                    if isinstance(n, dict) and "id" in n and "type" in n
                ]
        except (json.JSONDecodeError, KeyError):
            logger.warning("synthesis.graph_nodes_parse_failed", raw_block=json_str[:200])

    # Strip the graph_nodes block from the answer
    answer = re.sub(r"\n?```graph_nodes[\s\S]*?```\s*$", "", raw, flags=re.IGNORECASE).strip()
    if not answer:
        answer = "I was unable to generate a response."

    return answer, graph_nodes


# ---------------------------------------------------------------------------
# Entity extraction for graph highlighting
# ---------------------------------------------------------------------------

def _extract_entities(data: list[dict]) -> list[dict]:
    """Extract entity references from query results for graph highlighting.

    Graph node IDs are in the format "{Type}:{pk_value}" (e.g. "Invoice:5001").
    The entity_key produced here must match that format exactly.
    """
    entities: list[dict] = []
    seen: set[str] = set()

    # Maps a column name substring → graph node type.
    # Keys ordered longest-first so more specific matches win.
    entity_column_map: dict[str, str] = {
        "billing_doc_number": "Invoice",
        "billing_document": "Invoice",
        "invoice": "Invoice",
        "sales_order_id": "SalesOrder",
        "sales_order": "SalesOrder",
        "delivery_document": "Delivery",
        "delivery_id": "Delivery",
        "delivery": "Delivery",
        "accounting_document": "JournalEntry",
        "journal_entry_id": "JournalEntry",
        "journal_entry": "JournalEntry",
        "payment_document": "Payment",
        "payment_id": "Payment",
        "customer_id": "Customer",
        "customer": "Customer",
        "business_partner": "Customer",
        "material_id": "Product",
        "material": "Product",
        "product": "Product",
    }

    for row in data[:100]:
        for col, val in row.items():
            if val is None:
                continue
            col_lower = col.lower()
            for key, node_type in entity_column_map.items():
                if key in col_lower:
                    entity_key = f"{node_type}:{val}"
                    if entity_key not in seen:
                        seen.add(entity_key)
                        entities.append({"id": entity_key, "type": node_type, "value": str(val)})
                    break

    return entities


# ---------------------------------------------------------------------------
# Main chat function
# ---------------------------------------------------------------------------

def chat(message: str) -> ChatResponse:
    """Process a chat message through the full pipeline."""
    logger.info("chat.start", message=message[:100])

    # 1. Guardrails
    rejection = check_guardrails(message)
    if rejection:
        logger.info("chat.rejected", reason=rejection[:80])
        return ChatResponse(answer=rejection, error="guardrail")

    try:
        # 2. RAG retrieval
        context = _retrieve_context(message)
        logger.debug("chat.context_retrieved", context_length=len(context))

        # 3. SQL generation
        sql = _generate_sql(message, context)
        if not sql:
            return ChatResponse(
                answer="I wasn't able to generate a query for that question. "
                       "Could you rephrase it or be more specific about which entities "
                       "(orders, invoices, customers, etc.) you're asking about?",
                error="sql_generation_failed",
            )
        logger.info("chat.sql_generated", sql=sql[:200])

        # 4. SQL execution
        try:
            data, columns = _execute_sql(sql)
            logger.info("chat.sql_executed", rows=len(data))
        except Exception as exc:
            logger.error("chat.sql_execution_failed", error=str(exc), sql=sql[:200])
            return ChatResponse(
                answer="The generated query encountered an error. Let me try a different approach - "
                       "could you rephrase your question?",
                sql=sql,
                error=f"sql_execution_error: {str(exc)[:200]}",
            )

        # 5. Response synthesis + structured graph node extraction
        answer, graph_nodes = _synthesize_response(message, sql, data, columns)
        logger.info("chat.response_synthesized", answer_length=len(answer), graph_nodes=len(graph_nodes))

        # 6. Legacy heuristic entity extraction (kept for backwards compat)
        entities = _extract_entities(data)

        # 7. Build summary / data citation
        _RESULT_LIMIT = 25
        row_count = len(data)
        if row_count == 0:
            summary = "No matching records found."
        elif row_count >= _RESULT_LIMIT:
            summary = f"Showing top {_RESULT_LIMIT} results — there may be more."
        else:
            summary = f"{row_count} record{'s' if row_count != 1 else ''} found."

        # Serialize data (convert non-serializable types)
        serialized_data = []
        for row in data[:100]:
            serialized_row = {}
            for k, v in row.items():
                if v is None:
                    serialized_row[k] = None
                elif isinstance(v, (int, float, str, bool)):
                    serialized_row[k] = v
                else:
                    serialized_row[k] = str(v)
            serialized_data.append(serialized_row)

        return ChatResponse(
            answer=answer,
            sql=sql,
            data=serialized_data,
            entities=entities,
            graph_nodes=graph_nodes,
            row_count=row_count,
            summary=summary,
        )

    except Exception as exc:
        logger.exception("chat.unexpected_error")
        return ChatResponse(
            answer="An unexpected error occurred while processing your question. Please try again.",
            error=str(exc)[:300],
        )
