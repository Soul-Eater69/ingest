"""
tests/codebase_indexer/test_chunking.py
=========================================
Unit tests for all chunking strategies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codebase_indexer.models.chunk import ChunkKind, Language
from codebase_indexer.models.document import SourceFile
from codebase_indexer.parsers.python_parser import PythonParser
from codebase_indexer.chunking.semantic_chunker import SemanticChunker
from codebase_indexer.chunking.sliding_window import SlidingWindowChunker
from codebase_indexer.chunking.hybrid_chunker import HybridChunker


PYTHON_SOURCE = '''\
def foo():
    """Foo function."""
    pass


class Bar:
    """Bar class."""
    def method_a(self):
        pass
    def method_b(self):
        pass
'''


def make_source(content: str, language: Language = Language.PYTHON) -> SourceFile:
    return SourceFile(
        abs_path=Path("/tmp/test.py"),
        rel_path="test.py",
        repo_root=Path("/tmp"),
        language=language,
        size_bytes=len(content),
        mtime=0.0,
        content=content,
    )


class TestSemanticChunker:
    def setup_method(self) -> None:
        self.parser  = PythonParser()
        self.chunker = SemanticChunker()

    def test_produces_function_chunk(self) -> None:
        source  = make_source(PYTHON_SOURCE)
        symbols = self.parser.parse(PYTHON_SOURCE, "test.py")
        chunks  = self.chunker.chunk(source, symbols)
        kinds   = {c.kind for c in chunks}
        assert ChunkKind.FUNCTION in kinds

    def test_class_methods_are_separate_chunks(self) -> None:
        source  = make_source(PYTHON_SOURCE)
        symbols = self.parser.parse(PYTHON_SOURCE, "test.py")
        chunks  = self.chunker.chunk(source, symbols)
        method_chunks = [c for c in chunks if c.kind == ChunkKind.METHOD]
        names = {c.symbol_name for c in method_chunks}
        assert "Bar.method_a" in names
        assert "Bar.method_b" in names

    def test_method_has_class_context(self) -> None:
        source  = make_source(PYTHON_SOURCE)
        symbols = self.parser.parse(PYTHON_SOURCE, "test.py")
        chunks  = self.chunker.chunk(source, symbols)
        method = next((c for c in chunks if "method_a" in (c.symbol_name or "")), None)
        assert method is not None
        assert "Bar" in method.context_before

    def test_no_symbols_produces_module_chunk(self) -> None:
        source  = make_source("x = 1\ny = 2\n")
        symbols = []
        chunks  = self.chunker.chunk(source, symbols)
        assert len(chunks) == 1
        assert chunks[0].kind == ChunkKind.MODULE

    def test_chunk_has_correct_rel_path(self) -> None:
        source  = make_source(PYTHON_SOURCE)
        symbols = self.parser.parse(PYTHON_SOURCE, "test.py")
        chunks  = self.chunker.chunk(source, symbols)
        for chunk in chunks:
            assert chunk.rel_path == "test.py"


class TestSlidingWindowChunker:
    def setup_method(self) -> None:
        # Small window for testing
        self.chunker = SlidingWindowChunker(chunk_tokens=10, overlap_tokens=2)

    def test_produces_multiple_chunks_for_long_file(self) -> None:
        content = ("x = 1\n" * 50)
        source  = make_source(content)
        chunks  = self.chunker.chunk(source, [])
        assert len(chunks) > 1

    def test_all_chunks_are_sliding_kind(self) -> None:
        source = make_source(PYTHON_SOURCE)
        chunks = self.chunker.chunk(source, [])
        for chunk in chunks:
            assert chunk.kind == ChunkKind.SLIDING

    def test_chunks_cover_entire_file(self) -> None:
        content = "line\n" * 30
        source  = make_source(content)
        chunks  = self.chunker.chunk(source, [])
        reconstructed = ""
        for chunk in chunks:
            reconstructed += chunk.text
        # Every character appears at least once
        for char in content:
            assert char in reconstructed


class TestHybridChunker:
    def setup_method(self) -> None:
        self.parser  = PythonParser()
        self.chunker = HybridChunker()

    def test_small_symbols_stay_as_single_chunk(self) -> None:
        source  = make_source(PYTHON_SOURCE)
        symbols = self.parser.parse(PYTHON_SOURCE, "test.py")
        chunks  = self.chunker.chunk(source, symbols)
        # All symbols in PYTHON_SOURCE are small, so none should be split
        sliding_chunks = [c for c in chunks if c.kind == ChunkKind.SLIDING
                         and c.extra.get("sub_part") is not None]
        assert len(sliding_chunks) == 0

    def test_large_symbol_gets_split(self) -> None:
        # Create a very long function (exceeds max_symbol_tokens)
        long_fn = "def long_func():\n" + ("    x = 1\n" * 400)
        source  = make_source(long_fn)
        symbols = self.parser.parse(long_fn, "big.py")
        chunks  = self.chunker.chunk(source, symbols)
        # Should produce multiple sub-chunks
        assert len(chunks) > 1
