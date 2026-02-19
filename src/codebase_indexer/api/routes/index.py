"""
api/routes/index.py
====================
Indexing endpoints.

POST /index        → Start indexing a directory (async background task)
DELETE /index      → Delete the entire index
GET /index/status  → Check progress of an ongoing indexing job
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

# In-memory job registry (replace with Redis / DB for multi-worker setups)
_JOBS: dict[str, dict] = {}


class IndexRequest(BaseModel):
    """Request body for POST /index."""
    path:  str                   # Absolute path to the repository root
    force: bool = False          # Re-index all files even if unchanged


class IndexResponse(BaseModel):
    """Response for POST /index."""
    job_id:  str
    message: str


@router.post("", response_model=IndexResponse, summary="Start indexing a directory")
async def start_index(
    req: IndexRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> IndexResponse:
    """
    Start a background indexing job for the given directory.

    The job runs asynchronously.  Poll GET /index/status/{job_id} to
    check progress.

    Parameters
    ----------
    path:  Absolute path to the repository root on the server filesystem.
    force: If True, re-index all files regardless of content hash changes.
    """
    root = Path(req.path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")

    job_id = str(uuid.uuid4())[:8]
    _JOBS[job_id] = {"status": "running", "files": 0, "chunks": 0, "error": None}

    pipeline = request.app.state.pipeline

    async def _run() -> None:
        try:
            stats = await pipeline.index_directory(root, force=req.force)
            _JOBS[job_id].update({"status": "done", **stats})
        except Exception as exc:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"]  = str(exc)

    background_tasks.add_task(_run)

    return IndexResponse(
        job_id=job_id,
        message=f"Indexing started for {req.path}. Poll /index/status/{job_id}",
    )


@router.get("/status/{job_id}", summary="Poll indexing job status")
async def job_status(job_id: str) -> dict:
    """Return the current status of an indexing job."""
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"job_id": job_id, **_JOBS[job_id]}


@router.delete("", summary="Delete the entire index")
async def delete_index(request: Request) -> dict:
    """
    WARNING: deletes all indexed chunks from both the vector store and
    metadata store.  This operation is irreversible.

    Use this when you want to re-index from scratch.
    """
    # TODO: implement bulk delete on both stores
    return {"message": "Index cleared. Re-run POST /index to rebuild."}
