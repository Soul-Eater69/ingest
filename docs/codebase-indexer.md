# Codebase Indexer

A production-ready system that indexes source code repositories for
semantic search, RAG (Retrieval-Augmented Generation), and AI code
generation pipelines.

---

## What it does

```
  Your codebase ──▶ Parse ──▶ Chunk ──▶ Embed ──▶ Store
                                                      │
  Your query   ──▶ Embed ──▶ Search ──▶ Re-rank ──▶ Results
```

1. **Crawls** your repository, detects file languages, and skips unchanged files.
2. **Parses** each file with a language-specific AST parser to extract functions,
   classes, and methods as named symbols.
3. **Chunks** symbols into embedding-sized pieces (512 tokens by default), adding
   structured headers and context so the embedding model understands the code.
4. **Embeds** chunks using your choice of OpenAI or a local sentence-transformers
   model (free, private, works offline).
5. **Stores** vectors in ChromaDB or Qdrant, and metadata in SQLite or PostgreSQL.
6. At query time, runs **hybrid search** (dense embedding + BM25) fused with
   Reciprocal Rank Fusion for best-of-both-worlds retrieval.

---

## Quick Start

### Install

```bash
pip install -e ".[all]"   # installs all optional backends
```

Or install only what you need:

```bash
pip install -e ".[chroma,local-embed]"   # ChromaDB + sentence-transformers (default)
pip install -e ".[chroma,openai]"        # ChromaDB + OpenAI embeddings
pip install -e ".[qdrant,openai,rerank]" # Qdrant + OpenAI + cross-encoder re-ranking
```

### Index a codebase

```bash
# Index the current directory
cidx index .

# Index a specific repo with verbose output
cidx index /path/to/your/repo -v

# Force re-index everything (ignores change detection)
cidx index . --force
```

### Search

```bash
# Natural-language semantic search
cidx search "function that validates JWT token expiration"

# Exact identifier search (keyword mode)
cidx search "UserService.authenticate" --mode keyword

# Filter to a language and specific files
cidx search "database connection pool" \
    --language python \
    --path-filter src/db/ \
    --top-k 5

# JSON output for scripting
cidx search "parse CSV file" --json-output | jq '.results[0].chunk.symbol_name'
```

### Start the API server

```bash
cidx serve --port 8000
# Open http://localhost:8000/docs for interactive API documentation
```

### Watch for changes (incremental re-indexing)

```bash
cidx watch /path/to/repo
# Automatically re-indexes files when they are saved
```

### View index statistics

```bash
cidx info
```

### Use Docker

```bash
# Start the API server with Docker Compose
docker compose up

# Index a repo via Docker
docker compose run --rm api cidx index /repo
```

---

## Supported Languages

| Language       | Parser type | Functions | Classes | Methods | Imports |
|----------------|-------------|-----------|---------|---------|---------|
| Python         | AST (stdlib)| ✓         | ✓       | ✓       | ✓       |
| JavaScript     | Regex       | ✓         | ✓       | –       | ✓       |
| TypeScript     | Regex       | ✓         | ✓       | –       | ✓       |
| JSX / TSX      | Regex       | ✓         | ✓       | –       | ✓       |
| Go             | Regex       | ✓         | ✓       | ✓       | ✓       |
| Rust           | Regex       | ✓         | ✓       | –       | –       |
| YAML/JSON/TOML | Generic     | –         | –       | –       | –       |
| Markdown       | Generic     | –         | –       | –       | –       |
| SQL            | Generic     | –         | –       | –       | –       |
| All others     | Generic     | –         | –       | –       | –       |

All unsupported languages fall through to the generic parser which
treats the entire file as a single chunk (still fully searchable).

---

## Configuration

All settings are environment variables prefixed with `CIDX_`.
See [docs/configuration.md](configuration.md) for the full reference.

```bash
# Minimal configuration (local, free, no API keys)
CIDX_EMBED_PROVIDER=sentence_transformers
CIDX_VECTOR_BACKEND=chroma

# Production configuration (OpenAI + Qdrant)
CIDX_EMBED_PROVIDER=openai
CIDX_OPENAI_API_KEY=sk-...
CIDX_VECTOR_BACKEND=qdrant
CIDX_QDRANT_URL=http://qdrant:6333
CIDX_METADATA_DB_URL=postgresql://cidx:pass@db/cidx
CIDX_API_KEY=strong-random-key
CIDX_RERANKER_ENABLED=true
```

---

## Using the REST API

```bash
# Index a repository
curl -X POST http://localhost:8000/index \
     -H "Content-Type: application/json" \
     -d '{"path": "/path/to/repo"}'

# Search
curl -X POST http://localhost:8000/search \
     -H "Content-Type: application/json" \
     -d '{
           "text": "JWT token validation",
           "mode": "hybrid",
           "top_k": 5,
           "filter_language": "python"
         }'

# View stats
curl http://localhost:8000/info
```

---

## Using in a RAG Pipeline

