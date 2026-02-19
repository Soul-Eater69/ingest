"""
api/routes/search.py
=====================
Search / retrieval endpoint.

POST /search  → Query the index and return ranked code chunks
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...models.search import SearchQuery, SearchResponse

router = APIRouter()


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search the indexed codebase",
)
async def search(query: SearchQuery, request: Request) -> SearchResponse:
    """
    Search the indexed codebase for code matching the query.

    ## Examples

    **Find a function by description:**
    ```json
    {"text": "function that parses CSV files", "mode": "hybrid", "top_k": 5}
    ```

    **Find by exact identifier:**
    ```json
    {"text": "parseCSVFile", "mode": "keyword", "top_k": 3}
    ```

    **Filter to Python files only:**
    ```json
    {
        "text": "authentication middleware",
        "filter_language": "python",
        "filter_kinds": ["function", "method"]
    }
    ```

    ## Search modes

    - **semantic**: Dense embedding similarity.  Best for conceptual queries.
    - **keyword**: BM25 term frequency.  Best for exact identifier matching.
    - **hybrid**: Combines both with Reciprocal Rank Fusion.  Recommended.

    ## Filters

    All filters are applied AFTER retrieval (post-filtering).
    - `filter_language`: Only return chunks from this language.
    - `filter_paths`: Only return chunks from files under these path prefixes.
    - `filter_kinds`: Only return chunks of these kinds (function/class/etc).
    - `filter_symbols`: Only return chunks whose symbol name contains any of
      these substrings (case-insensitive).
    """
    engine = request.app.state.retrieval_engine
    return await engine.search(query)
