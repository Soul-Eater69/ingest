"""
utils/hashing.py
================
Deterministic hashing helpers used for cache keys and change detection.

We use SHA-256 truncated to 16 hex chars (64-bit collision space) which is
more than sufficient for de-duplication within a single codebase.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path, chunk_size: int = 65536) -> str:
    """
    Compute the SHA-256 digest of a file without loading it entirely into RAM.

    Reads in `chunk_size`-byte blocks (default 64 KB) so it can handle
    large files efficiently.

    Parameters
    ----------
    path:       Absolute or relative path to the file.
    chunk_size: Number of bytes to read per iteration.

    Returns
    -------
    16-character hex digest (first 64 bits of SHA-256).
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()[:16]


def text_hash(text: str) -> str:
    """
    Compute the SHA-256 digest of a UTF-8 string.

    Used to build cache keys for embeddings: if the text hasn't changed,
    the embedding vector can be reused from disk without calling the API.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def chunk_id(repo_root: str, rel_path: str, start_line: int) -> str:
    """
    Build a stable, unique chunk identifier from location metadata.

    Stable = same input always produces the same output, so re-indexing
    an unchanged file produces identical chunk IDs, enabling upserts.
    """
    raw = f"{repo_root}|{rel_path}|{start_line}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
