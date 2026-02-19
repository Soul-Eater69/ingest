"""
cli.py
======
Command-line interface for the codebase indexer.

Commands
--------
  cidx index <path>    Index a directory (or re-index changed files)
  cidx search <query>  Search the index
  cidx watch <path>    Watch for changes and re-index incrementally
  cidx info            Show index statistics
  cidx serve           Start the REST API server
  cidx cache clear     Clear the embedding cache

Usage examples
--------------
    # Index the current directory
    cidx index .

    # Force re-index everything
    cidx index . --force

    # Search semantically
    cidx search "function that validates email addresses"

    # Search with keyword mode and language filter
    cidx search "parseCSVFile" --mode keyword --language python

    # Watch for changes (incremental re-indexing)
    cidx watch /path/to/repo

    # Start the API server
    cidx serve --port 8000

    # Show index stats
    cidx info
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

from .config import SearchMode, settings


# ---------------------------------------------------------------------------
# Root command group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0", prog_name="cidx")
def cli() -> None:
    """
    cidx – Codebase Indexer CLI

    Index codebases for semantic search and RAG pipelines.
    """
    pass


# ---------------------------------------------------------------------------
# cidx index
# ---------------------------------------------------------------------------

@cli.command("index")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--force", is_flag=True, help="Re-index all files even if unchanged")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def cmd_index(path: str, force: bool, verbose: bool) -> None:
    """
    Index a codebase directory.

    PATH is the repository root to index (defaults to current directory).

    Only files whose content hash has changed since the last run are
    re-indexed.  Use --force to rebuild the entire index.
    """
    root = Path(path).resolve()
    click.echo(f"Indexing {root} ...")

    async def _run() -> None:
        from .embeddings.factory import get_embedder
        from .pipeline import IndexPipeline
        from .storage.factory import get_metadata_store, get_vector_store

        pipeline = IndexPipeline(
            vector_store=get_vector_store(),
            metadata_store=get_metadata_store(),
            embedder=get_embedder(),
        )
        stats = await pipeline.index_directory(root, force=force)
        click.echo(
            f"\nDone.  "
            f"Files: {stats['files_indexed']}  |  "
            f"Chunks: {stats['chunks_indexed']}"
        )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# cidx search
# ---------------------------------------------------------------------------

@cli.command("search")
@click.argument("query")
@click.option("--mode", type=click.Choice(["semantic", "keyword", "hybrid"]),
              default="hybrid", show_default=True)
@click.option("--top-k", "-k", default=10, show_default=True,
              help="Number of results to return")
@click.option("--language", "-l", default=None,
              help="Filter results to a specific language (python, go, rust, …)")
@click.option("--path-filter", "-p", multiple=True,
              help="Only return chunks under these path prefixes (repeatable)")
@click.option("--json-output", is_flag=True, help="Output results as JSON")
def cmd_search(
    query: str,
    mode: str,
    top_k: int,
    language: str | None,
    path_filter: tuple[str, ...],
    json_output: bool,
) -> None:
    """
    Search the indexed codebase.

    QUERY can be a natural-language description or an exact identifier.

    Examples:
        cidx search "function that parses JWT tokens"
        cidx search "UserService.authenticate" --mode keyword
        cidx search "database connection pool" --language python --top-k 5
    """

    async def _run() -> None:
        from .models.search import SearchQuery
        from .models.chunk import Language
        from .embeddings.factory import get_embedder
        from .retrieval.engine import RetrievalEngine
        from .retrieval.hybrid import HybridRetriever
        from .retrieval.keyword import KeywordRetriever
        from .retrieval.reranker import CrossEncoderReranker
        from .retrieval.semantic import SemanticRetriever
        from .storage.factory import get_metadata_store, get_vector_store

        vector_store   = get_vector_store()
        metadata_store = get_metadata_store()
        embedder       = get_embedder()
        semantic  = SemanticRetriever(embedder, vector_store, metadata_store)
        keyword   = KeywordRetriever(metadata_store)
        await keyword.load_index()
        hybrid    = HybridRetriever(semantic, keyword)
        engine    = RetrievalEngine(semantic, keyword, hybrid)

        lang_enum = None
        if language:
            try:
                lang_enum = Language(language.lower())
            except ValueError:
                click.echo(f"Unknown language: {language}", err=True)
                sys.exit(1)

        search_query = SearchQuery(
            text=query,
            mode=SearchMode(mode),
            top_k=top_k,
            filter_language=lang_enum,
            filter_paths=list(path_filter),
        )

        response = await engine.search(search_query)

        if json_output:
            click.echo(response.model_dump_json(indent=2))
            return

        click.echo(
            f"\n  {response.total} results for \"{query}\"  "
            f"[mode={mode}, {response.latency_ms:.0f}ms]\n"
        )
        click.echo("─" * 72)

        for result in response.results:
            chunk = result.chunk
            click.echo(
                f"\n[{result.rank}] {chunk['rel_path']}:{chunk['start_line']}-{chunk['end_line']}"
                f"  ({chunk['language']} · {chunk['kind']})"
            )
            if chunk.get("symbol_name"):
                click.echo(f"    Symbol: {chunk['symbol_name']}")
            click.echo(f"    Score:  {result.score:.4f}")
            if chunk.get("docstring"):
                first_doc_line = chunk["docstring"].split("\n")[0].strip()
                click.echo(f"    Doc:    {first_doc_line[:80]}")
            # Show first 3 lines of code
            code_preview = "\n".join(chunk["text"].splitlines()[:3])
            for line in code_preview.splitlines():
                click.echo(f"    {line}")
            click.echo("─" * 72)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# cidx watch
# ---------------------------------------------------------------------------

@cli.command("watch")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
def cmd_watch(path: str) -> None:
    """
    Watch a directory for changes and incrementally re-index on save.

    Useful during development: every time you save a file, it is
    automatically re-indexed so your semantic search stays current.
    """
    root = Path(path).resolve()
    click.echo(f"Watching {root} for changes (Ctrl+C to stop) ...")

    async def _run() -> None:
        from .embeddings.factory import get_embedder
        from .ingestion.watcher import FileWatcher
        from .pipeline import IndexPipeline
        from .storage.factory import get_metadata_store, get_vector_store

        pipeline = IndexPipeline(
            vector_store=get_vector_store(),
            metadata_store=get_metadata_store(),
            embedder=get_embedder(),
        )

        async def on_change(paths: list[Path]) -> None:
            for p in paths:
                click.echo(f"  re-indexing {p.relative_to(root)}")
                await pipeline.index_file(p, root)

        watcher = FileWatcher(root, callback=on_change)
        await watcher.start()

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await watcher.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# cidx info
# ---------------------------------------------------------------------------

@cli.command("info")
@click.option("--json-output", is_flag=True)
def cmd_info(json_output: bool) -> None:
    """Show index statistics and configuration."""

    async def _run() -> None:
        from .storage.factory import get_metadata_store
        store = get_metadata_store()
        stats = await store.get_stats()

        if json_output:
            click.echo(stats.model_dump_json(indent=2))
            return

        click.echo("\n  Codebase Indexer – Index Info\n")
        click.echo(f"  Files:       {stats.total_files:,}")
        click.echo(f"  Chunks:      {stats.total_chunks:,}")
        click.echo(f"  Tokens:      {stats.total_tokens:,}")
        click.echo(f"  Vector DB:   {stats.vector_backend}")
        click.echo(f"  Embedder:    {stats.embed_model}")
        if stats.last_indexed_at:
            click.echo(f"  Last index:  {stats.last_indexed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        if stats.files_by_language:
            click.echo("\n  Files by language:")
            for lang, count in sorted(stats.files_by_language.items(), key=lambda x: -x[1]):
                click.echo(f"    {lang:<20} {count:>6}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# cidx serve
# ---------------------------------------------------------------------------

@cli.command("serve")
@click.option("--host", default=settings.api_host, show_default=True)
@click.option("--port", default=settings.api_port, show_default=True)
@click.option("--workers", default=1, show_default=True)
@click.option("--reload", is_flag=True, help="Enable auto-reload (development only)")
def cmd_serve(host: str, port: int, workers: int, reload: bool) -> None:
    """Start the REST API server."""
    try:
        import uvicorn  # type: ignore[import]
    except ImportError:
        click.echo("uvicorn not installed. Install with: pip install uvicorn", err=True)
        sys.exit(1)

    click.echo(f"Starting API server at http://{host}:{port}")
    click.echo("  Docs: /docs   ReDoc: /redoc   Health: /health")

    uvicorn.run(
        "codebase_indexer.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


# ---------------------------------------------------------------------------
# cidx cache
# ---------------------------------------------------------------------------

@cli.group("cache")
def cmd_cache() -> None:
    """Manage the embedding cache."""
    pass


@cmd_cache.command("clear")
@click.confirmation_option(prompt="This will delete all cached embeddings. Continue?")
def cache_clear() -> None:
    """Delete all cached embedding vectors."""
    import shutil
    cache_dir = settings.embed_cache_dir
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        click.echo(f"Cache cleared: {cache_dir}")
    else:
        click.echo("Cache directory does not exist.")


@cmd_cache.command("stats")
def cache_stats() -> None:
    """Show embedding cache statistics."""
    cache_dir = settings.embed_cache_dir
    if not cache_dir.exists():
        click.echo("Cache is empty.")
        return
    files = list(cache_dir.glob("*.npy"))
    total_bytes = sum(f.stat().st_size for f in files)
    click.echo(f"Cached embeddings: {len(files):,}")
    click.echo(f"Cache size:        {total_bytes / 1024 / 1024:.1f} MB")
    click.echo(f"Cache directory:   {cache_dir}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
