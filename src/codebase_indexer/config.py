"""
config.py
=========
Central configuration management using Pydantic Settings.

All settings can be overridden via environment variables or a .env file.
Variable names are automatically uppercased and prefixed with CIDX_.

Example .env:
    CIDX_EMBED_PROVIDER=openai
    CIDX_OPENAI_API_KEY=sk-...
    CIDX_VECTOR_BACKEND=chroma
    CIDX_CHROMA_PATH=/data/chroma
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enums – enumerate all valid string choices for key settings
# ---------------------------------------------------------------------------

class EmbedProvider(str, Enum):
    """Which embedding model provider to use."""
    OPENAI = "openai"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    # Future: cohere, voyage, etc.


class VectorBackend(str, Enum):
    """Which vector database to use for storing / querying embeddings."""
    CHROMA = "chroma"
    QDRANT = "qdrant"
    # Future: pinecone, weaviate, milvus


class ChunkStrategy(str, Enum):
    """How to split source files into indexable chunks."""
    SEMANTIC = "semantic"          # split on AST symbol boundaries
    SLIDING_WINDOW = "sliding"     # fixed-size overlapping windows
    HYBRID = "hybrid"              # semantic first, slide for large symbols


class SearchMode(str, Enum):
    """Retrieval strategy returned by the search API."""
    SEMANTIC = "semantic"          # cosine similarity on embeddings only
    KEYWORD = "keyword"            # BM25 term frequency
    HYBRID = "hybrid"              # reciprocal rank fusion of both


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    Master configuration object.  Every field has a sensible default so the
    system runs out-of-the-box with no environment configuration.
    """

    model_config = SettingsConfigDict(
        env_prefix="CIDX_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- General -----------------------------------------------------------
    project_name: str = "codebase-indexer"
    debug: bool = False
    log_level: str = "INFO"

    # ---- API ---------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    api_key: Optional[str] = None          # if set, all requests must supply X-API-Key header
    cors_origins: list[str] = ["*"]

    # ---- Ingestion ---------------------------------------------------------
    # Maximum file size to ingest (bytes).  Files larger than this are skipped.
    max_file_bytes: int = 5 * 1024 * 1024  # 5 MB

    # Glob patterns for files to always ignore during crawl.
    ignore_patterns: list[str] = [
        "**/.git/**", "**/node_modules/**", "**/__pycache__/**",
        "**/.venv/**", "**/venv/**", "**/.tox/**",
        "**/*.pyc", "**/*.pyo", "**/*.so", "**/*.dylib", "**/*.dll",
        "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif", "**/*.ico",
        "**/*.svg", "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
        "**/*.zip", "**/*.tar", "**/*.gz", "**/*.bz2", "**/*.7z",
        "**/*.pdf", "**/*.docx", "**/*.xlsx",
        "**/dist/**", "**/build/**", "**/.next/**", "**/.nuxt/**",
    ]

    # How many files to ingest concurrently
    ingest_concurrency: int = 8

    # ---- Chunking ----------------------------------------------------------
    chunk_strategy: ChunkStrategy = ChunkStrategy.HYBRID

    # sliding-window parameters (used when strategy is SLIDING or HYBRID)
    chunk_size: int = 512       # tokens (approximated as chars/4)
    chunk_overlap: int = 64     # tokens of overlap between adjacent windows

    # semantic chunking: maximum symbol size before further splitting
    max_symbol_tokens: int = 1024

    # ---- Embedding ---------------------------------------------------------
    embed_provider: EmbedProvider = EmbedProvider.SENTENCE_TRANSFORMERS

    # OpenAI settings (only used when embed_provider == openai)
    openai_api_key: Optional[str] = None
    openai_embed_model: str = "text-embedding-3-small"
    openai_embed_batch_size: int = 512

    # Sentence-Transformers settings
    st_model_name: str = "BAAI/bge-base-en-v1.5"
    st_device: str = "cpu"    # "cpu" | "cuda" | "mps"
    st_batch_size: int = 64

    # Embedding cache: store computed embeddings to disk to avoid recomputation
    embed_cache_enabled: bool = True
    embed_cache_dir: Path = Path(".cidx_cache/embeddings")

    # ---- Vector store ------------------------------------------------------
    vector_backend: VectorBackend = VectorBackend.CHROMA

    # ChromaDB settings
    chroma_path: Path = Path(".cidx_data/chroma")
    chroma_collection: str = "codebase"

    # Qdrant settings
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "codebase"

    # ---- Metadata store ----------------------------------------------------
    metadata_db_url: str = "sqlite:///.cidx_data/metadata.db"

    # ---- Retrieval ---------------------------------------------------------
    default_search_mode: SearchMode = SearchMode.HYBRID

    # Number of candidates fetched from vector store before re-ranking
    retrieval_top_k: int = 20

    # Number of results returned to the user after re-ranking
    results_top_n: int = 10

    # BM25 index path (flat file persisted next to metadata db)
    bm25_index_path: Path = Path(".cidx_data/bm25.pkl")

    # Cross-encoder re-ranking model (set to "" to disable re-ranking)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_enabled: bool = False   # disabled by default (adds latency)

    # ---- Git integration ---------------------------------------------------
    # When True, respect .gitignore patterns during crawl
    respect_gitignore: bool = True

    # When True, store git blame metadata (author, commit) with each chunk
    store_git_blame: bool = False

    # ---- Watching (incremental re-index) -----------------------------------
    watch_debounce_seconds: float = 2.0  # wait this long after last event

    # ---------------------------------------------------------------------------
    @field_validator("embed_cache_dir", "chroma_path", "bm25_index_path", mode="before")
    @classmethod
    def _expand_path(cls, v: object) -> Path:
        return Path(os.path.expandvars(str(v))).expanduser()


# Module-level singleton – import this everywhere else
settings = Settings()
