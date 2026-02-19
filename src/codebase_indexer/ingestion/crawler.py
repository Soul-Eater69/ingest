"""
ingestion/crawler.py
====================
Asynchronous file-system crawler.

The crawler's job:
  1. Walk a directory tree
  2. Apply ignore patterns (gitignore + configured globs)
  3. Detect language for each file
  4. Read file content
  5. Yield SourceFile objects

Why async?
----------
Reading hundreds of files from disk is I/O-bound.  Using asyncio with
aiofiles allows us to issue many read() calls concurrently without
threads, keeping memory pressure low.

Change detection
----------------
The crawler computes a SHA-256 hash of each file's content and compares
it against the stored hash in the metadata database.  If the hash matches
the file is skipped, making incremental re-indexing very fast.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import AsyncIterator, Optional

from ..config import settings
from ..models.document import SourceFile
from ..models.chunk import Language
from ..utils.hashing import file_hash
from ..utils.logging import get_logger
from .language_detector import LanguageDetector

logger = get_logger(__name__)


class FileCrawler:
    """
    Async generator that yields SourceFile objects for each eligible file
    found under `root`.

    Parameters
    ----------
    root:            Repository root directory.
    known_hashes:    Dict mapping rel_path → content_hash from the previous
                     index pass.  Files whose hash hasn't changed are skipped
                     unless `force` is True.
    force:           Re-index all files regardless of hash.
    extra_ignores:   Additional glob patterns to ignore on top of the
                     configured defaults.
    """

    def __init__(
        self,
        root: Path,
        known_hashes: Optional[dict[str, str]] = None,
        force: bool = False,
        extra_ignores: Optional[list[str]] = None,
    ) -> None:
        self.root = root.resolve()
        self.known_hashes: dict[str, str] = known_hashes or {}
        self.force = force
        self.ignore_patterns = list(settings.ignore_patterns)
        if extra_ignores:
            self.ignore_patterns.extend(extra_ignores)
        self._detector = LanguageDetector()
        self._gitignore_patterns: list[str] = []

        if settings.respect_gitignore:
            self._load_gitignore()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def crawl(self) -> AsyncIterator[SourceFile]:
        """
        Yield SourceFile objects for every eligible, changed file under root.

        This is an async generator – consume it with `async for`:

            async for source_file in crawler.crawl():
                process(source_file)
        """
        total = skipped_ignore = skipped_size = skipped_unchanged = yielded = 0

        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            # Prune ignored directories in-place (faster than filtering filenames)
            dirnames[:] = [
                d for d in dirnames
                if not self._is_ignored(Path(dirpath) / d)
            ]

            for filename in filenames:
                total += 1
                abs_path = Path(dirpath) / filename

                if self._is_ignored(abs_path):
                    skipped_ignore += 1
                    continue

                stat = abs_path.stat()

                if stat.st_size > settings.max_file_bytes:
                    logger.debug("skipping oversized file", extra={
                        "path": str(abs_path), "size": stat.st_size
                    })
                    skipped_size += 1
                    continue

                rel_path = str(abs_path.relative_to(self.root))

                # Change detection: read hash without loading full content
                current_hash = file_hash(abs_path)
                if not self.force and self.known_hashes.get(rel_path) == current_hash:
                    skipped_unchanged += 1
                    continue

                # Read content
                try:
                    content = abs_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    logger.warning("cannot read file", extra={"path": rel_path, "error": str(exc)})
                    continue

                language = self._detector.detect(abs_path, content[:1024])

                source = SourceFile(
                    abs_path=abs_path,
                    rel_path=rel_path,
                    repo_root=self.root,
                    language=language,
                    size_bytes=stat.st_size,
                    mtime=stat.st_mtime,
                    content_hash=current_hash,
                    content=content,
                )
                yielded += 1

                # Yield control to the event loop between files so other
                # coroutines (e.g., embedding API calls) can make progress.
                await asyncio.sleep(0)
                yield source  # type: ignore[misc]

        logger.info("crawl complete", extra={
            "root": str(self.root),
            "total": total,
            "yielded": yielded,
            "skipped_ignore": skipped_ignore,
            "skipped_size": skipped_size,
            "skipped_unchanged": skipped_unchanged,
        })

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_ignored(self, path: Path) -> bool:
        """Return True if path matches any ignore / gitignore pattern."""
        rel = str(path.relative_to(self.root))
        for pattern in self.ignore_patterns + self._gitignore_patterns:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
        return False

    def _load_gitignore(self) -> None:
        """
        Parse .gitignore in the repository root and convert its patterns
        to fnmatch-compatible globs.

        Note: this is a simplified parser that handles the most common cases.
        For full gitignore spec compliance a library like `gitignorefile` would
        be needed.
        """
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            return

        for raw in gitignore.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Convert gitignore pattern to fnmatch glob
            if line.endswith("/"):
                self._gitignore_patterns.append(f"**/{line}**")
            else:
                self._gitignore_patterns.append(f"**/{line}")
                self._gitignore_patterns.append(line)
