"""
retrieval/engine.py
====================
RetrievalEngine: orchestrates the full retrieval pipeline.

Responsibilities
----------------
  1. Route the query to the correct retriever (semantic/keyword/hybrid).
  2. Apply post-retrieval filters (path prefix, kind, symbol name).
  3. Optionally re-rank with the cross-encoder.
  4. Return a SearchResponse with timing information.
"""

from __future__ import annotations

import time

from ..config import SearchMode, settings
from ..models.search import SearchQuery, SearchResponse, SearchResult
from .hybrid import HybridRetriever
from .keyword import KeywordRetriever
from .reranker import CrossEncoderReranker
from .semantic import SemanticRetriever


class RetrievalEngine:
    """
    High-level retrieval facade used by both the API and CLI.
    """

    def __init__(
        self,
        semantic:  SemanticRetriever,
        keyword:   KeywordRetriever,
        hybrid:    HybridRetriever,
        reranker:  CrossEncoderReranker | None = None,
    ) -> None:
        self._semantic = semantic
        self._keyword  = keyword
        self._hybrid   = hybrid
        self._reranker = reranker

    async def search(self, query: SearchQuery) -> SearchResponse:
        """
        Execute the full retrieval pipeline and return a SearchResponse.
        """
        t0 = time.perf_counter()

        # 1. Route to the correct retriever
        if query.mode == SearchMode.SEMANTIC:
            candidates = await self._semantic.retrieve(
                query, top_k=settings.retrieval_top_k
            )
        elif query.mode == SearchMode.KEYWORD:
            candidates = await self._keyword.retrieve(
                query, top_k=settings.retrieval_top_k
            )
        else:  # HYBRID
            candidates = await self._hybrid.retrieve(
                query, top_k=settings.retrieval_top_k
            )

        # 2. Post-retrieval filters (applied after ANN to avoid backend-specific logic)
        candidates = self._apply_filters(query, candidates)

        # 3. Optional re-ranking
        if settings.reranker_enabled and self._reranker:
            candidates = await self._reranker.rerank(
                query.text, candidates, top_n=query.top_k
            )
        else:
            candidates = candidates[: query.top_k]

        # 4. Build response
        results = [
            SearchResult(
                chunk=chunk.model_dump(exclude={"chunk_id"}),
                score=round(score, 6),
                rank=rank + 1,
                score_breakdown=chunk.extra.pop("score_breakdown", {}),
            )
            for rank, (chunk, score) in enumerate(candidates)
        ]

        latency_ms = (time.perf_counter() - t0) * 1000

        return SearchResponse(
            query=query.text,
            mode=query.mode,
            results=results,
            total=len(results),
            latency_ms=round(latency_ms, 2),
        )

    # ------------------------------------------------------------------
    def _apply_filters(
        self,
        query: SearchQuery,
        candidates: list,
    ) -> list:
        """Apply post-retrieval Python-side filters."""
        result = []
        for chunk, score in candidates:
            # Filter by path prefix
            if query.filter_paths:
                if not any(chunk.rel_path.startswith(p) for p in query.filter_paths):
                    continue

            # Filter by chunk kind
            if query.filter_kinds:
                if chunk.kind not in query.filter_kinds:
                    continue

            # Filter by symbol name substring
            if query.filter_symbols:
                name = chunk.symbol_name or ""
                if not any(s.lower() in name.lower() for s in query.filter_symbols):
                    continue

            result.append((chunk, score))

        return result
