"""
chunking
========
Converts ParsedSymbol objects into CodeChunk objects ready for embedding.

Three strategies are available:

  SemanticChunker     One chunk per symbol (function/class/etc).
                      Best retrieval precision – chunks have clear semantics.
                      Problem: very large symbols become oversized chunks.

  SlidingWindowChunker  Fixed-size overlapping windows regardless of
                        symbol boundaries.
                        Guarantees bounded chunk size.
                        Problem: chunks may split a function mid-body.

  HybridChunker       Semantic first: split on symbol boundaries.
                      For symbols larger than max_symbol_tokens, fall back
                      to sliding-window sub-chunking.
                      Best of both worlds – recommended default.
"""

from .base import BaseChunker
from .semantic_chunker import SemanticChunker
from .sliding_window import SlidingWindowChunker
from .hybrid_chunker import HybridChunker
from .factory import get_chunker

__all__ = [
    "BaseChunker", "SemanticChunker", "SlidingWindowChunker",
    "HybridChunker", "get_chunker",
]
