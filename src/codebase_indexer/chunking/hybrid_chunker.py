"""
chunking/hybrid_chunker.py
==========================
Hybrid chunker: semantic first, sliding-window fallback for large symbols.

Algorithm
---------
1. Run SemanticChunker to produce symbol-level chunks.
2. For each chunk whose token_count > max_symbol_tokens:
   a. Replace it with sliding-window sub-chunks of the same text.
   b. Each sub-chunk inherits the symbol metadata (name, kind, etc.)
      so retrieval filters still work correctly.
3. Return the combined list.

This gives us the best of both worlds:
  - Small functions/methods → one chunk each (best precision)
  - Giant generated files or huge classes → bounded chunk sizes
"""

from __future__ import annotations

from ..config import settings
from ..models.chunk import CodeChunk, ChunkKind
from ..models.document import SourceFile
from ..parsers.base import ParsedSymbol
from .base import BaseChunker
from .semantic_chunker import SemanticChunker
from .sliding_window import SlidingWindowChunker


class HybridChunker(BaseChunker):
    """Semantic chunking with sliding-window fallback for oversized symbols."""

    def __init__(self) -> None:
        self._semantic  = SemanticChunker()
        self._slider    = SlidingWindowChunker()
        self._max_tokens = settings.max_symbol_tokens

    def chunk(
        self,
        source: SourceFile,
        symbols: list[ParsedSymbol],
    ) -> list[CodeChunk]:
        semantic_chunks = self._semantic.chunk(source, symbols)
        result: list[CodeChunk] = []

        for chunk in semantic_chunks:
            if chunk.token_count <= self._max_tokens:
                result.append(chunk)
            else:
                # Sub-chunk this oversized symbol
                sub_chunks = self._sub_chunk(chunk, source)
                result.extend(sub_chunks)

        return result

    def _sub_chunk(self, chunk: CodeChunk, source: SourceFile) -> list[CodeChunk]:
        """
        Split an oversized chunk into overlapping sub-windows.

        Each sub-window inherits the symbol metadata so that filters on
        symbol_name, kind, etc. still work correctly.
        """
        text        = chunk.text
        chunk_chars = settings.chunk_size   * 4
        overlap_chars = settings.chunk_overlap * 4
        step_chars  = max(1, chunk_chars - overlap_chars)

        sub_chunks: list[CodeChunk] = []
        start = 0
        total = len(text)
        part  = 0

        while start < total:
            end = min(start + chunk_chars, total)
            window = text[start:end]

            # Recalculate absolute line numbers
            abs_start_line = chunk.start_line + text[:start].count("\n")
            abs_end_line   = chunk.start_line + text[:end].count("\n")

            sub_chunks.append(CodeChunk(
                repo_root=chunk.repo_root,
                rel_path=chunk.rel_path,
                language=chunk.language,
                kind=ChunkKind.SLIDING,
                # Keep symbol name so filters still work
                symbol_name=chunk.symbol_name,
                start_line=abs_start_line,
                end_line=abs_end_line,
                text=window,
                context_before=chunk.context_before,
                docstring=chunk.docstring if part == 0 else None,
                git_commit=chunk.git_commit,
                git_author=chunk.git_author,
                extra={"sub_part": part, "parent_chunk_id": chunk.chunk_id},
            ))

            if end == total:
                break
            start += step_chars
            part  += 1

        return sub_chunks
