"""
chunking/semantic_chunker.py
=============================
Semantic chunking: one CodeChunk per ParsedSymbol.

For each symbol we:
  1. Use the symbol text as the primary chunk text.
  2. Prepend a context_before snippet (e.g., the class header if the
     symbol is a method) to help the embedding model understand context.
  3. Include the symbol's docstring in the metadata.

When a class has child methods, each method becomes its own chunk AND the
class itself (header + docstring only) also becomes a chunk.  This gives us:
  - One CLASS chunk for "what does this class do overall?"
  - One METHOD chunk per method for "how does this specific method work?"

This mirrors how developers think about code and produces much better
retrieval results than treating the entire class as a single chunk.
"""

from __future__ import annotations

from ..config import settings
from ..models.chunk import CodeChunk, ChunkKind
from ..models.document import SourceFile
from ..parsers.base import ParsedSymbol
from .base import BaseChunker


class SemanticChunker(BaseChunker):
    """One chunk per parsed symbol."""

    def chunk(
        self,
        source: SourceFile,
        symbols: list[ParsedSymbol],
    ) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        repo_root = str(source.repo_root)
        rel_path  = source.rel_path

        for sym in symbols:
            # For classes: emit the class header chunk, then recursively
            # emit each child method as its own chunk with context_before
            # set to the class header.
            if sym.kind == ChunkKind.CLASS and sym.children:
                # Class header chunk (declaration + docstring only)
                header_lines = self._class_header_lines(sym)
                class_header_text = "\n".join(
                    sym.text.splitlines()[:header_lines]
                )
                chunks.append(self._make_chunk(
                    repo_root, rel_path, source.language,
                    sym, override_text=class_header_text,
                ))

                # Method chunks
                for child in sym.children:
                    chunks.append(self._make_chunk(
                        repo_root, rel_path, source.language,
                        child,
                        context_before=class_header_text,
                    ))
            else:
                chunks.append(self._make_chunk(
                    repo_root, rel_path, source.language, sym
                ))

        # If no symbols found, emit a single MODULE chunk
        if not chunks and source.content:
            chunks.append(CodeChunk(
                repo_root=repo_root,
                rel_path=rel_path,
                language=source.language,
                kind=ChunkKind.MODULE,
                symbol_name=rel_path,
                start_line=1,
                end_line=source.content.count("\n") + 1,
                text=source.content,
                git_commit=source.git_commit,
                git_author=source.git_author,
            ))

        return chunks

    # ------------------------------------------------------------------
    def _make_chunk(
        self,
        repo_root: str,
        rel_path: str,
        language: object,
        sym: ParsedSymbol,
        context_before: str = "",
        override_text: str | None = None,
    ) -> CodeChunk:
        return CodeChunk(
            repo_root=repo_root,
            rel_path=rel_path,
            language=language,  # type: ignore[arg-type]
            kind=sym.kind,
            symbol_name=sym.qualified_name,
            start_line=sym.start_line,
            end_line=sym.end_line,
            text=override_text if override_text is not None else sym.text,
            context_before=context_before,
            docstring=sym.docstring,
        )

    @staticmethod
    def _class_header_lines(sym: ParsedSymbol) -> int:
        """
        Estimate the number of lines in the class header (declaration + docstring).
        We take up to 10 lines or until the first method body.
        """
        lines = sym.text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Heuristic: stop at first blank line after line 3
            if i > 3 and not stripped:
                return i
        return min(10, len(lines))
