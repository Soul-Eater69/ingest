"""Ingestion engine — the enterprise orchestrator.

Reads the config, fetches data from each source, validates records,
applies transforms, and writes nodes and relationships to Neo4j.

Supports two execution modes:
- **standard**: Python-native. Reads into memory, writes via Neo4j driver.
  Suitable for up to ~10M records on a single machine.
- **spark**: Distributed. Reads via Spark, writes via Neo4j Spark Connector.
  Scales to billions of records across a cluster.

Features:
- Pre/post schema hooks (create indexes/constraints)
- Neo4j health check before starting
- Parallel source reading (optional)
- Record-level validation with configurable error strategies
- Structured metrics with JSON output
- Retry on transient Neo4j failures
- Dry-run mode (validate config + read sources without writing)
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neo4j_ingest.config import IngestConfig, ValidationConfig, load_config
from neo4j_ingest.graph import Neo4jWriter
from neo4j_ingest.metrics import JobMetrics, track_step
from neo4j_ingest.resilience import check_neo4j_health
from neo4j_ingest.sources import read_source
from neo4j_ingest.validation import (
    ErrorStrategy,
    RecordValidator,
    ValidationRule,
)

logger = logging.getLogger(__name__)

Record = dict[str, Any]


@dataclass
class IngestResult:
    """Summary of an ingestion run."""

    nodes_created: dict[str, int] = field(default_factory=dict)
    relationships_created: dict[str, int] = field(default_factory=dict)
    records_skipped: int = 0
    metrics: JobMetrics | None = None

    @property
    def total_nodes(self) -> int:
        return sum(self.nodes_created.values())

    @property
    def total_relationships(self) -> int:
        return sum(self.relationships_created.values())


def _build_validator(vcfg: ValidationConfig | None) -> RecordValidator | None:
    """Build a RecordValidator from a config validation block."""
    if vcfg is None or not vcfg.rules:
        return None
    rules = [
        ValidationRule(
            field=r.field,
            rule=r.rule,
            params=r.params,
            message=r.message,
        )
        for r in vcfg.rules
    ]
    return RecordValidator(rules=rules, strategy=ErrorStrategy(vcfg.on_error))


def _read_source_safe(source_cfg: Any) -> tuple[str, list[Record] | Exception]:
    """Read a single source, returning (name, records) or (name, exception)."""
    try:
        records = read_source(source_cfg)
        return source_cfg.name, records
    except Exception as exc:
        return source_cfg.name, exc


# ---------------------------------------------------------------------------
# Spark helpers
# ---------------------------------------------------------------------------

def _init_spark_session(config: IngestConfig) -> Any:
    """Create or retrieve a SparkSession with the configured settings."""
    from pyspark.sql import SparkSession

    spark_cfg = config.settings.spark
    builder = SparkSession.builder.appName(spark_cfg.app_name)

    if spark_cfg.master:
        builder = builder.master(spark_cfg.master)

    for k, v in spark_cfg.spark_config.items():
        builder = builder.config(k, v)

    return builder.getOrCreate()


def _run_spark(
    config: IngestConfig,
    dry_run: bool,
    job_metrics: JobMetrics,
    result: IngestResult,
) -> IngestResult:
    """Execute the ingestion pipeline using Spark + Neo4j Spark Connector."""
    from neo4j_ingest.spark_writer import SparkNeo4jWriter

    # Ensure spark source types are registered
    import neo4j_ingest.spark_sources  # noqa: F401

    settings = config.settings
    spark = _init_spark_session(config)
    logger.info("Spark session initialised: %s", spark.sparkContext.appName)

    # Read all sources (via the standard dispatcher which now includes spark_* types)
    source_data: dict[str, list[Record]] = {}
    for source_cfg in config.sources:
        step = job_metrics.add_step(f"source:{source_cfg.name}")
        with track_step(step):
            try:
                records = read_source(source_cfg)
                source_data[source_cfg.name] = records
                step.records_processed = len(records)
            except Exception:
                if not settings.continue_on_source_error:
                    raise
                logger.error("Source '%s' failed, continuing", source_cfg.name)

    if dry_run:
        logger.info("Dry run (Spark mode): skipping Neo4j writes")
        for name, records in source_data.items():
            logger.info("  Source '%s': %d records", name, len(records))
        job_metrics.status = "dry_run"
        job_metrics.end_time = time.time()
        job_metrics.log_summary()
        return result

    spark_settings = settings.spark
    with SparkNeo4jWriter(
        config.neo4j,
        batch_size=spark_settings.neo4j_connector_batch_size,
        partitions=spark_settings.partitions,
    ) as writer:
        # Pre-hooks
        if config.pre_hooks:
            hook_step = job_metrics.add_step("pre_hooks")
            with track_step(hook_step):
                writer.run_hooks(config.pre_hooks)
                hook_step.records_processed = len(config.pre_hooks)

        # Nodes
        for node_mapping in config.nodes:
            step = job_metrics.add_step(f"nodes:{node_mapping.label}")
            with track_step(step):
                records = source_data.get(node_mapping.source, [])

                validator = _build_validator(node_mapping.validation)
                if validator:
                    vresult = validator.validate(records)
                    records = vresult.valid_records
                    step.records_failed = vresult.total_errors
                    result.records_skipped += vresult.total_errors

                count = writer.write_nodes(
                    records, node_mapping,
                    batch_size=spark_settings.neo4j_connector_batch_size,
                )
                step.records_processed = count
                result.nodes_created[node_mapping.label] = (
                    result.nodes_created.get(node_mapping.label, 0) + count
                )

        # Relationships
        for rel_mapping in config.relationships:
            step = job_metrics.add_step(f"rels:{rel_mapping.rel_type}")
            with track_step(step):
                records = source_data.get(rel_mapping.source, [])

                validator = _build_validator(rel_mapping.validation)
                if validator:
                    vresult = validator.validate(records)
                    records = vresult.valid_records
                    step.records_failed = vresult.total_errors
                    result.records_skipped += vresult.total_errors

                count = writer.write_relationships(
                    records, rel_mapping,
                    batch_size=spark_settings.neo4j_connector_batch_size,
                )
                step.records_processed = count
                result.relationships_created[rel_mapping.rel_type] = (
                    result.relationships_created.get(rel_mapping.rel_type, 0) + count
                )

        # Post-hooks
        if config.post_hooks:
            hook_step = job_metrics.add_step("post_hooks")
            with track_step(hook_step):
                writer.run_hooks(config.post_hooks)
                hook_step.records_processed = len(config.post_hooks)

    return result


# ---------------------------------------------------------------------------
# Standard (Python-native) pipeline
# ---------------------------------------------------------------------------

def _run_standard(
    config: IngestConfig,
    dry_run: bool,
    job_metrics: JobMetrics,
    result: IngestResult,
) -> IngestResult:
    """Execute the pipeline using the Python Neo4j driver."""
    settings = config.settings

    # Read all sources
    source_data: dict[str, list[Record]] = {}

    if settings.parallel_sources and len(config.sources) > 1:
        logger.info(
            "Reading %d sources in parallel (max_workers=%d)",
            len(config.sources),
            settings.max_workers,
        )
        with ThreadPoolExecutor(max_workers=settings.max_workers) as pool:
            futures = {
                pool.submit(_read_source_safe, src): src
                for src in config.sources
            }
            for future in as_completed(futures):
                name, data = future.result()
                step = job_metrics.add_step(f"source:{name}")
                if isinstance(data, Exception):
                    step.status = "failed"
                    step.error = str(data)
                    if not settings.continue_on_source_error:
                        raise data
                    logger.error("Source '%s' failed: %s", name, data)
                else:
                    source_data[name] = data
                    step.records_processed = len(data)
                    step.status = "completed"
    else:
        for source_cfg in config.sources:
            step = job_metrics.add_step(f"source:{source_cfg.name}")
            with track_step(step):
                try:
                    records = read_source(source_cfg)
                    source_data[source_cfg.name] = records
                    step.records_processed = len(records)
                except Exception:
                    if not settings.continue_on_source_error:
                        raise
                    logger.error("Source '%s' failed, continuing", source_cfg.name)

    if dry_run:
        logger.info("Dry run: skipping Neo4j writes")
        for name, records in source_data.items():
            logger.info("  Source '%s': %d records", name, len(records))
        job_metrics.status = "dry_run"
        job_metrics.end_time = time.time()
        job_metrics.log_summary()
        return result

    with Neo4jWriter(
        config.neo4j,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_delay=settings.retry_base_delay,
    ) as writer:
        # Pre-hooks
        if config.pre_hooks:
            hook_step = job_metrics.add_step("pre_hooks")
            with track_step(hook_step):
                writer.run_hooks(config.pre_hooks)
                hook_step.records_processed = len(config.pre_hooks)

        # Nodes
        for node_mapping in config.nodes:
            step = job_metrics.add_step(f"nodes:{node_mapping.label}")
            with track_step(step):
                records = source_data.get(node_mapping.source, [])

                validator = _build_validator(node_mapping.validation)
                if validator:
                    vresult = validator.validate(records)
                    records = vresult.valid_records
                    step.records_failed = vresult.total_errors
                    result.records_skipped += vresult.total_errors

                count = writer.write_nodes(
                    records, node_mapping, batch_size=settings.batch_size
                )
                step.records_processed = count
                result.nodes_created[node_mapping.label] = (
                    result.nodes_created.get(node_mapping.label, 0) + count
                )

        # Relationships
        for rel_mapping in config.relationships:
            step = job_metrics.add_step(f"rels:{rel_mapping.rel_type}")
            with track_step(step):
                records = source_data.get(rel_mapping.source, [])

                validator = _build_validator(rel_mapping.validation)
                if validator:
                    vresult = validator.validate(records)
                    records = vresult.valid_records
                    step.records_failed = vresult.total_errors
                    result.records_skipped += vresult.total_errors

                count = writer.write_relationships(
                    records, rel_mapping, batch_size=settings.batch_size
                )
                step.records_processed = count
                result.relationships_created[rel_mapping.rel_type] = (
                    result.relationships_created.get(rel_mapping.rel_type, 0) + count
                )

        # Post-hooks
        if config.post_hooks:
            hook_step = job_metrics.add_step("post_hooks")
            with track_step(hook_step):
                writer.run_hooks(config.post_hooks)
                hook_step.records_processed = len(config.post_hooks)

    return result


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run(
    config: IngestConfig,
    dry_run: bool = False,
) -> IngestResult:
    """Execute the full ingestion pipeline.

    Automatically selects execution mode based on ``settings.execution_mode``:
    - ``"standard"``: Python-native reads + Neo4j Python driver writes
    - ``"spark"``: Spark distributed reads + Neo4j Spark Connector writes

    Steps:
        1. Health check Neo4j (unless disabled or dry_run)
        2. Read data from all sources
        3. Run pre-hooks (indexes, constraints)
        4. For each node mapping: validate, then write nodes
        5. For each relationship mapping: validate, then write rels
        6. Run post-hooks
        7. Emit metrics
    """
    settings = config.settings
    result = IngestResult()

    # Metrics
    job_metrics = JobMetrics(
        job_id=uuid.uuid4().hex[:12],
        start_time=time.time(),
    )
    result.metrics = job_metrics

    # Health check
    if settings.health_check and not dry_run:
        if not check_neo4j_health(
            config.neo4j.uri,
            config.neo4j.username,
            config.neo4j.password,
            config.neo4j.database,
        ):
            raise ConnectionError(
                f"Neo4j health check failed for {config.neo4j.uri}. "
                "Set settings.health_check: false to skip."
            )

    # Dispatch to execution mode
    if settings.execution_mode == "spark":
        logger.info("Using Spark execution mode")
        _run_spark(config, dry_run, job_metrics, result)
    else:
        _run_standard(config, dry_run, job_metrics, result)

    # Finalise metrics
    if job_metrics.status == "pending":
        job_metrics.status = "completed"
    job_metrics.end_time = time.time()
    job_metrics.log_summary()

    if settings.metrics_output:
        Path(settings.metrics_output).write_text(job_metrics.to_json())
        logger.info("Metrics written to %s", settings.metrics_output)

    return result


def run_from_file(
    config_path: str,
    dry_run: bool = False,
) -> IngestResult:
    """Load a config file and run the ingestion pipeline."""
    config = load_config(config_path)
    return run(config, dry_run=dry_run)


def validate_config(config_path: str) -> IngestConfig:
    """Load and validate a config file without running the pipeline."""
    return load_config(config_path)
