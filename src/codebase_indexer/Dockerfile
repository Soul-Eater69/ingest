# =============================================================================
# Codebase Indexer – Dockerfile
# =============================================================================
#
# Multi-stage build:
#   Stage 1 (builder): Install Python dependencies into /install
#   Stage 2 (runtime): Copy only the installed packages + source code
#
# This pattern keeps the final image small by excluding build tools
# (gcc, pip cache, wheel files) from the production image.
#
# Build:
#   docker build -t codebase-indexer:latest -f src/codebase_indexer/Dockerfile .
#
# Run:
#   docker run -p 8000:8000 \
#     -v /path/to/repo:/repo:ro \
#     -v cidx-data:/app/.cidx_data \
#     -e CIDX_EMBED_PROVIDER=sentence_transformers \
#     codebase-indexer:latest

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim AS builder

# Install build dependencies for packages that have C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only dependency files first (Docker layer caching optimisation)
COPY pyproject.toml ./

# Install all dependencies into a prefix directory
# --prefix /install → all packages go to /install/lib/python3.11/site-packages/
RUN pip install --no-cache-dir --prefix /install \
    # Core runtime dependencies
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    pydantic-settings \
    sqlalchemy \
    click \
    watchdog \
    rank-bm25 \
    numpy \
    # Default embedding backend
    sentence-transformers \
    # Default vector store
    chromadb \
    # Optional: uncomment to include OpenAI
    # openai \
    # Optional: uncomment for Qdrant support
    # qdrant-client \
    aiofiles

# Copy source code
COPY src/ /build/src/

# Install the package itself
RUN pip install --no-cache-dir --prefix /install --no-deps /build/src


# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

# Security: run as non-root user
RUN groupadd -r cidx && useradd -r -g cidx -d /app cidx

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Data directories (override with volumes in production)
RUN mkdir -p .cidx_data .cidx_cache/embeddings \
    && chown -R cidx:cidx /app

USER cidx

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

# Default command: start the API server
CMD ["python", "-m", "uvicorn", \
     "codebase_indexer.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
