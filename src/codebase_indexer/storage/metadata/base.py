"""
storage/metadata/base.py
========================
Abstract base class for metadata stores.

The metadata store is responsible for:
  1. Persisting full CodeChunk objects (minus embedding vectors).
  2. Recording file-level information (path, hash, last indexed time).
  3. Supporting SQL-style filtered queries (language, kind, path prefix, etc.)
  4. Providing statistics for the `cidx info` command.

Why keep metadata separate from the vector store?
-------------------------------------------------
Vector stores optimise for nearest-neighbour search on float arrays.
They support flat metadata dicts but NOT SQL-style joins, aggregations,
or sub-queries.  Keeping metadata in SQLite (or PostgreSQL) lets us:
  - Filter candidates before ANN search (cheaper)
  - Run complex analytical queries ("show me all functions changed by Alice")
  - Inspect the index without a vector store running
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ...models.chunk import CodeChunk, Language, ChunkKind
from ...models.document import IndexStats


class BaseMetadataStore(ABC):
    """Abstract interface for all metadata store backends."""

    @abstractmethod
    async def upsert_chunks(self, chunks: list[CodeChunk]) -> None:
        """Insert or update chunk metadata records."""
        ...

    @abstractmethod
    async def get_chunk(self, chunk_id: str) -> Optional[CodeChunk]:
        """Fetch a single chunk by ID."""
        ...

    @abstractmethod
    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[CodeChunk]:
        """Fetch multiple chunks by their IDs."""
        ...

    @abstractmethod
    async def delete_chunks_by_path(self, rel_path: str) -> int:
        """Delete all chunks for a file. Returns number of deleted rows."""
        ...

    @abstractmethod
    async def get_file_hash(self, rel_path: str) -> Optional[str]:
        """Return the stored content hash for a file, or None if not indexed."""
        ...

    @abstractmethod
    async def get_all_file_hashes(self) -> dict[str, str]:
        """Return {rel_path: content_hash} for all indexed files."""
        ...

    @abstractmethod
    async def upsert_file_record(
        self,
        rel_path:     str,
        content_hash: str,
        language:     Language,
        chunk_count:  int,
    ) -> None:
        """Record or update file-level indexing info."""
        ...

    @abstractmethod
    async def get_stats(self) -> IndexStats:
        """Compute and return aggregate index statistics."""
        ...
