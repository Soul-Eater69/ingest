"""
storage/vector/qdrant_store.py
================================
Qdrant vector store adapter.

Qdrant overview
---------------
Qdrant is a production-grade vector database with:
  - HNSW indexing for sub-millisecond approximate nearest-neighbour search
  - Payload filtering (equivalent to ChromaDB's where dict)
  - gRPC and REST APIs
  - Distributed horizontal scaling

To run Qdrant locally:
    docker run -p 6333:6333 qdrant/qdrant

Payload filtering
-----------------
Qdrant filters use a different syntax than ChromaDB:

    from qdrant_client.models import Filter, FieldCondition, MatchValue
    flt = Filter(must=[FieldCondition(key="language", match=MatchValue(value="python"))])

For simplicity, this adapter accepts a flat dict and auto-converts it to
Qdrant filter objects.
"""

from __future__ import annotations

from typing import Optional

from ...config import settings
from ...utils.logging import get_logger
from .base import BaseVectorStore, VectorSearchResult

logger = get_logger(__name__)


class QdrantVectorStore(BaseVectorStore):
    """Qdrant-backed vector store (requires a running Qdrant server)."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection_name: Optional[str] = None,
        vector_size: int = 768,
    ) -> None:
        self._url        = url        or settings.qdrant_url
        self._api_key    = api_key    or settings.qdrant_api_key
        self._collection = collection_name or settings.qdrant_collection
        self._vector_size = vector_size
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient  # type: ignore[import]
                from qdrant_client.models import Distance, VectorParams  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "qdrant-client not installed. "
                    "Install with: pip install qdrant-client"
                )
            self._client = QdrantClient(url=self._url, api_key=self._api_key)
            # Create collection if it doesn't exist
            existing = [c.name for c in self._client.get_collections().collections]  # type: ignore[attr-defined]
            if self._collection not in existing:
                self._client.create_collection(  # type: ignore[attr-defined]
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("qdrant collection created", extra={
                    "collection": self._collection, "dims": self._vector_size
                })
        return self._client

    async def upsert(
        self,
        chunk_ids: list[str],
        vectors:   list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if not chunk_ids:
            return

        from qdrant_client.models import PointStruct  # type: ignore[import]
        client = self._get_client()

        # Qdrant requires integer IDs; we hash chunk_id to int
        points = [
            PointStruct(
                id=abs(hash(cid)) % (2**63),
                vector=vec,
                payload={**meta, "_chunk_id": cid},
            )
            for cid, vec, meta in zip(chunk_ids, vectors, metadatas)
        ]
        client.upsert(collection_name=self._collection, points=points)  # type: ignore[attr-defined]

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        where: Optional[dict] = None,
    ) -> list[VectorSearchResult]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore[import]
        client = self._get_client()

        qfilter = None
        if where:
            qfilter = Filter(must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in where.items()
            ])

        hits = client.search(  # type: ignore[attr-defined]
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        )

        return [
            VectorSearchResult(
                chunk_id=hit.payload.get("_chunk_id", str(hit.id)),
                score=round(hit.score, 6),
                metadata={k: v for k, v in hit.payload.items() if k != "_chunk_id"},
            )
            for hit in hits
        ]

    async def delete_by_ids(self, chunk_ids: list[str]) -> None:
        from qdrant_client.models import PointIdsList  # type: ignore[import]
        client = self._get_client()
        int_ids = [abs(hash(cid)) % (2**63) for cid in chunk_ids]
        client.delete(  # type: ignore[attr-defined]
            collection_name=self._collection,
            points_selector=PointIdsList(points=int_ids),
        )

    async def delete_by_path(self, rel_path: str) -> None:
        from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore[import]
        client = self._get_client()
        client.delete(  # type: ignore[attr-defined]
            collection_name=self._collection,
            points_selector=Filter(must=[
                FieldCondition(key="rel_path", match=MatchValue(value=rel_path))
            ]),
        )

    async def count(self) -> int:
        client = self._get_client()
        info = client.get_collection(self._collection)  # type: ignore[attr-defined]
        return info.points_count or 0
