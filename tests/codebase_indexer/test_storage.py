"""
tests/codebase_indexer/test_storage.py
========================================
Integration tests for the metadata store (SQLite).

Uses an in-memory SQLite database to keep tests fast and isolated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codebase_indexer.models.chunk import CodeChunk, ChunkKind, Language
from codebase_indexer.storage.metadata.sqlite_store import SQLiteMetadataStore


def make_chunk(
    chunk_id: str = "abc123",
    rel_path: str = "src/foo.py",
    kind: ChunkKind = ChunkKind.FUNCTION,
    symbol: str = "my_func",
    start: int = 1,
    end: int = 10,
) -> CodeChunk:
    return CodeChunk(
        chunk_id=chunk_id,
        repo_root="/repo",
        rel_path=rel_path,
        language=Language.PYTHON,
        kind=kind,
        symbol_name=symbol,
        start_line=start,
        end_line=end,
        text="def my_func():\n    pass\n",
    )


class TestSQLiteMetadataStore:
    def setup_method(self) -> None:
        # In-memory SQLite DB
        self.store = SQLiteMetadataStore("sqlite:///:memory:")

    def _run(self, coro):
        return asyncio.run(coro)

    def test_upsert_and_retrieve_chunk(self) -> None:
        chunk = make_chunk()
        self._run(self.store.upsert_chunks([chunk]))
        fetched = self._run(self.store.get_chunk("abc123"))
        assert fetched is not None
        assert fetched.chunk_id == "abc123"
        assert fetched.symbol_name == "my_func"

    def test_retrieve_multiple_chunks(self) -> None:
        c1 = make_chunk(chunk_id="id1", symbol="func_a")
        c2 = make_chunk(chunk_id="id2", symbol="func_b")
        self._run(self.store.upsert_chunks([c1, c2]))
        chunks = self._run(self.store.get_chunks_by_ids(["id1", "id2"]))
        assert len(chunks) == 2
        names = {c.symbol_name for c in chunks}
        assert "func_a" in names and "func_b" in names

    def test_delete_chunks_by_path(self) -> None:
        c = make_chunk(chunk_id="del1", rel_path="src/del.py")
        self._run(self.store.upsert_chunks([c]))
        deleted = self._run(self.store.delete_chunks_by_path("src/del.py"))
        assert deleted == 1
        fetched = self._run(self.store.get_chunk("del1"))
        assert fetched is None

    def test_file_hash_round_trip(self) -> None:
        self._run(self.store.upsert_file_record(
            "src/foo.py", "abc123hash", Language.PYTHON, 5
        ))
        h = self._run(self.store.get_file_hash("src/foo.py"))
        assert h == "abc123hash"

    def test_get_all_file_hashes(self) -> None:
        self._run(self.store.upsert_file_record("a.py", "hash_a", Language.PYTHON, 1))
        self._run(self.store.upsert_file_record("b.go", "hash_b", Language.GO, 2))
        hashes = self._run(self.store.get_all_file_hashes())
        assert hashes["a.py"] == "hash_a"
        assert hashes["b.go"] == "hash_b"

    def test_get_stats(self) -> None:
        c1 = make_chunk(chunk_id="s1", rel_path="x.py")
        c2 = make_chunk(chunk_id="s2", rel_path="y.py", kind=ChunkKind.CLASS)
        self._run(self.store.upsert_chunks([c1, c2]))
        self._run(self.store.upsert_file_record("x.py", "h1", Language.PYTHON, 1))
        self._run(self.store.upsert_file_record("y.py", "h2", Language.PYTHON, 1))
        stats = self._run(self.store.get_stats())
        assert stats.total_files == 2
        assert stats.total_chunks == 2

    def test_upsert_is_idempotent(self) -> None:
        chunk = make_chunk()
        self._run(self.store.upsert_chunks([chunk]))
        self._run(self.store.upsert_chunks([chunk]))   # second upsert same chunk
        chunks = self._run(self.store.get_chunks_by_ids(["abc123"]))
        assert len(chunks) == 1   # still only one row

    def test_get_nonexistent_chunk_returns_none(self) -> None:
        result = self._run(self.store.get_chunk("does_not_exist"))
        assert result is None
