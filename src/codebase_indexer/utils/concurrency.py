"""
utils/concurrency.py
====================
Async helpers for safe concurrent execution.

Why asyncio?
------------
File I/O and HTTP calls to embedding APIs are both I/O-bound.  asyncio lets
us saturate network / disk bandwidth without the overhead of threading or
multiprocessing.  CPU-bound work (AST parsing) is offloaded to a thread
pool via run_in_executor so it doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")

# Shared thread pool for CPU-bound work (AST parsing, BM25 indexing).
# Size = None → Python defaults to min(32, cpu_count+4).
_thread_pool = ThreadPoolExecutor(thread_name_prefix="cidx-worker")


async def run_in_executor(fn: Callable[..., T], *args: object) -> T:
    """
    Run a synchronous (potentially CPU-bound) function in the thread pool
    without blocking the asyncio event loop.

    Example
    -------
        result = await run_in_executor(my_ast_parser.parse, source_code)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_pool, fn, *args)


async def gather_with_concurrency(
    limit: int,
    *coros: Awaitable[T],
) -> list[T]:
    """
    Run coroutines concurrently but cap inflight work at `limit`.

    asyncio.gather() runs *all* coroutines at once which can overwhelm
    rate-limited APIs or exhaust file descriptors.  This wrapper uses a
    Semaphore to keep at most `limit` coroutines running at the same time.

    Parameters
    ----------
    limit:  Maximum number of concurrent coroutines.
    *coros: Any number of awaitable objects.

    Returns
    -------
    List of results in the same order as the input coroutines.
    """
    semaphore = asyncio.Semaphore(limit)

    async def _guarded(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(_guarded(c) for c in coros)))
