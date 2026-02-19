"""
retrieval/semantic.py
======================
Semantic (dense) retrieval using cosine similarity on embedding vectors.

Pipeline
--------
  1. Embed the query text using the configured embedder.
  2. Run ANN search in the vector store to get the top-K chunk IDs + scores.
  3. Fetch full chunk metadata from the metadata store.
  4. Return ranked list of (chunk, score) pairs.

Score normalisation
-------------------
Vector store distances/similarities are already in [0, 1] for cosine.
We pass them through unchanged.
"""

from __future__ import annotations

from ..config import settings
from ..embeddings.base import BaseEmbedder
from ..models.chunk import CodeChunk
from ..models.search import SearchQuery
from ..storage.metadata.base import BaseMetadataStore
from ..storage.vector.base import BaseVectorStore
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SemanticRetriever:
    def __init__(
        self,
        embedder:        BaseEmbedder,
        vector_store:    BaseVectorStore,
        metadata_store:  BaseMetadataStore,
    ) -> None:
        self._embedder       = embedder
        self._vector_store   = vector_store
        self._metadata_store = metadata_store

    async def retrieve(
        self,
        query: SearchQuery,
        top_k: int | None = None,
    ) -> list[tuple[CodeChunk, float]]:
        """
        Embed query and return top_k chunks with cosine similarity scores.

        Returns list of (chunk, score) sorted by score descending.
        """
        k = top_k or settings.retrieval_top_k

        # 1. Embed the query
        query_vector = await self._embedder.embed_one(query.text)

        # 2. Build metadata filter for the vector store
        where = self._build_where(query)

        # 3. Search vector store
        vector_results = await self._vector_store.search(
            query_vector=query_vector,
            top_k=k,
            where=where or None,
        )

        if not vector_results:
            return []

        # 4. Fetch chunk metadata
        chunk_ids = [r.chunk_id for r in vector_results]
        chunks    = await self._metadata_store.get_chunks_by_ids(chunk_ids)
        chunk_map = {c.chunk_id: c for c in chunks}

        # 5. Apply min_score filter and return
        results: list[tuple[CodeChunk, float]] = []
        for vr in vector_results:
            chunk = chunk_map.get(vr.chunk_id)
            if chunk and vr.score >= query.min_score:
                results.append((chunk, vr.score))

        return results

    def _build_where(self, query: SearchQuery) -> dict:
        """Convert SearchQuery filters to a flat metadata filter dict."""
        where: dict = {}
        if query.filter_language:
            where["language"] = query.filter_language.value
        # Note: ChromaDB / Qdrant where dicts only support flat equality filters
        # at this level.  Range queries and OR conditions require backend-specific
        # filter objects (not implemented here for backend-agnosticism).
        return where
