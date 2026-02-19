# Architecture Guide

## Overview

The Codebase Indexer is a production-ready system that transforms raw source
code into a searchable vector index, enabling semantic search, RAG pipelines,
and AI code generation tools.

---

## System-Level Architecture

```
                        ┌─────────────────────────────────────────────────────────┐
                        │                 CODEBASE INDEXER                        │
                        │                                                         │
   ┌──────────┐         │   ┌───────────┐   ┌──────────┐   ┌────────────────┐   │
   │  Source  │─────────┼──▶│ Ingestion │──▶│  Parser  │──▶│    Chunker     │   │
   │   Code   │         │   │  Layer    │   │  Layer   │   │    Layer       │   │
   │  (disk)  │         │   └───────────┘   └──────────┘   └───────┬────────┘   │
   └──────────┘         │                                           │            │
                        │                                           ▼            │
   ┌──────────┐         │                                  ┌────────────────┐   │
   │   Git    │─────────┼──▶ (metadata)                    │   Embedding    │   │
   │   Repo   │         │                                  │    Layer       │   │
   └──────────┘         │                                  └───────┬────────┘   │
                        │                                          │             │
                        │               ┌──────────────────────────┘             │
                        │               ▼                                        │
                        │   ┌───────────────────────┐                           │
                        │   │     Storage Layer      │                           │
                        │   │  ┌─────────────────┐  │                           │
                        │   │  │  Vector Store   │  │  ← embedding vectors       │
                        │   │  │ (Chroma/Qdrant) │  │                           │
                        │   │  └─────────────────┘  │                           │
                        │   │  ┌─────────────────┐  │                           │
                        │   │  │ Metadata Store  │  │  ← chunk text + metadata  │
                        │   │  │    (SQLite)     │  │                           │
                        │   │  └─────────────────┘  │                           │
                        │   │  ┌─────────────────┐  │                           │
                        │   │  │   BM25 Index    │  │  ← keyword search index   │
                        │   │  └─────────────────┘  │                           │
                        │   └───────────────────────┘                           │
                        │                                                        │
                        │   ┌───────────────────────┐                           │
                        │   │   Retrieval Layer      │                           │
                        │   │  Semantic + Keyword    │◀── Query                 │
                        │   │  Hybrid (RRF fusion)   │                           │
                        │   │  Re-ranker (optional)  │──▶ Ranked Results        │
                        │   └───────────────────────┘                           │
                        │                                                        │
                        │   ┌─────────────────────────────────────────────────┐ │
                        │   │              Interface Layer                     │ │
                        │   │   REST API (FastAPI)  │  CLI (Click)             │ │
                        │   └─────────────────────────────────────────────────┘ │
                        └─────────────────────────────────────────────────────────┘
```

---

## Indexing Data Flow

This diagram shows the exact sequence of transformations a source file
undergoes from raw bytes to searchable vectors.

