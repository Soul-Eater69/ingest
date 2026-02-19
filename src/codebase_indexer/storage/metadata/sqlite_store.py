"""
storage/metadata/sqlite_store.py
==================================
SQLite-backed metadata store using SQLAlchemy Core (not ORM).

Why SQLAlchemy Core instead of the ORM?
  - Lighter weight (no object mapping overhead)
  - Works with both SQLite and PostgreSQL by swapping the connection URL
  - Explicit SQL is easier to debug

Schema
------
  files   – one row per indexed file
  chunks  – one row per CodeChunk

SQLite WAL mode is enabled for better concurrent read performance.

Thread safety
-------------
SQLAlchemy connections are NOT safe to share across threads.  We use
a connection pool and acquire a fresh connection per operation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table, Text,
    create_engine, event, select, text, delete, func
)
from sqlalchemy.engine import Engine

from ...config import settings
from ...models.chunk import CodeChunk, ChunkKind, Language
from ...models.document import IndexStats
from ...utils.concurrency import run_in_executor
from ...utils.logging import get_logger
from .base import BaseMetadataStore

logger = get_logger(__name__)

_metadata = MetaData()

files_table = Table(
    "files", _metadata,
    Column("rel_path",     String(1024), primary_key=True),
    Column("content_hash", String(64),   nullable=False),
    Column("language",     String(32),   nullable=False),
    Column("chunk_count",  Integer,      nullable=False, default=0),
    Column("indexed_at",   DateTime,     nullable=False),
)

chunks_table = Table(
    "chunks", _metadata,
    Column("chunk_id",      String(32),   primary_key=True),
    Column("rel_path",      String(1024), nullable=False, index=True),
    Column("repo_root",     String(1024), nullable=False),
    Column("language",      String(32),   nullable=False, index=True),
    Column("kind",          String(32),   nullable=False, index=True),
    Column("symbol_name",   String(512),  nullable=True),
    Column("start_line",    Integer,      nullable=False),
    Column("end_line",      Integer,      nullable=False),
    Column("text",          Text,         nullable=False),
    Column("context_before", Text,        nullable=True),
    Column("docstring",     Text,         nullable=True),
    Column("token_count",   Integer,      nullable=False, default=0),
    Column("git_commit",    String(40),   nullable=True),
    Column("git_author",    String(256),  nullable=True),
    Column("extra_json",    Text,         nullable=True),
)


def _enable_wal(dbapi_conn: object, _: object) -> None:
    """Enable Write-Ahead Logging for better concurrent read performance."""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")  # type: ignore[attr-defined]
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")  # type: ignore[attr-defined]


class SQLiteMetadataStore(BaseMetadataStore):
    """SQLite-backed metadata store."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        url = db_url or settings.metadata_db_url

        # Ensure the parent directory exists for SQLite file DBs
        if url.startswith("sqlite:///"):
            from pathlib import Path
            db_path = Path(url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self._engine: Engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if "sqlite" in url else {},
        )

        if "sqlite" in url:
            event.listen(self._engine, "connect", _enable_wal)

        _metadata.create_all(self._engine)
        logger.info("metadata store ready", extra={"url": url})

    # ------------------------------------------------------------------
    async def upsert_chunks(self, chunks: list[CodeChunk]) -> None:
        def _do() -> None:
            with self._engine.begin() as conn:
                for chunk in chunks:
                    conn.execute(
                        chunks_table.delete().where(
                            chunks_table.c.chunk_id == chunk.chunk_id
                        )
                    )
                    conn.execute(chunks_table.insert().values(
                        chunk_id=chunk.chunk_id,
                        rel_path=chunk.rel_path,
                        repo_root=chunk.repo_root,
                        language=chunk.language.value,
                        kind=chunk.kind.value,
                        symbol_name=chunk.symbol_name,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        text=chunk.text,
                        context_before=chunk.context_before or None,
                        docstring=chunk.docstring,
                        token_count=chunk.token_count,
                        git_commit=chunk.git_commit,
                        git_author=chunk.git_author,
                        extra_json=json.dumps(chunk.extra) if chunk.extra else None,
                    ))
        await run_in_executor(_do)

    async def get_chunk(self, chunk_id: str) -> Optional[CodeChunk]:
        chunks = await self.get_chunks_by_ids([chunk_id])
        return chunks[0] if chunks else None

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[CodeChunk]:
        if not chunk_ids:
            return []

        def _do() -> list[CodeChunk]:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(chunks_table).where(
                        chunks_table.c.chunk_id.in_(chunk_ids)
                    )
                ).fetchall()
                return [_row_to_chunk(r) for r in rows]

        return await run_in_executor(_do)

    async def delete_chunks_by_path(self, rel_path: str) -> int:
        def _do() -> int:
            with self._engine.begin() as conn:
                result = conn.execute(
                    chunks_table.delete().where(
                        chunks_table.c.rel_path == rel_path
                    )
                )
                return result.rowcount  # type: ignore[attr-defined]
        return await run_in_executor(_do)

    async def get_file_hash(self, rel_path: str) -> Optional[str]:
        def _do() -> Optional[str]:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(files_table.c.content_hash).where(
                        files_table.c.rel_path == rel_path
                    )
                ).fetchone()
                return row[0] if row else None
        return await run_in_executor(_do)

    async def get_all_file_hashes(self) -> dict[str, str]:
        def _do() -> dict[str, str]:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(files_table.c.rel_path, files_table.c.content_hash)
                ).fetchall()
                return {r[0]: r[1] for r in rows}
        return await run_in_executor(_do)

    async def upsert_file_record(
        self,
        rel_path: str,
        content_hash: str,
        language: Language,
        chunk_count: int,
    ) -> None:
        def _do() -> None:
            with self._engine.begin() as conn:
                conn.execute(files_table.delete().where(
                    files_table.c.rel_path == rel_path
                ))
                conn.execute(files_table.insert().values(
                    rel_path=rel_path,
                    content_hash=content_hash,
                    language=language.value,
                    chunk_count=chunk_count,
                    indexed_at=datetime.utcnow(),
                ))
        await run_in_executor(_do)

    async def get_stats(self) -> IndexStats:
        def _do() -> IndexStats:
            with self._engine.connect() as conn:
                total_files  = conn.execute(
                    select(func.count()).select_from(files_table)
                ).scalar() or 0
                total_chunks = conn.execute(
                    select(func.count()).select_from(chunks_table)
                ).scalar() or 0
                total_tokens = conn.execute(
                    select(func.sum(chunks_table.c.token_count))
                ).scalar() or 0

                # per-language breakdown
                lang_rows = conn.execute(
                    select(files_table.c.language, func.count().label("n"))
                    .group_by(files_table.c.language)
                ).fetchall()
                files_by_lang = {r[0]: r[1] for r in lang_rows}

                # per-kind breakdown
                kind_rows = conn.execute(
                    select(chunks_table.c.kind, func.count().label("n"))
                    .group_by(chunks_table.c.kind)
                ).fetchall()
                chunks_by_kind = {r[0]: r[1] for r in kind_rows}

                # last indexed time
                last_row = conn.execute(
                    select(func.max(files_table.c.indexed_at))
                ).scalar()

                return IndexStats(
                    total_files=total_files,
                    total_chunks=total_chunks,
                    total_tokens=total_tokens,
                    files_by_language=files_by_lang,
                    chunks_by_kind=chunks_by_kind,
                    last_indexed_at=last_row,
                    vector_backend=settings.vector_backend.value,
                    embed_provider=settings.embed_provider.value,
                    embed_model=(settings.openai_embed_model
                                 if settings.embed_provider.value == "openai"
                                 else settings.st_model_name),
                )
        return await run_in_executor(_do)


def _row_to_chunk(row: object) -> CodeChunk:
    """Convert a SQLAlchemy Row to a CodeChunk."""
    extra = json.loads(row.extra_json) if row.extra_json else {}  # type: ignore[attr-defined]
    return CodeChunk(
        chunk_id=row.chunk_id,         # type: ignore[attr-defined]
        repo_root=row.repo_root,       # type: ignore[attr-defined]
        rel_path=row.rel_path,         # type: ignore[attr-defined]
        language=Language(row.language),  # type: ignore[attr-defined]
        kind=ChunkKind(row.kind),         # type: ignore[attr-defined]
        symbol_name=row.symbol_name,      # type: ignore[attr-defined]
        start_line=row.start_line,        # type: ignore[attr-defined]
        end_line=row.end_line,            # type: ignore[attr-defined]
        text=row.text,                    # type: ignore[attr-defined]
        context_before=row.context_before or "",  # type: ignore[attr-defined]
        docstring=row.docstring,          # type: ignore[attr-defined]
        token_count=row.token_count,      # type: ignore[attr-defined]
        git_commit=row.git_commit,        # type: ignore[attr-defined]
        git_author=row.git_author,        # type: ignore[attr-defined]
        extra=extra,
    )
