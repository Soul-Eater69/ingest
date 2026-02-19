"""
models/document.py
==================
Higher-level models representing a whole source file and index statistics.

SourceFile   – raw file on disk before parsing
IndexedDocument – a file after parsing and chunking (with chunk list)
IndexStats   – aggregate statistics about the current index state
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from .chunk import CodeChunk, Language


class SourceFile(BaseModel):
    """
    A source file discovered by the crawler before any processing.

    Attributes
    ----------
    abs_path   Absolute path on the host filesystem.
    rel_path   Path relative to repo_root (used as the stable identifier).
    repo_root  Absolute path of the repository root.
    language   Detected programming language.
    size_bytes File size in bytes.
    mtime      Last modified time (used for change detection).
    content_hash
               SHA-256 of file contents.  If this matches the stored hash,
               the file has not changed and can be skipped.
    content    Raw file text (populated by the crawler after reading).
    git_commit Most recent commit SHA that touched this file (optional).
    """

    abs_path:     Path
    rel_path:     str
    repo_root:    Path
    language:     Language
    size_bytes:   int
    mtime:        float           # os.stat().st_mtime
    content_hash: str = ""
    content:      Optional[str] = None
    git_commit:   Optional[str] = None
    git_author:   Optional[str] = None

    def compute_hash(self) -> str:
        """Compute and store content hash.  Call after loading content."""
        if self.content is None:
            raise ValueError("content must be set before computing hash")
        self.content_hash = hashlib.sha256(self.content.encode()).hexdigest()
        return self.content_hash


class IndexedDocument(BaseModel):
    """
    A fully processed source file: parsed, chunked, and ready for embedding.

    This is the output of the parsing + chunking stages and the input to
    the embedding + storage stages.
    """

    source:  SourceFile
    chunks:  list[CodeChunk] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=datetime.utcnow)

    @computed_field
    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


class IndexStats(BaseModel):
    """
    Snapshot of the current index state – returned by GET /health and
    by the CLI's `cidx info` command.
    """

    total_files:    int = 0
    total_chunks:   int = 0
    total_tokens:   int = 0

    # per-language breakdown
    files_by_language: dict[str, int] = Field(default_factory=dict)
    chunks_by_kind:    dict[str, int] = Field(default_factory=dict)

    # storage info
    vector_backend:    str = ""
    embed_provider:    str = ""
    embed_model:       str = ""

    last_indexed_at:   Optional[datetime] = None
    index_size_bytes:  int = 0
