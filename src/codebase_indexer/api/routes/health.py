"""
api/routes/health.py
====================
Health check and index statistics endpoints.

GET /health  → liveness probe (returns 200 if the server is alive)
GET /info    → index statistics (file count, chunk count, last indexed time, etc.)
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...models.document import IndexStats

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    """
    Returns 200 with {"status": "ok"}.

    Use this as the liveness probe for Kubernetes / Docker health checks.
    The probe does NOT check that the vector store is reachable – use /info
    for a deeper readiness check.
    """
    return {"status": "ok"}


@router.get(
    "/info",
    response_model=IndexStats,
    summary="Index statistics and configuration info",
)
async def info(request: Request) -> IndexStats:
    """
    Return aggregate statistics about the current state of the index:
      - total files, chunks, tokens
      - per-language and per-kind breakdown
      - configured vector backend and embedding model
      - timestamp of the last indexing run
    """
    metadata_store = request.app.state.metadata_store
    return await metadata_store.get_stats()
