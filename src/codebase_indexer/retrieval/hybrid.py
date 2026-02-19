"""
retrieval/hybrid.py
====================
Hybrid retrieval using Reciprocal Rank Fusion (RRF).

What is RRF?
------------
RRF combines ranked lists from multiple retrieval systems into a single
ranked list WITHOUT requiring calibrated scores from each system.

Formula:
    RRF_score(d) = Σ_r  1 / (k + rank_r(d))

Where:
    d          = document
    r          = one retrieval system (e.g., semantic or BM25)
    rank_r(d)  = 1-based rank of document d in system r (∞ if not present)
    k          = smoothing constant (default 60, empirically validated)

Why RRF instead of linear interpolation of scores?
---------------------------------------------------
Linear interpolation (α * semantic_score + (1-α) * bm25_score) requires
tuning α and assumes both scores are on the same scale.  RRF only uses
ranks, so it's robust to scale differences and requires no tuning.

Research: "Reciprocal Rank Fusion outperforms Condorcet and individual
Rank Learning Methods" (Cormack et al., SIGIR 2009)
"""

from __future__ import annotations

from ..config import SearchMode, settings
from ..models.chunk import CodeChunk
from ..models.search import SearchQuery
from .semantic import SemanticRetriever
from .keyword import KeywordRetriever


_RRF_K = 60  # smoothing constant – standard value from the original paper


def _rrf_score(rank: int) -> float:
    """Compute RRF contribution for a single ranked result."""
    return 1.0 / (_RRF_K + rank)


class HybridRetriever:
    """
    Combines semantic and keyword retrieval with RRF fusion.
    """

    def __init__(
        self,
        semantic: SemanticRetriever,
        keyword:  KeywordRetriever,
    ) -> None:
        self._semantic = semantic
        self._keyword  = keyword

    async def retrieve(
        self,
        query: SearchQuery,
        top_k: int | None = None,
    ) -> list[tuple[CodeChunk, float]]:
        """
        Run both retrievers and fuse results with RRF.

        Returns list of (chunk, rrf_score) sorted by score descending.
        """
        k = top_k or settings.retrieval_top_k

        # Run both retrievers concurrently
        import asyncio
        semantic_task = asyncio.ensure_future(
            self._semantic.retrieve(query, top_k=k)
        )
        keyword_task  = asyncio.ensure_future(
            self._keyword.retrieve(query, top_k=k)
        )
        semantic_results, keyword_results = await asyncio.gather(
            semantic_task, keyword_task
        )

        # Build rank maps: chunk_id → rank (1-based)
        sem_ranks: dict[str, int] = {
            c.chunk_id: i + 1 for i, (c, _) in enumerate(semantic_results)
        }
        kw_ranks: dict[str, int] = {
            c.chunk_id: i + 1 for i, (c, _) in enumerate(keyword_results)
        }

        # Union of all seen chunk IDs
        all_ids = set(sem_ranks) | set(kw_ranks)

        # Build chunk lookup
        all_chunks: dict[str, CodeChunk] = {}
        for c, _ in semantic_results:
            all_chunks[c.chunk_id] = c
        for c, _ in keyword_results:
            all_chunks[c.chunk_id] = c

        # Compute RRF scores
        fused: list[tuple[CodeChunk, float, dict]] = []
        for cid in all_ids:
            sem_rank = sem_ranks.get(cid, len(sem_ranks) + 1000)
            kw_rank  = kw_ranks.get(cid,  len(kw_ranks)  + 1000)
            score = _rrf_score(sem_rank) + _rrf_score(kw_rank)
            chunk = all_chunks[cid]
            breakdown = {
                "semantic_rank": sem_ranks.get(cid),
                "keyword_rank":  kw_ranks.get(cid),
                "rrf_score":     round(score, 6),
            }
            fused.append((chunk, score, breakdown))

        # Sort by RRF score descending, return top_k
        fused.sort(key=lambda x: x[1], reverse=True)
        top = fused[:k]

        # Attach breakdown to chunk.extra for the API response
        results: list[tuple[CodeChunk, float]] = []
        for chunk, score, breakdown in top:
            chunk.extra["score_breakdown"] = breakdown
            results.append((chunk, score))

        return results
