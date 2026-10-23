"""ORM models.

Dataset tables are generated from dataset packages (``src/datasets/ddl.py``) and
have no ORM classes.  Only the embedding table of the first chat pipeline is
mapped here, until the intelligence pipeline replaces it.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

from .base import Base


class RagEmbedding(Base):
    __tablename__ = "rag_embeddings"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    category = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default="{}")
    embedding = Column(Vector(3072), nullable=False)
    content_hash = Column(String(32), nullable=False, unique=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
