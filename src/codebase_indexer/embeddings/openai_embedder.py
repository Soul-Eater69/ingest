"""
embeddings/openai_embedder.py
==============================
OpenAI Embeddings API adapter.

API details
-----------
  Endpoint:  POST https://api.openai.com/v1/embeddings
  Models:    text-embedding-3-small  (1536 dims, cheapest)
             text-embedding-3-large  (3072 dims)
             text-embedding-ada-002  (1536 dims, legacy)
  Rate limit: 1,000,000 tokens/min (tier 1)
  Pricing:    $0.02 / 1M tokens (3-small as of 2024)

Batching
--------
We chunk the input list into batches of `batch_size` (default 512) texts
before calling the API.  The OpenAI API allows up to 2048 inputs per call
but smaller batches reduce the impact of a single failure.

Error handling
--------------
  RateLimitError  → exponential backoff with jitter, up to 5 retries
  APIError        → raise immediately (don't retry on 4xx)
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Optional

from ..config import settings
from ..utils.logging import get_logger
from .base import BaseEmbedder

logger = get_logger(__name__)


class OpenAIEmbedder(BaseEmbedder):
    """Embed text using the OpenAI Embeddings API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        self._api_key   = api_key   or settings.openai_api_key
        self._model     = model     or settings.openai_embed_model
        self._batch_size = batch_size or settings.openai_embed_batch_size
        self._client: object | None = None  # lazy init

    @property
    def dimensions(self) -> int:
        _DIM_MAP = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return _DIM_MAP.get(self._model, 1536)

    @property
    def model_name(self) -> str:
        return f"openai/{self._model}"

    def _get_client(self) -> object:
        if self._client is None:
            try:
                import openai  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "openai package not installed. "
                    "Install with: pip install openai"
                )
            self._client = openai.AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        client = self._get_client()
        vectors: list[list[float]] = []

        # Process in batches
        batches = [
            texts[i:i + self._batch_size]
            for i in range(0, len(texts), self._batch_size)
        ]

        for batch in batches:
            batch_vectors = await self._embed_with_retry(client, batch)
            vectors.extend(batch_vectors)

        return vectors

    async def _embed_with_retry(
        self,
        client: object,
        texts: list[str],
        max_retries: int = 5,
    ) -> list[list[float]]:
        """Call the API with exponential-backoff retry on rate limit errors."""
        try:
            import openai  # type: ignore[import]
        except ImportError:
            raise

        for attempt in range(max_retries):
            try:
                response = await client.embeddings.create(  # type: ignore[attr-defined]
                    model=self._model,
                    input=texts,
                )
                return [item.embedding for item in sorted(
                    response.data, key=lambda x: x.index
                )]

            except openai.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                delay = (2 ** attempt) + random.uniform(0, 1)
                logger.warning("rate limited, backing off", extra={
                    "attempt": attempt + 1, "delay": round(delay, 2)
                })
                await asyncio.sleep(delay)

        return []  # unreachable
