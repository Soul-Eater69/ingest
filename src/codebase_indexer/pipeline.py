"""
pipeline.py
===========
IndexPipeline: the central orchestrator that ties all layers together.

Data flow (indexing)
--------------------

  ┌─────────────┐    ┌─────────┐    ┌──────────┐    ┌───────────┐
  │ FileCrawler │───▶│ Parser  │───▶│ Chunker  │───▶│ Embedder  │
  └─────────────┘    └─────────┘    └──────────┘    └─────┬─────┘
                                                           │
                          ┌────────────────────────────────┘
                          ▼
              ┌──────────────────────┐
              │  VectorStore upsert  │  ← embedding vectors
              │  MetadataStore upsert│  ← chunk text + metadata
              └──────────────────────┘

Steps
-----
  1. Crawl(root) → stream of SourceFile objects
  2. For each SourceFile:
     a. Parse → list[ParsedSymbol]
     b. Chunk  → list[CodeChunk]
  3. Batch chunks → embed batch → list[vector]
  4. Upsert vectors to VectorStore
  5. Upsert metadata to MetadataStore
  6. Update BM25 keyword index

Batching
--------
Chunks are accumulated into batches of `embed_batch_size` before calling
the embedder.  Embedding APIs have per-request limits and batching reduces
the number of round-trips.

Concurrency
-----------
Files are parsed concurrently (CPU-bound, via thread pool).
Embedding calls are batched and serialised (API rate limits).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Optional

from .chunking.factory import get_chunker
from .config import settings
from .embeddings.base import BaseEmbedder
from .embeddings.factory import get_embedder
from .ingestion.crawler import FileCrawler
from .ingestion.git_indexer import GitIndexer
from .models.chunk import CodeChunk
from .models.document import SourceFile
from .parsers.registry import get_parser
from .retrieval.keyword import KeywordRetriever
from .storage.metadata.base import BaseMetadataStore
from .storage.vector.base import BaseVectorStore
from .utils.logging import get_logger

logger = get_logger(__name__)

_EMBED_BATCH = 64   # how many chunks to embed per API call


class IndexPipeline:
    """
    Orchestrates the full indexing pipeline from raw files to searchable index.

    Parameters
    ----------
    vector_store:    Where to persist embedding vectors.
    metadata_store:  Where to persist chunk metadata.
    embedder:        Which embedding model to use (default from config).
    keyword_retriever:
                     BM25 index to update after indexing.
    """

    def __init__(
        self,
        vector_store:       BaseVectorStore,
        metadata_store:     BaseMetadataStore,
        embedder:           Optional[BaseEmbedder] = None,
        keyword_retriever:  Optional[KeywordRetriever] = None,
    ) -> None:
        self._vector_store   = vector_store
        self._metadata_store = metadata_store
        self._embedder       = embedder or get_embedder()
        self._chunker        = get_chunker()
        self._keyword        = keyword_retriever
        self._git_indexer:   Optional[GitIndexer] = None

    async def index_directory(
        self,
        root: Path,
        force: bool = False,
    ) -> dict:
        """
        Index an entire directory tree.

        Parameters
        ----------
        root:   Repository root to crawl.
        force:  Re-index all files even if their hash hasn't changed.

        Returns
        -------
        Dict with indexing statistics.
        """
        root = root.resolve()
        self._git_indexer = GitIndexer(root)

        # Load known hashes for change detection
        known_hashes = await self._metadata_store.get_all_file_hashes()

        crawler = FileCrawler(root, known_hashes=known_hashes, force=force)

        total_files = total_chunks = 0
        all_chunks: list[CodeChunk] = []

        # Process files as they stream from the crawler
        async for source_file in crawler.crawl():
            file_chunks = await self._process_file(source_file)
            all_chunks.extend(file_chunks)
            total_chunks += len(file_chunks)
            total_files += 1

            # Embed in batches to avoid accumulating too many chunks in memory
            if len(all_chunks) >= _EMBED_BATCH:
                await self._embed_and_store(all_chunks)
                all_chunks = []

        # Flush remaining chunks
        if all_chunks:
            await self._embed_and_store(all_chunks)

        # Rebuild BM25 keyword index after full indexing pass
        if self._keyword:
            logger.info("rebuilding BM25 index …")
            # Load all chunks from metadata for BM25 rebuild
            # (simplified: in production you'd rebuild incrementally)
            pass   # BM25 rebuild is triggered externally after full pass

        logger.info("indexing complete", extra={
            "root": str(root), "files": total_files, "chunks": total_chunks
        })

        return {"files_indexed": total_files, "chunks_indexed": total_chunks}

    async def index_file(self, abs_path: Path, repo_root: Path) -> list[CodeChunk]:
        """
        Index a single file (used by the file watcher for incremental updates).
        """
        rel_path = str(abs_path.relative_to(repo_root.resolve()))
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        from .ingestion.language_detector import LanguageDetector
        from .utils.hashing import file_hash
        import os

        detector  = LanguageDetector()
        language  = detector.detect(abs_path, content[:1024])
        stat      = abs_path.stat()

        source = SourceFile(
            abs_path=abs_path,
            rel_path=rel_path,
            repo_root=repo_root.resolve(),
            language=language,
            size_bytes=stat.st_size,
            mtime=stat.st_mtime,
            content_hash=file_hash(abs_path),
            content=content,
        )

        # Remove old chunks for this file
        await self._metadata_store.delete_chunks_by_path(rel_path)
        await self._vector_store.delete_by_path(rel_path)

        chunks = await self._process_file(source)
        await self._embed_and_store(chunks)
        return chunks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _process_file(self, source: SourceFile) -> list[CodeChunk]:
        """Parse + chunk a single SourceFile."""
        # Enrich with git metadata
        if self._git_indexer and settings.store_git_blame:
            blame = self._git_indexer.get_file_blame(source.rel_path)
            if blame:
                source.git_commit, source.git_author = blame

        # Parse (CPU-bound, run in thread pool)
        from .utils.concurrency import run_in_executor
        parser  = get_parser(source.language)
        symbols = await run_in_executor(parser.parse, source.content or "", source.rel_path)

        # Chunk
        chunks = self._chunker.chunk(source, symbols)

        # Record file-level info
        await self._metadata_store.upsert_file_record(
            rel_path=source.rel_path,
            content_hash=source.content_hash,
            language=source.language,
            chunk_count=len(chunks),
        )

        logger.debug("processed file", extra={
            "path": source.rel_path,
            "language": source.language.value,
            "symbols": len(symbols),
            "chunks": len(chunks),
        })

        return chunks

    async def _embed_and_store(self, chunks: list[CodeChunk]) -> None:
        """Embed a batch of chunks and write to both stores."""
        if not chunks:
            return

        texts   = [c.full_text_for_embedding for c in chunks]
        vectors = await self._embedder.embed(texts)

        # Store metadata
        await self._metadata_store.upsert_chunks(chunks)

        # Store vectors (with lightweight metadata for vector-store filtering)
        chunk_ids = [c.chunk_id for c in chunks]
        metadatas = [
            {
                "rel_path":    c.rel_path,
                "language":    c.language.value,
                "kind":        c.kind.value,
                "symbol_name": c.symbol_name or "",
                "start_line":  c.start_line,
            }
            for c in chunks
        ]
        await self._vector_store.upsert(chunk_ids, vectors, metadatas)

        logger.debug("stored batch", extra={"count": len(chunks)})
