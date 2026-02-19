"""
models/search.py
================
Request / response models for the search (retrieval) layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .chunk import ChunkKind, Language
from ..config import SearchMode


class SearchQuery(BaseModel):
    """
    A query submitted by the user.

    Attributes
    ----------
    text         The natural-language or code query string.
    mode         Retrieval strategy (semantic | keyword | hybrid).
    top_k        Number of results to return.
    min_score    Minimum similarity score threshold (0.0–1.0).
                 Results below this are discarded.

    Filters – all optional, narrow the candidate set before scoring:
    filter_language    Only return chunks from files of this language.
    filter_paths       Only return chunks from files whose rel_path starts
                       with one of these prefixes.
    filter_kinds       Only return chunks of these structural kinds.
    filter_symbols     Only return chunks whose symbol_name contains one
                       of these substrings (case-insensitive).
    """

    text:  str
    mode:  SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # optional filters
    filter_language: Optional[Language] = None
    filter_paths:    list[str] = Field(default_factory=list)
    filter_kinds:    list[ChunkKind] = Field(default_factory=list)
    filter_symbols:  list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    """
    A single retrieved chunk with its relevance score.

    Attributes
    ----------
    chunk        The retrieved CodeChunk.
    score        Normalised relevance score (0.0–1.0, higher is better).
    rank         1-based position in the result list.
    score_breakdown
                 Optional dict showing sub-scores for each signal
                 (e.g., {"semantic": 0.82, "bm25": 0.71, "rrf": 0.93}).
    """

    chunk:  dict                        # serialised CodeChunk
    score:  float
    rank:   int
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Envelope returned by POST /search."""

    query:   str
    mode:    SearchMode
    results: list[SearchResult]
    total:   int
    latency_ms: float = 0.0
