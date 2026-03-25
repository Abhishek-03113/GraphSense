"""ChromaDB-based vector store for schema embeddings and SQL retrieval."""

from typing import Optional

import chromadb
import structlog

from .config import ai_settings

logger = structlog.get_logger(__name__)

_client: Optional[chromadb.ClientAPI] = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=ai_settings.CHROMA_PERSIST_DIR)
        logger.info("chroma.init", path=ai_settings.CHROMA_PERSIST_DIR)
    return _client


def get_ddl_collection() -> chromadb.Collection:
    return get_chroma_client().get_or_create_collection(
        name="ddl_schemas",
        metadata={"hnsw:space": "cosine"},
    )


def get_docs_collection() -> chromadb.Collection:
    return get_chroma_client().get_or_create_collection(
        name="documentation",
        metadata={"hnsw:space": "cosine"},
    )


def get_sql_collection() -> chromadb.Collection:
    return get_chroma_client().get_or_create_collection(
        name="sql_pairs",
        metadata={"hnsw:space": "cosine"},
    )
