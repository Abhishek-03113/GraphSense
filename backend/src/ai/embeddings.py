"""pgvector-based embedding store using Gemini text-embedding-004.

Replaces ChromaDB — all embeddings live in the rag_embeddings table.
"""

import hashlib
import json
from typing import Optional

import structlog
from google import genai
from sqlalchemy import text, select, delete
from sqlalchemy.dialects.postgresql import insert

from .config import ai_settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Gemini embedding client (singleton)
# ---------------------------------------------------------------------------

_embed_client: Optional[genai.Client] = None


def _get_embed_client() -> genai.Client:
    global _embed_client
    if _embed_client is None:
        if not ai_settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Please set it in backend/.env")
        _embed_client = genai.Client(api_key=ai_settings.GEMINI_API_KEY)
    return _embed_client


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts using Gemini text-embedding-004.

    Batches automatically — Gemini supports up to 2048 texts per call but we
    chunk at 100 to stay well within limits and avoid timeouts.
    """
    client = _get_embed_client()
    all_embeddings: list[list[float]] = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.models.embed_content(
            model=ai_settings.GEMINI_EMBEDDING_MODEL,
            contents=batch,
        )
        all_embeddings.extend([e.values for e in response.embeddings])

    return all_embeddings


def generate_embedding(text_input: str) -> list[float]:
    """Generate a single embedding vector."""
    return generate_embeddings([text_input])[0]


def content_hash(content: str) -> str:
    """Stable MD5 hash used for idempotent upserts."""
    return hashlib.md5(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Store & query operations (sync — used by the chat pipeline)
# ---------------------------------------------------------------------------

def upsert_embeddings(
    engine,
    items: list[dict],
) -> int:
    """Upsert embedding rows into rag_embeddings.

    Each item must have: category, content, metadata, embedding, content_hash.
    Returns the number of rows upserted.
    """
    if not items:
        return 0

    from src.db.models import RagEmbedding

    with engine.begin() as conn:
        for item in items:
            metadata = item["metadata"]
            if isinstance(metadata, dict):
                metadata = json.dumps(metadata)
            stmt = insert(RagEmbedding).values(
                category=item["category"],
                content=item["content"],
                metadata_=metadata,
                embedding=item["embedding"],
                content_hash=item["content_hash"],
            ).on_conflict_do_update(
                index_elements=["content_hash"],
                set_={
                    "content": item["content"],
                    "metadata": metadata,
                    "embedding": item["embedding"],
                    "category": item["category"],
                },
            )
            conn.execute(stmt)

    return len(items)


def query_similar(
    engine,
    question_embedding: list[float],
    category: str | None = None,
    n_results: int = 5,
) -> list[dict]:
    """Find the most similar embeddings using cosine distance.

    Returns list of dicts with keys: content, metadata, distance.
    """
    # Build the query using raw SQL for pgvector operator support.
    # The embedding vector is inlined as a literal (it's a float array from the model,
    # not user input) to avoid placeholder conflicts with pgvector's :: cast syntax.
    embedding_literal = str(question_embedding)
    params: dict = {"limit": n_results}

    category_filter = ""
    if category:
        category_filter = "AND category = :category"
        params["category"] = category

    sql = f"""
        SELECT content, metadata, 1 - (embedding <=> '{embedding_literal}'::vector) AS similarity
        FROM rag_embeddings
        WHERE 1=1 {category_filter}
        ORDER BY embedding <=> '{embedding_literal}'::vector
        LIMIT :limit
    """

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [
        {
            "content": row[0],
            "metadata": json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {}),
            "similarity": float(row[2]),
        }
        for row in rows
    ]


def clear_category(engine, category: str) -> int:
    """Delete all embeddings in a category. Returns count deleted."""
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM rag_embeddings WHERE category = :category"),
            {"category": category},
        )
        return result.rowcount
