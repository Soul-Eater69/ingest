# API Reference

## Base URL

```
http://localhost:8000
```

Interactive docs available at `/docs` (Swagger UI) and `/redoc`.

---

## Authentication

When `CIDX_API_KEY` is set, all requests (except `/health`) must include:

```
X-API-Key: your-secret-key
```

---

## Endpoints

### Health

#### `GET /health`

Liveness probe.  Always returns 200 if the server is running.

**Response:**
```json
{"status": "ok"}
```

---

#### `GET /info`

Index statistics and configuration summary.

**Response:**
```json
{
  "total_files": 847,
  "total_chunks": 12453,
  "total_tokens": 3841920,
  "files_by_language": {
    "python": 312,
    "typescript": 198,
    "go": 145
  },
  "chunks_by_kind": {
    "function": 4821,
    "method": 5103,
    "class": 892,
    "import": 847,
    "module": 790
  },
  "vector_backend": "chroma",
  "embed_provider": "sentence_transformers",
  "embed_model": "BAAI/bge-base-en-v1.5",
  "last_indexed_at": "2024-01-15T14:23:11",
  "index_size_bytes": 0
}
```

---

### Indexing

#### `POST /index`

Start a background indexing job.

**Request body:**
```json
{
  "path": "/absolute/path/to/repo",
  "force": false
}
```

| Field   | Type    | Required | Description                                          |
|---------|---------|----------|------------------------------------------------------|
| `path`  | string  | yes      | Absolute path to the repository root on the server   |
| `force` | boolean | no       | Re-index all files even if content hash is unchanged |

**Response (202 Accepted):**
```json
{
  "job_id": "a1b2c3d4",
  "message": "Indexing started for /path/to/repo. Poll /index/status/a1b2c3d4"
}
```

---

#### `GET /index/status/{job_id}`

Poll indexing job progress.

**Response:**
```json
{
  "job_id": "a1b2c3d4",
  "status": "done",
  "files_indexed": 847,
  "chunks_indexed": 12453,
  "error": null
}
```

| `status` value | Meaning                          |
|----------------|----------------------------------|
| `running`      | Job is in progress               |
| `done`         | Completed successfully           |
| `error`        | Failed – see `error` field       |

---

#### `DELETE /index`

Delete the entire index.  **Irreversible.**

---

### Search

#### `POST /search`

Query the indexed codebase.

**Request body:**
```json
{
  "text": "function that validates JWT tokens",
  "mode": "hybrid",
  "top_k": 10,
  "min_score": 0.0,
  "filter_language": "python",
  "filter_paths": ["src/auth/"],
  "filter_kinds": ["function", "method"],
  "filter_symbols": ["validate", "verify"]
}
```

| Field             | Type             | Default    | Description                                    |
|-------------------|------------------|------------|------------------------------------------------|
| `text`            | string           | required   | Natural-language or code query                 |
| `mode`            | enum             | `hybrid`   | `semantic` / `keyword` / `hybrid`              |
| `top_k`           | integer (1-100)  | `10`       | Number of results to return                    |
| `min_score`       | float (0.0-1.0)  | `0.0`      | Minimum score threshold                        |
| `filter_language` | string           | none       | Only return chunks from this language          |
| `filter_paths`    | string[]         | `[]`       | Only return chunks under these path prefixes   |
| `filter_kinds`    | string[]         | `[]`       | Only return chunks of these kinds              |
| `filter_symbols`  | string[]         | `[]`       | Symbol name must contain one of these (case-insensitive) |

**Response:**
```json
{
  "query": "function that validates JWT tokens",
  "mode": "hybrid",
  "total": 5,
  "latency_ms": 42.3,
  "results": [
    {
      "rank": 1,
      "score": 0.9423,
      "score_breakdown": {
        "semantic_rank": 1,
        "keyword_rank": 2,
        "rrf_score": 0.0325
      },
      "chunk": {
        "rel_path": "src/auth/jwt.py",
        "language": "python",
        "kind": "method",
        "symbol_name": "JWTValidator.validate",
        "start_line": 9,
        "end_line": 22,
        "text": "def validate(self, token: str) -> dict:\n    ...",
        "docstring": "Validate the JWT signature and claims.",
        "context_before": "class JWTValidator:",
        "token_count": 87
      }
    }
  ]
}
```

---

## Search Mode Guide

| Mode       | When to Use                                                         |
|------------|---------------------------------------------------------------------|
| `semantic` | Conceptual queries: "error handling logic", "caching strategy"      |
| `keyword`  | Exact identifiers: `UserService.authenticate`, `parseJWT`, `db_pool`|
| `hybrid`   | Default – combines both for best overall results                    |

---

## Error Responses

All errors follow the standard FastAPI format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning                              |
|--------|--------------------------------------|
| 400    | Invalid request (bad path, etc.)     |
| 401    | Missing or invalid API key           |
| 404    | Resource not found (job ID, etc.)    |
| 422    | Validation error (bad request body)  |
| 500    | Internal server error                |