```
 RAW FILE ON DISK
      │
      │  read_text(encoding="utf-8")
      ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │ SourceFile                                                       │
 │   abs_path = /repo/src/auth/jwt.py                              │
 │   rel_path = src/auth/jwt.py                                    │
 │   language = PYTHON                                             │
 │   size     = 4,218 bytes                                        │
 │   content  = "import jwt\n\nclass JWTValidator:\n ..."          │
 │   content_hash = "a1b2c3d4..."   ← SHA-256, change detection   │
 └──────────────────────────────┬──────────────────────────────────┘
                                │
                                │  parser.parse(content, rel_path)
                                │  (runs in thread pool, CPU-bound)
                                ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │ ParsedSymbol[]                                                   │
 │  [0] kind=IMPORT   name=__imports__    lines=1-2               │
 │  [1] kind=CLASS    name=JWTValidator   lines=4-48              │
 │       └─ [0] kind=METHOD name=validate    lines=9-22           │
 │       └─ [1] kind=METHOD name=decode      lines=24-38          │
 │       └─ [2] kind=METHOD name=_verify_exp lines=40-48          │
 └──────────────────────────────┬──────────────────────────────────┘
                                │
                                │  chunker.chunk(source, symbols)
                                │  HybridChunker: semantic first,
                                │  sliding window for large symbols
                                ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │ CodeChunk[]                                                      │
 │  [0] chunk_id=a1b2  kind=IMPORT    symbol=__imports__           │
 │  [1] chunk_id=c3d4  kind=CLASS     symbol=JWTValidator          │
 │       context_before="" (top-level class)                       │
 │  [2] chunk_id=e5f6  kind=METHOD    symbol=JWTValidator.validate │
 │       context_before="class JWTValidator:"                      │
 │  [3] chunk_id=g7h8  kind=METHOD    symbol=JWTValidator.decode   │
 │       context_before="class JWTValidator:"                      │
 │  [4] chunk_id=i9j0  kind=METHOD    symbol=JWTValidator._verify  │
 │       context_before="class JWTValidator:"                      │
 └──────────────────────────────┬──────────────────────────────────┘
                                │
                                │  embedder.embed([chunk.full_text_for_embedding
                                │                  for chunk in chunks])
                                │  Batched, cached, async
                                ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │ Embedding vectors  (float32[768] per chunk)                      │
 │  [0] [0.021, -0.134, 0.892, ...]   ← IMPORT chunk              │
 │  [1] [0.341, -0.012, 0.103, ...]   ← CLASS chunk               │
 │  [2] [0.782, -0.234, 0.041, ...]   ← validate method           │
 │  [3] [0.512, -0.789, 0.234, ...]   ← decode method             │
 │  [4] [0.123, -0.456, 0.789, ...]   ← _verify_exp method        │
 └──────────────────────────────┬──────────────────────────────────┘
                                │
                       ┌────────┴────────┐
                       ▼                 ▼
            ┌──────────────────┐   ┌──────────────────┐
            │   Vector Store   │   │  Metadata Store  │
            │  (ChromaDB)      │   │  (SQLite)        │
            │                  │   │                  │
            │  chunk_id → vec  │   │  chunk_id → {    │
            │  + small flat    │   │    rel_path,     │
            │    metadata      │   │    language,     │
            │    for filtering │   │    kind,         │
            │                  │   │    symbol_name,  │
            │                  │   │    lines,        │
            │                  │   │    text,         │
            │                  │   │    docstring,    │
            │                  │   │    git_commit    │
            │                  │   │  }               │
            └──────────────────┘   └──────────────────┘
```

---

## Retrieval / Query Flow

```
 USER QUERY: "function that validates JWT token expiration"
      │
      │
      │  ┌──────────────────────────────────────────────────────┐
      │  │                  HYBRID RETRIEVAL                     │
      │  │                                                      │
      └─▶│  ┌─────────────────────┐  ┌──────────────────────┐  │
         │  │  SEMANTIC PATH      │  │  KEYWORD PATH        │  │
         │  │                     │  │                      │  │
         │  │  1. embed(query)    │  │  1. tokenize(query)  │  │
         │  │  2. ANN search in   │  │  2. BM25 score each  │  │
         │  │     vector store    │  │     indexed chunk    │  │
         │  │  3. Return top-20   │  │  3. Return top-20    │  │
         │  │     with cosine     │  │     with BM25 score  │  │
         │  │     similarity      │  │                      │  │
         │  └──────────┬──────────┘  └──────────┬───────────┘  │
         │             │                        │               │
         │             └──────────┬─────────────┘               │
         │                        │                             │
         │             RECIPROCAL RANK FUSION                   │
         │             RRF(d) = 1/(60+sem_rank)                 │
         │                    + 1/(60+kw_rank)                  │
         │                        │                             │
         │                        ▼                             │
         │             Fused ranking of top-20                  │
         └──────────────────────────────────────────────────────┘
                                  │
                                  │  (optional) Cross-encoder re-ranking
                                  │  Re-scores each (query, chunk) pair
                                  │  Returns top-10
                                  ▼
         ┌────────────────────────────────────────────────────────┐
         │  SearchResponse                                          │
         │                                                         │
         │  [1] score=0.94  src/auth/jwt.py:40-48                 │
         │      JWTValidator._verify_exp  (method)                 │
         │      "Verify that the JWT has not expired..."           │
         │                                                         │
         │  [2] score=0.87  src/auth/jwt.py:9-22                  │
         │      JWTValidator.validate  (method)                    │
         │      "Validate the JWT signature and claims..."         │
         │                                                         │
         │  [3] score=0.71  src/middleware/auth.py:15-30          │
         │      require_auth  (function)                           │
         │      "Middleware that validates the Bearer token..."    │
         └────────────────────────────────────────────────────────┘
```

