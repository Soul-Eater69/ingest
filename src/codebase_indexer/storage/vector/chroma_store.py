"""
storage/vector/chroma_store.py
================================
ChromaDB vector store adapter.

ChromaDB overview
-----------------
ChromaDB is an open-source, embedded vector database.  It can run entirely
in-process (no server required) or as a separate server.

  - Persistent mode: data is stored to disk at `chroma_path`
  - In-memory mode:  data is lost on process exit (for testing)

Collections
-----------
Each "collection" in ChromaDB is a named namespace for vectors.
We use a single collection (default: "codebase") for all indexed chunks.

Metadata filtering
------------------
ChromaDB supports filtering on metadata fields using a `where` dict:

    where={"language": "python"}
    where={"$and": [{"language": "python"}, {"kind": "function"}]}

We pass through any where dict from the search API directly to ChromaDB.

Embedding function
------------------
ChromaDB has a built-in embedding function system.  We disable it by passing
embedding_function=None and providing pre-computed vectors ourselves.  This
gives us full control over the embedding model and batching.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...config import settings
from ...utils.logging import get_logger
from .base import BaseVectorStore, VectorSearchResult

logger = get_logger(__name__)


class ChromaVectorStore(BaseVectorStore):
    """ChromaDB-backed vector store (persistent on disk)."""

    def __init__(
        self,
        path: Optional[Path] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self._path = (path or settings.chroma_path).resolve()
        self._collection_name = collection_name or settings.chroma_collection
        self._client: object | None = None
        self._collection: object | None = None

    def _get_collection(self) -> object:
        if self._collection is None:
            try:
                import chromadb  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "chromadb not installed. "
                    "Install with: pip install chromadb"
                )
            self._path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._path))
            self._collection = self._client.get_or_create_collection(  # type: ignore[attr-defined]
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},  # use cosine distance
            )
            logger.info("chromadb collection ready", extra={
                "path": str(self._path),
                "collection": self._collection_name,
            })
        return self._collection

    async def upsert(
        self,
        chunk_ids: list[str],
        vectors:   list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if not chunk_ids:
            return
        col = self._get_collection()
        # ChromaDB requires string documents; use chunk_id as the document text
        col.upsert(  # type: ignore[attr-defined]
            ids=chunk_ids,
            embeddings=vectors,
            metadatas=metadatas,
            documents=chunk_ids,  # placeholder – actual text in metadata store
        )

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        where: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        col = self._get_collection()
        kwargs: dict = {
            "query_embeddings": [query_vector],
            "n_results": min(top_k, await self.count() or top_k),
            "include": ["metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)  # type: ignore[attr-defined]

        output: list[VectorSearchResult] = []
        ids       = results["ids"][0]
        distances = results["distances"][0]
        metas     = results["metadatas"][0]

        for chunk_id, dist, meta in zip(ids, distances, metas):
            # ChromaDB returns cosine DISTANCE (0=identical, 2=opposite)
            # Convert to similarity score (0–1)
            score = 1.0 - (dist / 2.0)
            output.append(VectorSearchResult(
                chunk_id=chunk_id,
                score=round(score, 6),
                metadata=meta or {},
            ))

        return sorted(output, key=lambda r: r.score, reverse=True)

    async def delete_by_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        col = self._get_collection()
        col.delete(ids=chunk_ids)  # type: ignore[attr-defined]

    async def delete_by_path(self, rel_path: str) -> None:
        col = self._get_collection()
        col.delete(where={"rel_path": rel_path})  # type: ignore[attr-defined]

    async def count(self) -> int:
        col = self._get_collection()
        return col.count()  # type: ignore[attr-defined]
