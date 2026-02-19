"""
embeddings/cache.py
===================
Disk-based embedding cache using numpy .npy files.

How it works
------------
  key   = SHA-256(text + model_name)[:16]   (16 hex chars = 64-bit key)
  value = float32 numpy array stored as <cache_dir>/<key>.npy

On embed():
  1. For each text, compute cache key.
  2. If <cache_dir>/<key>.npy exists, load the vector from disk.
  3. Collect uncached texts and call the wrapped embedder.
  4. Store new vectors to disk.
  5. Return all vectors in original order.

Why .npy files instead of SQLite or a KV store?
  - Zero dependencies (numpy is already needed for ML work)
  - Fast random access (mmap-able)
  - Simple to inspect and delete individual entries

Cache invalidation
------------------
Cache entries never expire.  To clear the cache, delete the cache directory
or run `cidx cache clear`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.logging import get_logger
from .base import BaseEmbedder

logger = get_logger(__name__)


def _cache_key(text: str, model: str) -> str:
    """Deterministic 16-char key for (text, model) pair."""
    raw = f"{model}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class EmbeddingCache(BaseEmbedder):
    """
    Transparent caching wrapper for any BaseEmbedder.

    Usage
    -----
        base = SentenceTransformerEmbedder()
        embedder = EmbeddingCache(base)
        vectors = await embedder.embed(texts)
    """

    def __init__(
        self,
        wrapped: BaseEmbedder,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self._wrapped = wrapped
        self._cache_dir = (cache_dir or settings.embed_cache_dir).resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    @property
    def dimensions(self) -> int:
        return self._wrapped.dimensions

    @property
    def model_name(self) -> str:
        return self._wrapped.model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            import numpy as np  # type: ignore[import]
        except ImportError:
            # numpy not available – fall through to uncached embedding
            return await self._wrapped.embed(texts)

        model = self.model_name
        results: list[Optional[list[float]]] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts:   list[str] = []

        # Pass 1: load from cache
        for i, text in enumerate(texts):
            key  = _cache_key(text, model)
            path = self._cache_dir / f"{key}.npy"
            if path.exists():
                results[i] = np.load(str(path)).tolist()
                self._hits += 1
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)
                self._misses += 1

        # Pass 2: embed uncached texts
        if uncached_texts:
            new_vectors = await self._wrapped.embed(uncached_texts)
            for idx, vector in zip(uncached_indices, new_vectors):
                results[idx] = vector
                # Persist to disk
                key  = _cache_key(texts[idx], model)
                path = self._cache_dir / f"{key}.npy"
                np.save(str(path), np.array(vector, dtype=np.float32))

        logger.debug("embedding cache stats", extra={
            "hits": self._hits, "misses": self._misses,
            "hit_rate": f"{100 * self._hits / max(1, self._hits + self._misses):.1f}%"
        })

        return results  # type: ignore[return-value]

    def cache_stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits":     self._hits,
            "misses":   self._misses,
            "hit_rate": self._hits / max(1, total),
            "cache_dir": str(self._cache_dir),
        }