---

## Component Interaction Diagram

```
                    ┌──────────────────────────────────────────────────┐
                    │                 IndexPipeline                     │
                    │  (orchestrates all layers during indexing)        │
                    │                                                   │
                    │  index_directory(root)                           │
                    │        │                                         │
                    │        ├──▶ FileCrawler.crawl()  ──────────────┐ │
                    │        │         (async generator)             │ │
                    │        │                                       │ │
                    │        │   for each SourceFile:                │ │
                    │        │       ├──▶ GitIndexer.get_blame()     │ │
                    │        │       ├──▶ Parser.parse()             │ │
                    │        │       │     (in thread pool)          │ │
                    │        │       └──▶ Chunker.chunk()            │ │
                    │        │                                       │ │
                    │        ├──▶ Embedder.embed(batch)              │ │
                    │        │         (batched, cached, async)      │ │
                    │        │                                       │ │
                    │        ├──▶ VectorStore.upsert()               │ │
                    │        └──▶ MetadataStore.upsert_chunks()      │ │
                    └──────────────────────────────────────────────────┘

                    ┌──────────────────────────────────────────────────┐
                    │                RetrievalEngine                    │
                    │  (orchestrates all layers during search)          │
                    │                                                   │
                    │  search(query)                                   │
                    │        │                                         │
                    │        ├──▶ SemanticRetriever                    │
                    │        │       │──▶ Embedder.embed_one(query)    │
                    │        │       │──▶ VectorStore.search()         │
                    │        │       └──▶ MetadataStore.get_chunks()   │
                    │        │                                         │
                    │        ├──▶ KeywordRetriever                     │
                    │        │       │──▶ BM25.get_scores(tokens)      │
                    │        │       └──▶ MetadataStore.get_chunks()   │
                    │        │                                         │
                    │        ├──▶ HybridRetriever (RRF fusion)         │
                    │        │                                         │
                    │        ├──▶ [filters: language, path, kind]      │
                    │        │                                         │
                    │        └──▶ CrossEncoderReranker (optional)      │
                    └──────────────────────────────────────────────────┘
```

---

## Chunking Strategy Comparison

```
  FILE: src/models/user.py  (200 lines)

  ┌───────────────────────────────────────────────────────────────────┐
  │ SEMANTIC CHUNKING                                                  │
  │                                                                   │
  │   Chunk 1: IMPORT block        lines 1-5                         │
  │   Chunk 2: class User          lines 7-15  (header only)         │
  │   Chunk 3: User.__init__       lines 10-22 (method)              │
  │   Chunk 4: User.validate       lines 24-45 (method)              │
  │   Chunk 5: User.to_dict        lines 47-58 (method)              │
  │   Chunk 6: def get_user_by_id  lines 61-80 (function)            │
  │   Chunk 7: def create_user     lines 82-120 (function)           │
  │   ...                                                             │
  │                                                                   │
  │   Pro:  Each chunk has clear semantics → better retrieval         │
  │   Con:  Large functions produce oversized chunks                  │
  └───────────────────────────────────────────────────────────────────┘

  ┌───────────────────────────────────────────────────────────────────┐
  │ SLIDING WINDOW CHUNKING  (window=512 tokens, overlap=64 tokens)   │
  │                                                                   │
  │   Chunk 1: lines 1-42   [0 tokens overlap]                       │
  │   Chunk 2: lines 36-78  [64 token overlap with chunk 1]          │
  │   Chunk 3: lines 72-114 [64 token overlap with chunk 2]          │
  │   Chunk 4: lines 108-150 ...                                      │
  │   Chunk 5: lines 144-186 ...                                      │
  │   Chunk 6: lines 180-200 ...                                      │
  │                                                                   │
  │   Pro:  Bounded chunk size, guaranteed coverage                   │
  │   Con:  Chunks split functions → lose semantic meaning            │
  └───────────────────────────────────────────────────────────────────┘

  ┌───────────────────────────────────────────────────────────────────┐
  │ HYBRID CHUNKING  (recommended)                                    │
  │                                                                   │
  │   Semantic first:                                                 │
  │     Chunk 1: User.__init__  (80 tokens)   → keep as-is           │
  │     Chunk 2: User.validate  (200 tokens)  → keep as-is           │
  │     Chunk 7: create_user    (1,500 tokens) → TOO BIG, split:     │
  │                                                                   │
  │   Sliding fallback for oversized symbols:                         │
  │     Chunk 7a: create_user [part 0]  lines 82-114  (512 tokens)  │
  │     Chunk 7b: create_user [part 1]  lines 108-140 (512 tokens)  │
  │     Chunk 7c: create_user [part 2]  lines 136-158 (512 tokens)  │
  │                                                                   │
  │   Pro:  Best of both worlds                                       │
  │   Pro:  Symbol metadata preserved on sub-chunks                  │
  └───────────────────────────────────────────────────────────────────┘
```

