"""
chunking/base.py
================
Abstract base class for all chunkers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.chunk import CodeChunk
from ..models.document import SourceFile
from ..parsers.base import ParsedSymbol


class BaseChunker(ABC):
    """
    Transform (SourceFile, ParsedSymbols) → list[CodeChunk].

    Subclasses implement the `chunk()` method.
    """

    @abstractmethod
    def chunk(
        self,
        source: SourceFile,
        symbols: list[ParsedSymbol],
    ) -> list[CodeChunk]:
        """
        Produce chunks from a source file and its parsed symbols.

        Parameters
        ----------
        source:  The SourceFile with content loaded.
        symbols: List of ParsedSymbol from the parser stage.

        Returns
        -------
        List of CodeChunk objects ready for embedding.
        """
        ...