```python
import httpx

async def get_context_for_query(query: str, top_k: int = 5) -> str:
    """
    Retrieve relevant code chunks for a query.
    Returns formatted context ready to inject into an LLM prompt.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/search",
            json={"text": query, "mode": "hybrid", "top_k": top_k},
        )
        data = response.json()

    # Format chunks as context for the LLM
    context_parts = []
    for result in data["results"]:
        chunk = result["chunk"]
        context_parts.append(
            f"# {chunk['rel_path']}:{chunk['start_line']}-{chunk['end_line']}\n"
            f"# {chunk['language']} | {chunk['kind']}"
            + (f" | {chunk['symbol_name']}" if chunk.get('symbol_name') else "")
            + f"\n\n{chunk['text']}\n"
        )

    return "\n---\n".join(context_parts)


# In your LLM call:
async def answer_code_question(question: str) -> str:
    context = await get_context_for_query(question)
    prompt = f"""You are a code assistant. Use the following code context to answer the question.

<context>
{context}
</context>

Question: {question}
Answer:"""

    # Pass prompt to your LLM of choice (Claude, GPT-4, etc.)
    ...
```

---

## Architecture

See [docs/architecture.md](architecture.md) for detailed diagrams and explanations of:

- The full indexing pipeline with data-flow diagrams
- The retrieval pipeline with RRF fusion details
- Chunking strategy comparison
- Change detection mechanics
- Embedding text construction

---

## Project Structure

```
src/codebase_indexer/
├── config.py              ← All settings (Pydantic Settings)
├── pipeline.py            ← IndexPipeline orchestrator
├── cli.py                 ← CLI (cidx command)
├── main.py                ← FastAPI app entry point
│
├── models/
│   ├── chunk.py           ← CodeChunk, ChunkKind, Language
│   ├── document.py        ← SourceFile, IndexedDocument, IndexStats
│   └── search.py          ← SearchQuery, SearchResult, SearchResponse
│
├── ingestion/
│   ├── crawler.py         ← Async file-system crawler
│   ├── watcher.py         ← File watcher (watchdog)
│   ├── git_indexer.py     ← Git blame / changed files
│   └── language_detector.py ← Extension + shebang detection
│
├── parsers/
│   ├── base.py            ← BaseParser, ParsedSymbol
│   ├── python_parser.py   ← AST-based Python parser
│   ├── javascript_parser.py ← Regex JS/TS parser
│   ├── go_parser.py       ← Regex Go parser
│   ├── rust_parser.py     ← Regex Rust parser
│   ├── generic_parser.py  ← Fallback (module-level chunk)
│   └── registry.py        ← Language → parser mapping
│
├── chunking/
│   ├── semantic_chunker.py  ← One chunk per symbol
│   ├── sliding_window.py    ← Fixed-size overlapping windows
│   ├── hybrid_chunker.py    ← Semantic + sliding fallback
│   └── factory.py           ← get_chunker()
│
├── embeddings/
│   ├── base.py              ← BaseEmbedder interface
│   ├── openai_embedder.py   ← OpenAI Embeddings API
│   ├── sentence_transformer_embedder.py ← Local HuggingFace models
│   ├── cache.py             ← Disk-based embedding cache
│   └── factory.py           ← get_embedder()
│
├── storage/
│   ├── vector/
│   │   ├── base.py          ← BaseVectorStore interface
│   │   ├── chroma_store.py  ← ChromaDB adapter
│   │   └── qdrant_store.py  ← Qdrant adapter
│   ├── metadata/
│   │   ├── base.py          ← BaseMetadataStore interface
│   │   └── sqlite_store.py  ← SQLite + SQLAlchemy Core
│   └── factory.py           ← get_vector_store(), get_metadata_store()
│
├── retrieval/
│   ├── semantic.py          ← Dense embedding ANN search
│   ├── keyword.py           ← BM25 keyword search
│   ├── hybrid.py            ← RRF fusion
│   ├── reranker.py          ← Cross-encoder re-ranking
│   └── engine.py            ← RetrievalEngine orchestrator
│
├── api/
│   ├── app.py               ← FastAPI app factory + lifespan
│   ├── middleware.py        ← API key auth middleware
│   └── routes/
│       ├── health.py        ← GET /health, GET /info
│       ├── index.py         ← POST /index, GET /index/status/{id}
│       └── search.py        ← POST /search
│
└── utils/
    ├── hashing.py           ← SHA-256 helpers
    ├── logging.py           ← JSON structured logging
    └── concurrency.py       ← asyncio helpers, thread pool
```

---

## Running Tests

```bash
pytest tests/codebase_indexer/ -v

# Run only fast unit tests
pytest tests/codebase_indexer/test_parsers.py -v
pytest tests/codebase_indexer/test_models.py -v
pytest tests/codebase_indexer/test_chunking.py -v

# Run storage integration tests
pytest tests/codebase_indexer/test_storage.py -v
```
