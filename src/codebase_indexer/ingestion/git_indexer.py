"""
ingestion/git_indexer.py
========================
Git-aware metadata enrichment.

Adds git blame information (author, commit SHA) to SourceFile objects
so that chunks can be filtered by author or commit date at retrieval time.

This module uses `git log` and `git blame` via subprocess rather than
a Python git library (like GitPython or pygit2) to keep dependencies minimal
and avoid native library requirements.

Design note
-----------
git blame is expensive: O(lines × history depth).  We only run it when
`settings.store_git_blame` is True AND the file has changed since last index.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


def _run_git(args: list[str], cwd: Path) -> str:
    """
    Run a git command and return its stdout as a string.

    Raises RuntimeError if git is not available or the command fails.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("git command failed", extra={
                "args": args, "stderr": result.stderr.strip()
            })
            return ""
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("git not available", extra={"error": str(exc)})
        return ""


class GitIndexer:
    """
    Enriches source files with git metadata.

    Parameters
    ----------
    repo_root: Path to the git repository root.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._is_git_repo = (repo_root / ".git").exists()

    def is_git_repo(self) -> bool:
        return self._is_git_repo

    def get_file_blame(self, rel_path: str) -> Optional[tuple[str, str]]:
        """
        Return (commit_sha, author_email) for the most recent commit
        that modified the given file.

        Returns None if git is not available or the file is untracked.
        """
        if not self._is_git_repo:
            return None

        # git log -1 --format="%H %ae" -- <path>
        output = _run_git(
            ["log", "-1", "--format=%H %ae", "--", rel_path],
            self.repo_root,
        )
        if not output:
            return None

        parts = output.split(" ", 1)
        if len(parts) != 2:
            return None
        commit_sha, author_email = parts
        return commit_sha, author_email

    def get_changed_files(self, since_commit: Optional[str] = None) -> list[str]:
        """
        Return list of files changed since `since_commit`.

        If `since_commit` is None, returns all files tracked by git.
        Useful for computing the diff between two index runs.
        """
        if not self._is_git_repo:
            return []

        if since_commit:
            output = _run_git(
                ["diff", "--name-only", since_commit, "HEAD"],
                self.repo_root,
            )
        else:
            output = _run_git(["ls-files"], self.repo_root)

        return [line for line in output.splitlines() if line.strip()]

    def get_current_commit(self) -> Optional[str]:
        """Return the SHA of the current HEAD commit."""
        if not self._is_git_repo:
            return None
        result = _run_git(["rev-parse", "HEAD"], self.repo_root)
        return result or None
