"""
embeddings
==========
Convert text chunks into dense vector representations.

Two providers are supported out of the box:

  OpenAIEmbedder           Uses the OpenAI Embeddings API.
                           Best quality, requires API key, costs money.
                           Default model: text-embedding-3-small (1536 dims).

  SentenceTransformerEmbedder
                           Uses a local HuggingFace model via sentence-transformers.
                           Free, private, works offline.
                           Default model: BAAI/bge-base-en-v1.5 (768 dims).

Both implement the same BaseEmbedder interface so they are interchangeable.

Caching
-------
EmbeddingCache wraps any embedder and persists computed embeddings to disk.
On subsequent runs, vectors are retrieved from disk instead of recomputed,
reducing both cost (for OpenAI) and time (for both providers).
"""

from .base import BaseEmbedder
from .openai_embedder import OpenAIEmbedder
from .sentence_transformer_embedder import SentenceTransformerEmbedder
from .cache import EmbeddingCache
from .factory import get_embedder

__all__ = [
    "BaseEmbedder", "OpenAIEmbedder", "SentenceTransformerEmbedder",
    "EmbeddingCache", "get_embedder",
]
