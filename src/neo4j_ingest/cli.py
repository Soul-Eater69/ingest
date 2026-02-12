"""CLI entry point for neo4j-ingest."""

from __future__ import annotations

import logging
import sys

import click

from neo4j_ingest.engine import run_from_file


@click.command()
@click.argument("config", type=click.Path(exists=True))
@click.option(
    "--batch-size",
    default=500,
    show_default=True,
    help="Number of records per Neo4j write transaction.",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
    help="Logging verbosity.",
)
def main(config: str, batch_size: int, log_level: str) -> None:
    """Ingest data into Neo4j from a YAML/JSON config file.

    CONFIG is the path to the ingestion config file.
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        result = run_from_file(config, batch_size=batch_size)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo("Ingestion complete!")
    for label, count in result.nodes_created.items():
        click.echo(f"  Nodes  [{label}]: {count}")
    for rel_type, count in result.relationships_created.items():
        click.echo(f"  Rels   [{rel_type}]: {count}")


if __name__ == "__main__":
    main()
