"""
chunking/sliding_window.py
==========================
Sliding-window chunking: fixed-size overlapping text windows.

The window slides over the source file's lines with a configurable
step size (chunk_size - overlap).  Each window becomes one SLIDING chunk.

Why overlap?
------------
When a piece of relevant code falls near the boundary of a chunk, it might
be split across two chunks and neither chunk contains enough context for the
embedding model to match it confidently.  Overlapping ensures that every
line appears in at least two adjacent chunks, reducing boundary effects.

Chunk size unit: tokens (approximated as characters ÷ 4)
---------------------------------------------------------
We use character count ÷ 4 as a cheap approximation of sub-word token count.
This avoids the dependency on a tokenizer at chunking time.  The approximation
is accurate to ±20% for English text and typical source code.
"""

from __future__ import annotations

from ..config import settings
from ..models.chunk import CodeChunk, ChunkKind
from ..models.document import SourceFile
from ..parsers.base import ParsedSymbol
from .base import BaseChunker


class SlidingWindowChunker(BaseChunker):
    """
    Split source files into fixed-size overlapping windows.

    Parameters
    ----------
    chunk_tokens:   Target window size in approximate tokens.
    overlap_tokens: Overlap between adjacent windows in approximate tokens.
    """

    def __init__(
        self,
        chunk_tokens: int | None = None,
        overlap_tokens: int | None = None,
    ) -> None:
        self.chunk_chars   = (chunk_tokens   or settings.chunk_size)   * 4
        self.overlap_chars = (overlap_tokens or settings.chunk_overlap) * 4
        self.step_chars    = max(1, self.chunk_chars - self.overlap_chars)

    def chunk(
        self,
        source: SourceFile,
        symbols: list[ParsedSymbol],  # ignored by this chunker
    ) -> list[CodeChunk]:
        if not source.content:
            return []

        text   = source.content
        chunks: list[CodeChunk] = []
        start  = 0
        total_chars = len(text)

        while start < total_chars:
            end = min(start + self.chunk_chars, total_chars)
            window_text = text[start:end]

            # Count newlines to determine line range
            start_line = text[:start].count("\n") + 1
            end_line   = text[:end].count("\n") + 1

            chunks.append(CodeChunk(
                repo_root=str(source.repo_root),
                rel_path=source.rel_path,
                language=source.language,
                kind=ChunkKind.SLIDING,
                symbol_name=None,
                start_line=start_line,
                end_line=end_line,
                text=window_text,
                git_commit=source.git_commit,
                git_author=source.git_author,
            ))

            if end == total_chars:
                break
            start += self.step_chars

        return chunks
