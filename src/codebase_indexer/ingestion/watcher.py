"""
ingestion/watcher.py
====================
Incremental file-system watcher for live re-indexing.

Uses the `watchdog` library to receive OS-level inotify / kqueue / FSEvents
notifications and debounces rapid successive changes (e.g., editor save storms)
before triggering the indexing pipeline.

Debouncing
----------
Text editors often save a file many times in rapid succession (autosave,
format-on-save, lint-fix).  Without debouncing, the indexer would re-embed
the same file 10+ times per second.  The debounce timer waits
`settings.watch_debounce_seconds` (default 2 s) after the last event
before actually re-indexing.

Thread model
------------
watchdog runs its observer thread in the background.  When a file event
fires, we schedule a coroutine on the main asyncio event loop via
`asyncio.run_coroutine_threadsafe()`.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable, Awaitable

from ..config import settings
from ..utils.logging import get_logger

logger = get_logger(__name__)

# Type alias for the callback the watcher calls when files change
OnChangeCallback = Callable[[list[Path]], Awaitable[None]]


class FileWatcher:
    """
    Watch a directory for changes and invoke a callback with changed paths.

    Usage
    -----
        async def on_change(paths: list[Path]):
            for p in paths:
                await reindex_file(p)

        watcher = FileWatcher(root=Path("/repo"), callback=on_change)
        await watcher.start()
        # ... runs until watcher.stop() is called
        await watcher.stop()
    """

    def __init__(self, root: Path, callback: OnChangeCallback) -> None:
        self.root = root.resolve()
        self.callback = callback
        self._loop: asyncio.AbstractEventLoop | None = None
        self._observer: object | None = None
        self._pending: dict[Path, asyncio.TimerHandle] = {}
        self._lock = threading.Lock()

    async def start(self) -> None:
        """Start the background observer thread."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileSystemEvent
        except ImportError:
            logger.warning(
                "watchdog not installed – file watching disabled. "
                "Install with: pip install watchdog"
            )
            return

        self._loop = asyncio.get_event_loop()

        watcher_self = self  # capture for closure

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: "FileSystemEvent") -> None:
                if event.is_directory:
                    return
                path = Path(event.src_path)
                watcher_self._schedule(path)

        observer = Observer()
        observer.schedule(_Handler(), str(self.root), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("file watcher started", extra={"root": str(self.root)})

    async def stop(self) -> None:
        """Stop the background observer thread."""
        if self._observer is not None:
            self._observer.stop()   # type: ignore[attr-defined]
            self._observer.join()   # type: ignore[attr-defined]
            logger.info("file watcher stopped")

    def _schedule(self, path: Path) -> None:
        """
        Schedule (or reschedule) a debounced callback for `path`.

        Called from the watchdog thread – must be thread-safe.
        """
        if self._loop is None:
            return

        def _fire() -> None:
            with self._lock:
                changed = list(self._pending.keys())
                self._pending.clear()
            asyncio.ensure_future(self.callback(changed), loop=self._loop)

        with self._lock:
            # Cancel any existing timer for this path
            if path in self._pending:
                self._pending.pop(path).cancel()

            handle = self._loop.call_later(
                settings.watch_debounce_seconds, _fire
            )
            self._pending[path] = handle
