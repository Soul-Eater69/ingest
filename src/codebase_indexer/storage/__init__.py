"""
storage
=======
Two storage subsystems:

  vector/    Vector store – persists embedding vectors and their chunk IDs.
             Supports cosine similarity search (ANN).
             Backends: ChromaDB (default), Qdrant

  metadata/  Metadata store – persists chunk metadata (file path, language,
             symbol name, line numbers, content hash, etc.) in a relational DB.
             Backends: SQLite (default), PostgreSQL (via SQLAlchemy)

Separation of concerns
----------------------
Storing vectors and metadata separately lets us:
  - Query metadata with SQL (fast filtering before vector search)
  - Swap vector backends without touching metadata (and vice versa)
  - Inspect / debug metadata with standard SQL tools
"""

from .vector.base import BaseVectorStore
from .vector.chroma_store import ChromaVectorStore
from .vector.qdrant_store import QdrantVectorStore
from .metadata.base import BaseMetadataStore
from .metadata.sqlite_store import SQLiteMetadataStore
from .factory import get_vector_store, get_metadata_store

__all__ = [
    "BaseVectorStore", "ChromaVectorStore", "QdrantVectorStore",
    "BaseMetadataStore", "SQLiteMetadataStore",
    "get_vector_store", "get_metadata_store",
]
