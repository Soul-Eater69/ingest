"""
embeddings/base.py
==================
Abstract base class for embedding providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """
    Converts a list of text strings into a list of float vectors.

    All embedders must be thread-safe (they may be called from a thread pool).
    """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """The number of dimensions in each output vector."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier (for logging / metadata)."""
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts.

        Parameters
        ----------
        texts: List of strings to embed.  May be empty.

        Returns
        -------
        List of float vectors, one per input text, in the same order.
        Vectors are L2-normalised (unit length) for cosine similarity.
        """
        ...

    async def embed_one(self, text: str) -> list[float]:
        """Convenience method to embed a single text string."""
        results = await self.embed([text])
        return results[0]
