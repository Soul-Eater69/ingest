"""storage/factory.py – create the configured storage backends."""

from ..config import VectorBackend, settings
from .vector.base import BaseVectorStore
from .vector.chroma_store import ChromaVectorStore
from .vector.qdrant_store import QdrantVectorStore
from .metadata.base import BaseMetadataStore
from .metadata.sqlite_store import SQLiteMetadataStore

_vector_store: BaseVectorStore | None = None
_metadata_store: BaseMetadataStore | None = None


def get_vector_store() -> BaseVectorStore:
    """Return the singleton vector store instance."""
    global _vector_store
    if _vector_store is None:
        if settings.vector_backend == VectorBackend.QDRANT:
            _vector_store = QdrantVectorStore()
        else:
            _vector_store = ChromaVectorStore()
    return _vector_store


def get_metadata_store() -> BaseMetadataStore:
    """Return the singleton metadata store instance."""
    global _metadata_store
    if _metadata_store is None:
        _metadata_store = SQLiteMetadataStore()
    return _metadata_store
