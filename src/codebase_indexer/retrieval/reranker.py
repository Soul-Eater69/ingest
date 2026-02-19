"""
retrieval/reranker.py
=====================
Cross-encoder re-ranking for higher precision.

Two-stage retrieval
-------------------
Stage 1 (retrieval)  : Bi-encoder embedding + ANN.  Fast but imprecise.
                       Returns top-K candidates (e.g., 20).
Stage 2 (re-ranking) : Cross-encoder scores each (query, candidate) pair.
                       Slower but much more precise.
                       Returns top-N final results (e.g., 10).

Why the two-stage approach?
  Cross-encoders jointly encode the query and each candidate, allowing
  them to model fine-grained token-level interactions.  This makes them
  significantly more accurate than bi-encoders but also much slower –
  O(K) inference calls vs O(1) for ANN.  By using a bi-encoder to
  narrow from ALL chunks down to K candidates, then re-ranking only K,
  we get near-cross-encoder quality at manageable latency.

Model
-----
Default: cross-encoder/ms-marco-MiniLM-L-6-v2
  - 22M parameters
  - ~10ms / pair on CPU
  - Trained on MS MARCO passage ranking

Disable re-ranking by setting CIDX_RERANKER_ENABLED=false (default).
"""

from __future__ import annotations

from typing import Optional

from ..config import settings
from ..models.chunk import CodeChunk
from ..utils.concurrency import run_in_executor
from ..utils.logging import get_logger

logger = get_logger(__name__)


class CrossEncoderReranker:
    """Re-rank retrieved chunks using a cross-encoder model."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = model_name or settings.reranker_model
        self._model: object | None = None

    def _load_model(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore[import]
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
            logger.info("loading cross-encoder model", extra={"model": self._model_name})
            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[CodeChunk, float]],
        top_n: int | None = None,
    ) -> list[tuple[CodeChunk, float]]:
        """
        Re-score candidates and return the top_n results.

        Parameters
        ----------
        query:      The original query text.
        candidates: List of (chunk, score) from the retrieval stage.
        top_n:      Number of results to return after re-ranking.

        Returns
        -------
        List of (chunk, rerank_score) sorted by rerank_score descending.
        """
        if not candidates:
            return []

        n = top_n or settings.results_top_n

        def _score() -> list[float]:
            model = self._load_model()
            pairs = [(query, chunk.full_text_for_embedding)
                     for chunk, _ in candidates]
            scores = model.predict(pairs)  # type: ignore[attr-defined]
            return scores.tolist() if hasattr(scores, "tolist") else list(scores)

        try:
            scores = await run_in_executor(_score)
        except Exception as exc:
            logger.warning("reranker failed, using original order", extra={"error": str(exc)})
            return candidates[:n]

        # Pair and sort by reranker score
        paired = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        return [(chunk, float(score)) for (chunk, _), score in paired[:n]]
