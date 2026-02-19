# Configuration Reference

All settings are read from environment variables prefixed with `CIDX_`
and/or from a `.env` file in the current working directory.

## Quick Start

```bash
# Minimum configuration for local use (no API key required)
cp .env.example .env
cidx index .
```

## All Settings

### General

| Variable          | Default               | Description                    |
|-------------------|-----------------------|--------------------------------|
| `CIDX_DEBUG`      | `false`               | Enable debug mode              |
| `CIDX_LOG_LEVEL`  | `INFO`                | Log level (DEBUG/INFO/WARNING) |

### API Server

| Variable            | Default     | Description                                     |
|---------------------|-------------|-------------------------------------------------|
| `CIDX_API_HOST`     | `0.0.0.0`   | Bind address                                    |
| `CIDX_API_PORT`     | `8000`      | Listen port                                     |
| `CIDX_API_WORKERS`  | `1`         | Number of uvicorn workers (use >1 in production)|
| `CIDX_API_KEY`      | (none)      | If set, requests must include `X-API-Key` header|
| `CIDX_CORS_ORIGINS` | `["*"]`     | List of allowed CORS origins                    |

### Ingestion

| Variable                  | Default      | Description                                             |
|---------------------------|--------------|---------------------------------------------------------|
| `CIDX_MAX_FILE_BYTES`     | `5242880`    | Max file size to index (5 MB default)                  |
| `CIDX_INGEST_CONCURRENCY` | `8`          | Max files processed concurrently                       |
| `CIDX_RESPECT_GITIGNORE`  | `true`       | Skip files matched by .gitignore                       |
| `CIDX_STORE_GIT_BLAME`    | `false`      | Store git author/commit per chunk (slow)               |

### Chunking

| Variable                  | Default    | Description                                    |
|---------------------------|------------|------------------------------------------------|
| `CIDX_CHUNK_STRATEGY`     | `hybrid`   | `semantic` / `sliding` / `hybrid`             |
| `CIDX_CHUNK_SIZE`         | `512`      | Sliding window size in approximate tokens      |
| `CIDX_CHUNK_OVERLAP`      | `64`       | Overlap between adjacent windows (tokens)     |
| `CIDX_MAX_SYMBOL_TOKENS`  | `1024`     | Max symbol size before hybrid splits it        |

### Embedding

| Variable                    | Default                    | Description                               |
|-----------------------------|----------------------------|-------------------------------------------|
| `CIDX_EMBED_PROVIDER`       | `sentence_transformers`    | `openai` / `sentence_transformers`        |
| `CIDX_OPENAI_API_KEY`       | (none)                     | Required when `EMBED_PROVIDER=openai`     |
| `CIDX_OPENAI_EMBED_MODEL`   | `text-embedding-3-small`   | OpenAI model name                         |
| `CIDX_ST_MODEL_NAME`        | `BAAI/bge-base-en-v1.5`   | Sentence-transformers model               |
| `CIDX_ST_DEVICE`            | `cpu`                      | `cpu` / `cuda` / `mps`                   |
| `CIDX_ST_BATCH_SIZE`        | `64`                       | Batch size for local embedding            |
| `CIDX_EMBED_CACHE_ENABLED`  | `true`                     | Cache embeddings to disk                  |
| `CIDX_EMBED_CACHE_DIR`      | `.cidx_cache/embeddings`   | Where to store cached vectors             |

### Vector Store

| Variable                  | Default              | Description                              |
|---------------------------|----------------------|------------------------------------------|
| `CIDX_VECTOR_BACKEND`     | `chroma`             | `chroma` / `qdrant`                     |
| `CIDX_CHROMA_PATH`        | `.cidx_data/chroma`  | ChromaDB persistence directory           |
| `CIDX_CHROMA_COLLECTION`  | `codebase`           | ChromaDB collection name                 |
| `CIDX_QDRANT_URL`         | `http://localhost:6333` | Qdrant server URL                     |
| `CIDX_QDRANT_API_KEY`     | (none)               | Qdrant API key (for Qdrant Cloud)        |
| `CIDX_QDRANT_COLLECTION`  | `codebase`           | Qdrant collection name                   |

### Metadata Store

| Variable                | Default                        | Description            |
|-------------------------|--------------------------------|------------------------|
| `CIDX_METADATA_DB_URL`  | `sqlite:///.cidx_data/metadata.db` | SQLAlchemy DB URL  |

For PostgreSQL:
```
CIDX_METADATA_DB_URL=postgresql://user:pass@localhost/cidx
```

### Retrieval

| Variable                    | Default                                   | Description                       |
|-----------------------------|-------------------------------------------|-----------------------------------|
| `CIDX_DEFAULT_SEARCH_MODE`  | `hybrid`                                  | Default search mode               |
| `CIDX_RETRIEVAL_TOP_K`      | `20`                                      | Candidates from vector search     |
| `CIDX_RESULTS_TOP_N`        | `10`                                      | Final results after re-ranking    |
| `CIDX_RERANKER_ENABLED`     | `false`                                   | Enable cross-encoder re-ranking   |
| `CIDX_RERANKER_MODEL`       | `cross-encoder/ms-marco-MiniLM-L-6-v2`   | Cross-encoder model name          |

### File Watching

| Variable                       | Default | Description                                |
|--------------------------------|---------|--------------------------------------------|
| `CIDX_WATCH_DEBOUNCE_SECONDS`  | `2.0`   | Wait after last file event before re-index |

---

## Environment-Specific Profiles

### Local Development (no API key, local embedding)

```env
CIDX_EMBED_PROVIDER=sentence_transformers
CIDX_ST_MODEL_NAME=BAAI/bge-small-en-v1.5
CIDX_VECTOR_BACKEND=chroma
CIDX_DEBUG=true
CIDX_LOG_LEVEL=DEBUG
```

### Production with OpenAI

```env
CIDX_EMBED_PROVIDER=openai
CIDX_OPENAI_API_KEY=sk-...
CIDX_OPENAI_EMBED_MODEL=text-embedding-3-small
CIDX_VECTOR_BACKEND=qdrant
CIDX_QDRANT_URL=https://your-cluster.qdrant.io
CIDX_QDRANT_API_KEY=...
CIDX_METADATA_DB_URL=postgresql://cidx:password@db/cidx
CIDX_API_KEY=your-strong-random-key
CIDX_API_WORKERS=4
CIDX_RERANKER_ENABLED=true
```

### GPU-Accelerated (Apple Silicon)

```env
CIDX_EMBED_PROVIDER=sentence_transformers
CIDX_ST_MODEL_NAME=BAAI/bge-large-en-v1.5
CIDX_ST_DEVICE=mps
CIDX_ST_BATCH_SIZE=128
```