---

## Embedding Text Construction

The exact string fed to the embedding model matters enormously for retrieval
quality.  We prepend a structured header so the model sees context it wouldn't
have from bare code alone:

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ EMBEDDING INPUT for chunk: JWTValidator.validate                  │
  │                                                                  │
  │  Line 1 (header):                                                │
  │    # src/auth/jwt.py | python | method: JWTValidator.validate    │
  │                                                                  │
  │  Lines 2-N (context_before):                                     │
  │    class JWTValidator:                                           │
  │        """Validates JWT tokens issued by our auth service."""    │
  │                                                                  │
  │  Lines N+1-M (actual chunk text):                                │
  │    def validate(self, token: str) -> dict:                       │
  │        """Validate the JWT signature and claims.                 │
  │                                                                  │
  │        Args:                                                     │
  │            token: Raw JWT string (Bearer token without prefix)   │
  │        Returns:                                                   │
  │            Decoded payload dict if valid.                        │
  │        Raises:                                                   │
  │            InvalidTokenError: If signature or claims are bad.    │
  │        """                                                       │
  │        try:                                                      │
  │            payload = jwt.decode(token, self.secret, ...)         │
  │            self._verify_exp(payload)                             │
  │            return payload                                        │
  │        except jwt.ExpiredSignatureError:                         │
  │            raise InvalidTokenError("Token has expired")          │
  │                                                                  │
  │  Why this works:                                                 │
  │    - The header gives the model the file path and language       │
  │    - The class context shows this is a method inside JWTValidator│
  │    - The docstring provides natural-language description         │
  │    - Together they dramatically improve retrieval precision      │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Change Detection (Incremental Re-indexing)

```
  FIRST RUN:
    ┌────────────┐    hash = SHA-256(content)    ┌──────────────────┐
    │ file.py    │──────────────────────────────▶│ metadata.db      │
    │ (changed)  │                               │ file.py → a1b2c3 │
    └────────────┘                               └──────────────────┘

  SECOND RUN:
    ┌────────────┐    hash = SHA-256(content)
    │ file.py    │──────────────────────────────▶ hash == a1b2c3?
    │ (unchanged)│                                    │
    └────────────┘                                   YES → SKIP
                                                      │
                                                      NO  → re-index

  RESULT:
    Only changed files are re-indexed.
    A 100k file codebase with 10 changed files re-indexes in seconds
    instead of minutes.
```

---

## BM25 + RRF Fusion Details

```
  Query: "parse CSV with header"

  Semantic results:        BM25 results:
  ┌─────────────────┐      ┌─────────────────┐
  │ rank │ chunk_id │      │ rank │ chunk_id │
  │  1   │   A      │      │  1   │   C      │
  │  2   │   B      │      │  2   │   A      │
  │  3   │   C      │      │  3   │   D      │
  │  4   │   D      │      │  4   │   E      │
  └─────────────────┘      └─────────────────┘

  RRF score (k=60):

    A: 1/(60+1) + 1/(60+2) = 0.01639 + 0.01613 = 0.03252
    B: 1/(60+2) + 1/(60+∞) = 0.01613 + 0.00000 = 0.01613
    C: 1/(60+3) + 1/(60+1) = 0.01587 + 0.01639 = 0.03226
    D: 1/(60+4) + 1/(60+3) = 0.01563 + 0.01587 = 0.03150
    E: 1/(60+∞) + 1/(60+4) = 0.00000 + 0.01563 = 0.01563

  Final ranking: A (0.0325) > C (0.0323) > D (0.0315) > B (0.016) > E (0.016)

  Note: A appeared in BOTH systems (top in semantic, 2nd in BM25) →
        gets promoted above C (3rd semantic, 1st BM25) because it had
        consistent cross-system relevance.
```
