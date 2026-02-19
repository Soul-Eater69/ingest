# Deployment Guide

## Local Development

```bash
# 1. Install dependencies
pip install -e ".[all,dev]"

# 2. Copy and edit configuration
cp .env.example .env
# Edit .env as needed

# 3. Index a codebase
cidx index /path/to/your/repo

# 4. Search
cidx search "function that handles authentication"

# 5. (optional) Start the API server
cidx serve
```

---

## Docker Compose (Recommended)

```bash
# 1. Set the repo path to index
export CIDX_REPO_PATH=/path/to/your/repo

# 2. Start the API server
docker compose up -d

# 3. Index the repo
docker compose run --rm api cidx index /repo

# 4. Query the API
curl -X POST http://localhost:8000/search \
     -H "Content-Type: application/json" \
     -d '{"text": "JWT validation", "top_k": 5}'
```

---

## Production Architecture

```
                         ┌─────────────────────────────────────┐
                         │           Kubernetes Cluster         │
                         │                                      │
   ┌─────────┐           │  ┌──────────────────────────────┐   │
   │  Load   │           │  │    API Deployment (3 pods)    │   │
   │Balancer │──────────▶│  │                              │   │
   └─────────┘           │  │  cidx-api:latest             │   │
                         │  │  replicas: 3                 │   │
                         │  │  resources:                  │   │
                         │  │    cpu: 1000m                │   │
                         │  │    memory: 2Gi               │   │
                         │  └──────────────────────────────┘   │
                         │             │                        │
                         │     ┌───────┴────────┐              │
                         │     ▼                ▼              │
                         │  ┌──────────┐  ┌──────────────┐    │
                         │  │ Qdrant   │  │  PostgreSQL   │    │
                         │  │(StatefulS│  │  (StatefulS)  │    │
                         │  │   Set)   │  │               │    │
                         │  └──────────┘  └──────────────┘    │
                         └─────────────────────────────────────┘
```

### Kubernetes Manifest Snippets

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cidx-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: cidx-api
  template:
    spec:
      containers:
      - name: api
        image: codebase-indexer:1.0.0
        ports:
        - containerPort: 8000
        env:
        - name: CIDX_EMBED_PROVIDER
          value: "openai"
        - name: CIDX_OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: cidx-secrets
              key: openai-api-key
        - name: CIDX_VECTOR_BACKEND
          value: "qdrant"
        - name: CIDX_QDRANT_URL
          value: "http://qdrant-svc:6333"
        - name: CIDX_METADATA_DB_URL
          valueFrom:
            secretKeyRef:
              name: cidx-secrets
              key: db-url
        - name: CIDX_API_KEY
          valueFrom:
            secretKeyRef:
              name: cidx-secrets
              key: api-key
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 60
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2000m"
            memory: "4Gi"
```

---

## Indexing Strategies for Large Codebases

### Strategy 1: Initial Full Index

Index the entire codebase once.  For a large monorepo (~500k LOC):
- With sentence-transformers on CPU: ~20-40 minutes
- With OpenAI API: ~5-10 minutes (depends on rate limits)
- With sentence-transformers on GPU: ~3-5 minutes

```bash
# Full index with progress visible
cidx index /path/to/monorepo --verbose
```

### Strategy 2: Incremental Re-index

After the initial index, only changed files are re-indexed.
A typical developer's daily work touches 10-50 files.
Incremental re-index: < 30 seconds.

```bash
# Incremental (default – only re-indexes changed files)
cidx index /path/to/repo
```

### Strategy 3: CI/CD Pipeline Integration

```yaml
# .github/workflows/reindex.yml
name: Re-index on push
on:
  push:
    branches: [main]

jobs:
  reindex:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - run: |
        curl -X POST https://your-cidx-server/index \
             -H "X-API-Key: ${{ secrets.CIDX_API_KEY }}" \
             -H "Content-Type: application/json" \
             -d '{"path": "/workspace", "force": false}'
```

### Strategy 4: Live Watch (Development)

```bash
# Re-indexes on every file save (no manual re-index needed)
cidx watch /path/to/repo
```

---

## Performance Tuning

### Embedding Speed

| Provider                     | Speed (1k chunks) | Cost          |
|------------------------------|-------------------|---------------|
| OpenAI text-embedding-3-small | ~10s (API bound) | $0.02/1M tok  |
| BAAI/bge-small-en-v1.5 (CPU)  | ~120s             | Free          |
| BAAI/bge-base-en-v1.5 (CPU)   | ~180s             | Free          |
| BAAI/bge-base-en-v1.5 (GPU)   | ~15s              | Free          |

### Retrieval Latency

| Configuration           | Latency (p50) | Latency (p99) |
|-------------------------|---------------|---------------|
| Semantic only (no rerank)| 15ms         | 40ms          |
| Hybrid (no rerank)       | 20ms          | 55ms          |
| Hybrid + cross-encoder   | 80ms          | 150ms         |

### Scaling Recommendations

| Index Size | Recommended Setup                                          |
|------------|------------------------------------------------------------|
| < 10k chunks | SQLite + ChromaDB, single worker                         |
| 10k-500k   | SQLite + ChromaDB or Qdrant, 2-4 workers                  |
| > 500k     | PostgreSQL + Qdrant cluster, horizontal scaling           |

---

## Security Checklist

- [ ] Set `CIDX_API_KEY` to a strong random key in production
- [ ] Use HTTPS (terminate TLS at the load balancer or with a reverse proxy)
- [ ] Mount codebase volumes as `:ro` (read-only) in Docker
- [ ] Store API keys in a secrets manager (Vault, AWS Secrets Manager, k8s Secrets)
- [ ] Enable CORS only for known origins (`CIDX_CORS_ORIGINS=["https://your-app.com"]`)
- [ ] Run the container as a non-root user (already done in the Dockerfile)
- [ ] Rotate the API key regularly
