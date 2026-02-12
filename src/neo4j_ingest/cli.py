"""CLI entry point for neo4j-ingest.

Provides subcommands:
  run       — execute the full ingestion pipeline
  validate  — check a config file without running
  dry-run   — read sources and validate but skip Neo4j writes
"""

from __future__ import annotations

import logging
import sys

import click


def _setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.version_option(package_name="neo4j-ingest")
def main() -> None:
    """neo4j-ingest: Config-driven data ingestion into Neo4j."""


@main.command()
@click.argument("config", type=click.Path(exists=True))
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
@click.option("--metrics-output", default=None, help="Path to write JSON metrics.")
def run(config: str, log_level: str, metrics_output: str | None) -> None:
    """Run the full ingestion pipeline."""
    _setup_logging(log_level)

    from neo4j_ingest.engine import run_from_file

    try:
        result = run_from_file(config)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo("Ingestion complete!")
    for label, count in result.nodes_created.items():
        click.echo(f"  Nodes  [{label}]: {count}")
    for rel_type, count in result.relationships_created.items():
        click.echo(f"  Rels   [{rel_type}]: {count}")
    if result.records_skipped:
        click.echo(f"  Skipped: {result.records_skipped} records")

    if metrics_output and result.metrics:
        import pathlib

        pathlib.Path(metrics_output).write_text(result.metrics.to_json())
        click.echo(f"  Metrics: {metrics_output}")


@main.command()
@click.argument("config", type=click.Path(exists=True))
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
def validate(config: str, log_level: str) -> None:
    """Validate a config file without running the pipeline."""
    _setup_logging(log_level)

    from neo4j_ingest.engine import validate_config

    try:
        cfg = validate_config(config)
    except Exception as exc:
        click.echo(f"Validation FAILED: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo("Config is valid!")
    click.echo(f"  Sources:       {len(cfg.sources)}")
    click.echo(f"  Node mappings: {len(cfg.nodes)}")
    click.echo(f"  Rel mappings:  {len(cfg.relationships)}")
    click.echo(f"  Pre-hooks:     {len(cfg.pre_hooks)}")
    click.echo(f"  Post-hooks:    {len(cfg.post_hooks)}")


@main.command("dry-run")
@click.argument("config", type=click.Path(exists=True))
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
def dry_run(config: str, log_level: str) -> None:
    """Read sources and validate without writing to Neo4j."""
    _setup_logging(log_level)

    from neo4j_ingest.engine import run_from_file

    try:
        result = run_from_file(config, dry_run=True)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo("Dry run complete! No data was written to Neo4j.")
    if result.metrics:
        for step in result.metrics.steps:
            click.echo(f"  {step.name}: {step.records_processed} records")


if __name__ == "__main__":
    main()
