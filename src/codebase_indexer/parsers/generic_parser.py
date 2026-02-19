"""
parsers/generic_parser.py
=========================
Fallback line-based parser for languages without a dedicated parser.

Strategy:
  Treat the entire file as a single MODULE chunk.  This is the safest
  approach for languages we don't have a dedicated parser for (HTML, SQL,
  YAML, Markdown, etc.) – the content is still indexed and searchable,
  just without symbol-level granularity.

For large files this produces one huge chunk which will be further split
by the chunking layer (sliding window strategy).
"""

from __future__ import annotations

from ..models.chunk import ChunkKind, Language
from .base import BaseParser, ParsedSymbol


class GenericParser(BaseParser):
    """
    Wraps the entire file content in a single MODULE-kind ParsedSymbol.

    Used as a fallback for YAML, JSON, SQL, HTML, Markdown, etc.
    """

    language = Language.UNKNOWN

    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        if not source.strip():
            return []

        line_count = source.count("\n") + 1
        return [ParsedSymbol(
            kind=ChunkKind.MODULE,
            name=rel_path,
            start_line=1,
            end_line=line_count,
            text=source,
        )]
