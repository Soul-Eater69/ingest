"""
parsers/base.py
===============
Abstract base class and shared data structures for all language parsers.

Design principles
-----------------
1. Dependency-free by default.
   All parsers use the standard library's `ast` module (Python) or
   regex-based heuristics (other languages).  No native extensions required.

2. Tree-sitter optional.
   If `tree-sitter` is installed, parsers may use it for better accuracy.
   The code degrades gracefully to regex-based parsing if it's absent.

3. Pure functions.
   `parse()` is a pure function: same input always produces the same output,
   making it easy to test and cache.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..models.chunk import ChunkKind, Language


@dataclass
class ParsedSymbol:
    """
    A structural unit extracted from source code by a parser.

    This is the raw output of parsing, before chunking.  One ParsedSymbol
    typically maps to one CodeChunk, but large symbols may be further split.

    Attributes
    ----------
    kind         : Structural category (function, class, method, …).
    name         : Fully qualified name ("ClassName.method_name").
    start_line   : 1-based first line (inclusive).
    end_line     : 1-based last line (inclusive).
    text         : Raw source text of the symbol.
    parent_name  : Name of the enclosing symbol, if any ("ClassName").
    docstring    : Extracted leading docstring / comment block.
    decorators   : List of decorator / annotation strings.
    signature    : Function/method signature line (for display).
    children     : Nested symbols (e.g., methods inside a class).
    """
    kind:         ChunkKind
    name:         str
    start_line:   int
    end_line:     int
    text:         str
    parent_name:  Optional[str] = None
    docstring:    Optional[str] = None
    decorators:   list[str] = field(default_factory=list)
    signature:    Optional[str] = None
    children:     list["ParsedSymbol"] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    @property
    def token_count(self) -> int:
        """Approximate token count (characters ÷ 4)."""
        return max(1, len(self.text) // 4)

    @property
    def qualified_name(self) -> str:
        """Return 'ParentClass.method_name' or just 'name'."""
        if self.parent_name:
            return f"{self.parent_name}.{self.name}"
        return self.name


class BaseParser(ABC):
    """
    Abstract base class for all language-specific parsers.

    Subclass and implement `parse()` to add support for a new language.

    The parse() method should:
      - NOT raise exceptions – return an empty list on parse failure
      - Be deterministic and side-effect free
      - Handle malformed / partial source gracefully
    """

    language: Language = Language.UNKNOWN

    @abstractmethod
    def parse(self, source: str, rel_path: str) -> list[ParsedSymbol]:
        """
        Parse `source` and return a list of top-level symbols.

        Parameters
        ----------
        source:    Full source text of the file.
        rel_path:  Relative path (used for error messages).

        Returns
        -------
        List of ParsedSymbol, one per extracted structural unit.
        Empty list on failure (do not raise).
        """
        ...

    def extract_imports(self, source: str) -> Optional[ParsedSymbol]:
        """
        Extract the import/require block at the top of a file.

        Optional – parsers may override this.  Returns a ParsedSymbol of
        kind=IMPORT or None if no imports are detected.
        """
        return None
