"""
api/app.py
==========
FastAPI application factory.

Startup sequence
----------------
  1. Initialise metadata store (runs DB migrations if needed).
  2. Initialise vector store (connects to ChromaDB / Qdrant).
  3. Load the BM25 index from disk (if it exists).
  4. Instantiate retrievers and the RetrievalEngine.
  5. Mount all routes.

Dependency injection
--------------------
We use FastAPI's dependency injection system to provide the RetrievalEngine
and IndexPipeline to route handlers.  A single instance of each is created
at startup (via app.state) and injected as needed.

This avoids global variables and makes testing easy – tests can override
the dependency to inject mocks.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from ..embeddings.factory import get_embedder
from ..pipeline import IndexPipeline
from ..retrieval.engine import RetrievalEngine
from ..retrieval.hybrid import HybridRetriever
from ..retrieval.keyword import KeywordRetriever
from ..retrieval.reranker import CrossEncoderReranker
from ..retrieval.semantic import SemanticRetriever
from ..storage.factory import get_metadata_store, get_vector_store
from ..utils.logging import get_logger
from .routes.health import router as health_router
from .routes.index import router as index_router
from .routes.search import router as search_router

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise all singletons on startup, clean up on shutdown."""
    logger.info("starting codebase-indexer API", extra={"version": "1.0.0"})

    # Storage
    vector_store   = get_vector_store()
    metadata_store = get_metadata_store()

    # Embedding
    embedder = get_embedder()

    # Retrieval
    semantic = SemanticRetriever(embedder, vector_store, metadata_store)
    keyword  = KeywordRetriever(metadata_store)
    await keyword.load_index()   # no-op if index file doesn't exist

    hybrid   = HybridRetriever(semantic, keyword)
    reranker = CrossEncoderReranker() if settings.reranker_enabled else None

    retrieval_engine = RetrievalEngine(semantic, keyword, hybrid, reranker)
    pipeline = IndexPipeline(vector_store, metadata_store, embedder, keyword)

    # Attach to app state for dependency injection
    app.state.retrieval_engine = retrieval_engine
    app.state.pipeline         = pipeline
    app.state.metadata_store   = metadata_store

    logger.info("startup complete")
    yield
    logger.info("shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Codebase Indexer API",
        description=(
            "Production-ready codebase indexing system for RAG and code generation. "
            "Index your codebase once, query it semantically forever."
        ),
        version="1.0.0",
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware (optional API key)
    if settings.api_key:
        from .middleware import APIKeyMiddleware
        app.add_middleware(APIKeyMiddleware, api_key=settings.api_key)

    # Routes
    app.include_router(health_router, tags=["Health"])
    app.include_router(index_router,  prefix="/index",  tags=["Indexing"])
    app.include_router(search_router, prefix="/search", tags=["Search"])

    return app
