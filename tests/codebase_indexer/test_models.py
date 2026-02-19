"""
tests/codebase_indexer/test_models.py
=======================================
Unit tests for Pydantic data models.
"""

from __future__ import annotations

import pytest

from codebase_indexer.models.chunk import CodeChunk, ChunkKind, Language
from codebase_indexer.utils.hashing import text_hash, file_hash, chunk_id


class TestCodeChunk:
    def _make_chunk(self, **kwargs) -> CodeChunk:
        defaults = dict(
            repo_root="/repo",
            rel_path="src/foo.py",
            language=Language.PYTHON,
            kind=ChunkKind.FUNCTION,
            symbol_name="my_func",
            start_line=10,
            end_line=20,
            text="def my_func():\n    pass\n",
        )
        return CodeChunk(**{**defaults, **kwargs})

    def test_chunk_id_is_auto_computed(self) -> None:
        chunk = self._make_chunk()
        assert len(chunk.chunk_id) == 16
        assert all(c in "0123456789abcdef" for c in chunk.chunk_id)

    def test_chunk_id_is_stable(self) -> None:
        c1 = self._make_chunk()
        c2 = self._make_chunk()
        assert c1.chunk_id == c2.chunk_id

    def test_chunk_id_changes_with_location(self) -> None:
        c1 = self._make_chunk(start_line=10)
        c2 = self._make_chunk(start_line=20)
        assert c1.chunk_id != c2.chunk_id

    def test_token_count_approximation(self) -> None:
        text = "x" * 400  # 400 chars → ~100 tokens
        chunk = self._make_chunk(text=text)
        assert chunk.token_count == 100

    def test_full_text_for_embedding_has_header(self) -> None:
        chunk = self._make_chunk()
        full = chunk.full_text_for_embedding
        assert "src/foo.py" in full
        assert "python" in full
        assert "function" in full
        assert "my_func" in full

    def test_full_text_includes_context_before(self) -> None:
        chunk = self._make_chunk(context_before="class MyClass:")
        full = chunk.full_text_for_embedding
        assert "class MyClass:" in full

    def test_display_location_format(self) -> None:
        chunk = self._make_chunk(start_line=10, end_line=20)
        assert chunk.display_location == "src/foo.py:10-20"

    def test_explicit_chunk_id_not_overwritten(self) -> None:
        chunk = self._make_chunk(chunk_id="custom_id_123")
        assert chunk.chunk_id == "custom_id_123"


class TestHashing:
    def test_text_hash_is_deterministic(self) -> None:
        assert text_hash("hello") == text_hash("hello")

    def test_text_hash_differs_for_different_inputs(self) -> None:
        assert text_hash("hello") != text_hash("world")

    def test_text_hash_is_16_chars(self) -> None:
        assert len(text_hash("test")) == 16

    def test_chunk_id_stable(self) -> None:
        id1 = chunk_id("/repo", "src/foo.py", 10)
        id2 = chunk_id("/repo", "src/foo.py", 10)
        assert id1 == id2

    def test_chunk_id_differs_by_line(self) -> None:
        assert chunk_id("/repo", "src/foo.py", 10) != chunk_id("/repo", "src/foo.py", 11)
