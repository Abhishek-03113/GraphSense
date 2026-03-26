"""Retrieval module — multi-category fan-out RAG context assembly.

Replaces the inline _retrieve_context logic in chat.py with a structured,
configurable retrieval pipeline that queries across all five embedding
categories and formats the results into a prompt-ready context block.
"""

from dataclasses import dataclass

import structlog

from .embeddings import query_similar

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetrievalConfig:
    """Per-category result budgets for context assembly."""
    schema_n: int = 5
    relationships_n: int = 4
    data_profile_n: int = 3
    sql_pair_n: int = 4
    documentation_n: int = 3
    similarity_threshold: float = 0.0  # 0.0 = no filter


def retrieve_by_category(
    engine,
    question_embedding: list[float],
    category: str,
    n_results: int,
    similarity_threshold: float = 0.0,
) -> list[dict]:
    """Retrieve top-N results for a single category, optionally filtered by threshold."""
    results = query_similar(engine, question_embedding, category=category, n_results=n_results)
    if similarity_threshold > 0.0:
        results = [r for r in results if r["similarity"] >= similarity_threshold]
    return results


def format_sql_pair(result: dict) -> str:
    """Format a sql_pair retrieval result for inclusion in the context block."""
    meta = result.get("metadata") or {}
    question = meta.get("question", result.get("content", ""))
    sql = meta.get("sql", "")
    return f"Question: {question}\nSQL:\n{sql}"


def retrieve_schema_context(
    engine,
    question_embedding: list[float],
    config: RetrievalConfig = RetrievalConfig(),
) -> str:
    """Fan out to all five categories, merge, and format as a structured context block.

    Returns a multi-section string with clearly labeled sections.
    Empty sections are omitted.
    """
    parts: list[str] = []

    # 1. Table schemas (DDL)
    schema_results = retrieve_by_category(
        engine, question_embedding, "schema", config.schema_n, config.similarity_threshold
    )
    if schema_results:
        parts.append("=== RELEVANT TABLE SCHEMAS ===")
        for r in schema_results:
            parts.append(r["content"])

    # 2. FK Relationships
    rel_results = retrieve_by_category(
        engine, question_embedding, "relationships", config.relationships_n, config.similarity_threshold
    )
    if rel_results:
        parts.append("\n=== RELATIONSHIPS ===")
        for r in rel_results:
            parts.append(r["content"])

    # 3. Data profiles
    profile_results = retrieve_by_category(
        engine, question_embedding, "data_profile", config.data_profile_n, config.similarity_threshold
    )
    if profile_results:
        parts.append("\n=== DATA PROFILES (from actual data) ===")
        for r in profile_results:
            parts.append(r["content"])

    # 4. SQL examples
    sql_results = retrieve_by_category(
        engine, question_embedding, "sql_pair", config.sql_pair_n, config.similarity_threshold
    )
    if sql_results:
        parts.append("\n=== EXAMPLE SQL QUERIES ===")
        for r in sql_results:
            parts.append(format_sql_pair(r))

    # 5. Domain documentation
    doc_results = retrieve_by_category(
        engine, question_embedding, "documentation", config.documentation_n, config.similarity_threshold
    )
    if doc_results:
        parts.append("\n=== DOMAIN DOCUMENTATION ===")
        for r in doc_results:
            parts.append(r["content"])

    logger.debug(
        "retrieval.context_assembled",
        schema=len(schema_results),
        relationships=len(rel_results),
        data_profile=len(profile_results),
        sql_pairs=len(sql_results),
        documentation=len(doc_results),
    )

    return "\n\n".join(parts)
