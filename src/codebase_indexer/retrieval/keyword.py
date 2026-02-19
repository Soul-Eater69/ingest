"""
retrieval/keyword.py
====================
BM25 keyword retrieval.

BM25 (Best Match 25) is the industry-standard term-frequency ranking function.
It scores documents based on how often query terms appear in them, normalised
by document length.  It excels at exact token matching (identifiers, class names,
error messages) where dense embeddings can struggle.

Implementation
--------------
We use the `rank_bm25` Python library which implements BM25Okapi.
The index is built over the tokenised chunk texts at index time and
persisted to disk as a pickle file.

Tokenisation
------------
We tokenise source code by splitting on non-word characters (spaces,
underscores, camelCase boundaries, dots, parens, etc.) to ensure that
identifiers like "parseCSVFile" are tokenised as ["parse", "CSV", "File"].

Index persistence
-----------------
Building BM25 from scratch over 100k chunks takes ~5 seconds.
We pickle the BM25 object + the list of chunk IDs so subsequent
server starts can load the index from disk instantly.
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models.chunk import CodeChunk
from ..models.search import SearchQuery
from ..storage.metadata.base import BaseMetadataStore
from ..utils.concurrency import run_in_executor
from ..utils.logging import get_logger

logger = get_logger(__name__)

_SPLIT = re.compile(r"[^a-zA-Z0-9]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenize(text: str) -> list[str]:
    """Split source code into lowercase tokens for BM25."""
    tokens = [t.lower() for t in _SPLIT.split(text) if len(t) > 1]
    return tokens


class KeywordRetriever:
    """BM25-based keyword search over indexed chunks."""

    def __init__(
        self,
        metadata_store: BaseMetadataStore,
        index_path: Optional[Path] = None,
    ) -> None:
        self._metadata = metadata_store
        self._index_path = index_path or settings.bm25_index_path
        self._bm25: object | None = None
        self._chunk_ids: list[str] = []

    async def build_index(self, chunks: list[CodeChunk]) -> None:
        """
        Build (or rebuild) the BM25 index from a list of chunks.

        Call this after the embedding + storage stage so all chunks are
        available.  For incremental updates, call after each file is indexed.
        """
        def _build() -> None:
            try:
                from rank_bm25 import BM25Okapi  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "rank-bm25 not installed. "
                    "Install with: pip install rank-bm25"
                )
            tokenised = [_tokenize(c.full_text_for_embedding) for c in chunks]
            self._bm25      = BM25Okapi(tokenised)
            self._chunk_ids = [c.chunk_id for c in chunks]

            # Persist to disk
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_path, "wb") as f:
                pickle.dump((self._bm25, self._chunk_ids), f)

            logger.info("BM25 index built", extra={
                "chunks": len(chunks), "path": str(self._index_path)
            })

        await run_in_executor(_build)

    async def load_index(self) -> bool:
        """Load index from disk. Returns True on success."""
        if not self._index_path.exists():
            return False

        def _load() -> None:
            with open(self._index_path, "rb") as f:
                self._bm25, self._chunk_ids = pickle.load(f)

        await run_in_executor(_load)
        logger.info("BM25 index loaded", extra={"path": str(self._index_path)})
        return True

    async def retrieve(
        self,
        query: SearchQuery,
        top_k: int | None = None,
    ) -> list[tuple[CodeChunk, float]]:
        """Return chunks with BM25 scores for the given query."""
        if self._bm25 is None:
            loaded = await self.load_index()
            if not loaded:
                logger.warning("BM25 index not available, skipping keyword search")
                return []

        k = top_k or settings.retrieval_top_k

        def _score() -> list[tuple[str, float]]:
            tokens = _tokenize(query.text)
            scores = self._bm25.get_scores(tokens)  # type: ignore[attr-defined]
            # Get top-k indices
            import numpy as np  # type: ignore[import]
            top_indices = np.argsort(scores)[::-1][:k]
            return [
                (self._chunk_ids[i], float(scores[i]))
                for i in top_indices
                if scores[i] > 0
            ]

        try:
            id_score_pairs = await run_in_executor(_score)
        except ImportError:
            logger.warning("numpy not available for BM25 ranking")
            return []

        if not id_score_pairs:
            return []

        # Normalise BM25 scores to [0, 1] by dividing by max score
        max_score = max(s for _, s in id_score_pairs) or 1.0
        normalised = [(cid, s / max_score) for cid, s in id_score_pairs]

        # Fetch chunk objects
        chunk_ids = [cid for cid, _ in normalised]
        chunks    = await self._metadata.get_chunks_by_ids(chunk_ids)
        chunk_map = {c.chunk_id: c for c in chunks}

        results: list[tuple[CodeChunk, float]] = []
        for cid, score in normalised:
            chunk = chunk_map.get(cid)
            if chunk:
                results.append((chunk, score))

        return results
