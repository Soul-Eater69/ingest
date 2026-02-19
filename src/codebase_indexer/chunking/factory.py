"""chunking/factory.py – select the right chunker based on config."""

from ..config import ChunkStrategy, settings
from .base import BaseChunker
from .semantic_chunker import SemanticChunker
from .sliding_window import SlidingWindowChunker
from .hybrid_chunker import HybridChunker

_CHUNKERS: dict[ChunkStrategy, BaseChunker] = {
    ChunkStrategy.SEMANTIC:      SemanticChunker(),
    ChunkStrategy.SLIDING_WINDOW: SlidingWindowChunker(),
    ChunkStrategy.HYBRID:        HybridChunker(),
}


def get_chunker(strategy: ChunkStrategy | None = None) -> BaseChunker:
    """Return the configured chunker (defaults to settings.chunk_strategy)."""
    return _CHUNKERS[strategy or settings.chunk_strategy]
