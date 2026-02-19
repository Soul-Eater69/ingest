"""
main.py
=======
Application entry point for the FastAPI server.

Used by uvicorn:
    uvicorn codebase_indexer.main:app

Or via Docker CMD:
    python -m codebase_indexer.main
"""

from .api.app import create_app

app = create_app()
