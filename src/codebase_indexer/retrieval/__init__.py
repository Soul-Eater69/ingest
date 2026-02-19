"""
retrieval
=========
Query the index and return ranked code chunks.

Three retrieval strategies:

  SemanticRetriever   Embeds the query and finds nearest neighbours in the
                      vector store.  Best for conceptual / semantic queries
                      like "function that parses CSV" or "error handler".

  KeywordRetriever    BM25 term-frequency search over the raw chunk text.
                      Best for exact token queries like class names, function
                      signatures, error messages, or uncommon identifiers.

  HybridRetriever     Combines both signals using Reciprocal Rank Fusion (RRF).
                      Recommended default – outperforms either alone.

After retrieval, an optional Reranker re-scores results using a cross-encoder
model for higher precision at the cost of additional latency.
"""

from .semantic import SemanticRetriever
from .keyword import KeywordRetriever
from .hybrid import HybridRetriever
from .reranker import CrossEncoderReranker
from .engine import RetrievalEngine

__all__ = [
    "SemanticRetriever", "KeywordRetriever", "HybridRetriever",
    "CrossEncoderReranker", "RetrievalEngine",
]
