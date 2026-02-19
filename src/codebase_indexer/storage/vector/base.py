"""
storage/vector/base.py
======================
Abstract base class for vector store backends.

A vector store provides:
  upsert()  – Store vectors with their chunk IDs and a small metadata dict.
  search()  – Find the top-k most similar vectors to a query vector.
  delete()  – Remove vectors by chunk ID or by file path.
  count()   – Return the total number of stored vectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VectorSearchResult:
    """A single result from a vector similarity search."""
    chunk_id: str
    score: float          # cosine similarity (0–1, higher is better)
    metadata: dict        # lightweight metadata stored alongside the vector


class BaseVectorStore(ABC):
    """Abstract interface for all vector store backends."""

    @abstractmethod
    async def upsert(
        self,
        chunk_ids:  list[str],
        vectors:    list[list[float]],
        metadatas:  list[dict],
    ) -> None:
        """
        Insert or update vectors in the store.

        Parameters
        ----------
        chunk_ids:  Stable IDs for each vector.
        vectors:    Float vectors (must all have the same dimension).
        metadatas:  Per-vector metadata dicts (must not contain nested objects
                    – vector stores typically only accept flat dicts).
        """
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        where: dict | None = None,
    ) -> list[VectorSearchResult]:
        """
        Return the top_k most similar stored vectors.

        Parameters
        ----------
        query_vector: Dense query vector (same dimension as stored vectors).
        top_k:        Number of results to return.
        where:        Optional metadata filter dict (syntax varies by backend).

        Returns
        -------
        List of VectorSearchResult sorted by score descending.
        """
        ...

    @abstractmethod
    async def delete_by_ids(self, chunk_ids: list[str]) -> None:
        """Delete specific vectors by chunk ID."""
        ...

    @abstractmethod
    async def delete_by_path(self, rel_path: str) -> None:
        """Delete all vectors for a given file path."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return total number of vectors in the store."""
        ...
