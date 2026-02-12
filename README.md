# neo4j-ingest

A config-driven data ingestion framework for Neo4j. Define your data sources, node mappings, relationship mappings, transforms, and validation rules in a single YAML or JSON file — and the framework handles reading, transforming, validating, and writing everything to Neo4j.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Commands](#cli-commands)
- [Configuration Reference](#configuration-reference)
  - [neo4j](#neo4j)
  - [settings](#settings)
  - [sources](#sources)
  - [nodes](#nodes)
  - [relationships](#relationships)
  - [pre_hooks / post_hooks](#pre_hooks--post_hooks)
- [Environment Variable Substitution](#environment-variable-substitution)
- [Data Sources](#data-sources)
  - [CSV](#csv)
  - [JSON](#json)
  - [SQL](#sql)
  - [REST API](#rest-api)
  - [Spark Sources](#spark-sources)
- [Transforms](#transforms)
- [Validation](#validation)
- [Execution Modes](#execution-modes)
  - [Standard Mode](#standard-mode)
  - [Spark Mode](#spark-mode)
- [Resilience](#resilience)
  - [Retry with Backoff](#retry-with-backoff)
  - [Circuit Breaker](#circuit-breaker)
  - [Health Checks](#health-checks)
- [Metrics and Observability](#metrics-and-observability)
- [Plugin System](#plugin-system)
  - [Custom Source Types](#custom-source-types)
  - [Custom Transforms](#custom-transforms)
- [Architecture](#architecture)
  - [High-Level System Architecture](#high-level-system-architecture)
  - [Module Dependency Map](#module-dependency-map)
  - [Pipeline Execution Flow](#pipeline-execution-flow)
  - [Config Processing Pipeline](#config-processing-pipeline)
  - [Record Processing Detail](#record-processing-detail)
  - [Standard vs. Spark Execution Comparison](#standard-vs-spark-execution-comparison)
  - [Resilience Patterns](#resilience-patterns)
  - [Plugin Registry Architecture](#plugin-registry-architecture)
  - [Cypher Generation Detail](#cypher-generation-detail)
  - [Spark Mode Internals](#spark-mode-internals)
  - [Validation Flow Detail](#validation-flow-detail)
  - [Metrics Collection Architecture](#metrics-collection-architecture)
- [Python API](#python-api)
- [Examples](#examples)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Installation

**Core installation** (CSV, JSON, SQL, REST sources):

```bash
pip install neo4j-ingest
```

**With Spark support** (for massive datasets via PySpark):

```bash
pip install neo4j-ingest[spark]
```

**Development installation** (from source):

```bash
git clone <repo-url>
cd ingest
pip install -e ".[dev]"
```

### Requirements

- Python >= 3.10
- Neo4j >= 5.0 (server)
- PySpark >= 3.4 (optional, for Spark execution mode)

### Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `neo4j` | >= 5.0 | Neo4j Python driver for database writes |
| `pyyaml` | >= 6.0 | YAML config file parsing |
| `pydantic` | >= 2.0 | Config validation and type checking |
| `requests` | >= 2.28 | REST API source connector |
| `sqlalchemy` | >= 2.0 | SQL database source connector |
| `click` | >= 8.0 | CLI interface |

---

## Quick Start

### 1. Create a config file

Create `config.yaml`:

```yaml
neo4j:
  uri: bolt://localhost:7687
  username: neo4j
  password: changeme
  database: neo4j

sources:
  - name: employees
    type: csv
    path: employees.csv

nodes:
  - source: employees
    label: Person
    key: emp_id
    properties:
      - source_field: emp_id
      - source_field: name
      - source_field: email
```

### 2. Create the data file

Create `employees.csv`:

```csv
emp_id,name,email
1,Alice,alice@example.com
2,Bob,bob@example.com
3,Charlie,charlie@example.com
```

### 3. Run the ingestion

```bash
neo4j-ingest run config.yaml
```

Output:

```
Ingestion complete!
  Nodes  [Person]: 3
```

That's it. Three employees are now `Person` nodes in Neo4j, each with `emp_id`, `name`, and `email` properties, deduplicated by `emp_id`.

---

## CLI Commands

The CLI provides three subcommands. All accept a config file path and an optional `--log-level`.

### `neo4j-ingest run`

Executes the full ingestion pipeline: reads sources, validates records, runs pre-hooks, writes nodes and relationships, runs post-hooks, and emits metrics.

```bash
neo4j-ingest run config.yaml
neo4j-ingest run config.yaml --log-level DEBUG
neo4j-ingest run config.yaml --metrics-output /tmp/metrics.json
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `CONFIG` | path | required | Path to YAML or JSON config file |
| `--log-level` | choice | `INFO` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--metrics-output` | path | none | Path to write JSON metrics file after completion |

### `neo4j-ingest validate`

Validates a config file without connecting to Neo4j or reading any data. Useful for CI/CD pipelines or pre-flight checks.

```bash
neo4j-ingest validate config.yaml
```

Output on success:

```
Config is valid!
  Sources:       2
  Node mappings: 2
  Rel mappings:  1
  Pre-hooks:     3
  Post-hooks:    1
```

Output on failure:

```
Validation FAILED: CSV source requires 'path'
```

### `neo4j-ingest dry-run`

Reads all data sources and validates records, but does **not** write anything to Neo4j. Use this to verify your sources are reachable and your data looks correct before committing to a real run.

```bash
neo4j-ingest dry-run config.yaml
```

Output:

```
Dry run complete! No data was written to Neo4j.
  source:employees: 1000 records
  source:departments: 50 records
```

### Version

```bash
neo4j-ingest --version
```

---

## Configuration Reference

A config file is either YAML (`.yaml`, `.yml`) or JSON (`.json`). Every field is documented below with its type, default value, and whether it is required.

### Full Config Structure

```yaml
neo4j:          # Neo4j connection settings
settings:       # Job-level settings (batch size, retries, mode, etc.)
sources:        # List of data sources to read from
nodes:          # List of node mappings (source → Neo4j nodes)
relationships:  # List of relationship mappings (source → Neo4j relationships)
pre_hooks:      # Cypher queries to run BEFORE ingestion
post_hooks:     # Cypher queries to run AFTER ingestion
```

---

### `neo4j`

Connection settings for the target Neo4j database. All fields are optional and have sensible defaults.

```yaml
neo4j:
  uri: bolt://localhost:7687
  username: neo4j
  password: changeme
  database: neo4j
  max_connection_pool_size: 100
  connection_acquisition_timeout: 60.0
  encrypted: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `uri` | string | `"bolt://localhost:7687"` | Neo4j Bolt URI. Use `bolt://` for unencrypted, `bolt+s://` or `neo4j+s://` for TLS. For Aura, use `neo4j+s://`. |
| `username` | string | `"neo4j"` | Database username for authentication. |
| `password` | string | `"neo4j"` | Database password. **Use environment variable substitution** (see below) to avoid hardcoding secrets. |
| `database` | string | `"neo4j"` | Target database name. Neo4j Community Edition only supports the default `"neo4j"` database. Enterprise Edition supports multiple databases. |
| `max_connection_pool_size` | integer | `100` | Maximum number of connections in the driver's connection pool. Increase for high-throughput jobs with many concurrent writes. |
| `connection_acquisition_timeout` | float | `60.0` | Seconds to wait when acquiring a connection from the pool before raising a timeout error. |
| `encrypted` | boolean | `false` | Whether to use TLS encryption for the connection. Set to `true` when using `bolt://` with a Neo4j instance that requires encryption. Not needed if the URI scheme already includes encryption (e.g., `bolt+s://`). |

#### Securing Credentials

Never hardcode passwords in config files. Use environment variable substitution:

```yaml
neo4j:
  uri: ${NEO4J_URI:-bolt://localhost:7687}
  username: ${NEO4J_USER:-neo4j}
  password: ${NEO4J_PASSWORD}
```

---

### `settings`

Global job-level configuration that controls how the ingestion pipeline behaves.

```yaml
settings:
  batch_size: 500
  parallel_sources: false
  max_workers: 4
  health_check: true
  retry_max_attempts: 3
  retry_base_delay: 1.0
  continue_on_source_error: false
  metrics_output: null
  execution_mode: standard
  spark:
    app_name: neo4j-ingest
    master: null
    partitions: null
    neo4j_connector_batch_size: 5000
    spark_config: {}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `batch_size` | integer | `500` | Number of records sent to Neo4j per `UNWIND` transaction in standard mode. Higher values reduce round-trips but use more memory. Recommended: 500–5000. |
| `parallel_sources` | boolean | `false` | When `true`, reads multiple data sources concurrently using a thread pool. Useful when sources are I/O-bound (e.g., multiple REST APIs). |
| `max_workers` | integer | `4` | Maximum number of threads for parallel source reading. Only used when `parallel_sources` is `true`. |
| `health_check` | boolean | `true` | When `true`, verifies Neo4j is reachable before starting the pipeline. Runs a simple `RETURN 1` query. Disable for dry-run or when Neo4j is known to be available. |
| `retry_max_attempts` | integer | `3` | Maximum number of attempts for each Neo4j batch write. The first attempt counts as attempt 1. Set to `1` to disable retries. |
| `retry_base_delay` | float | `1.0` | Base delay in seconds for the first retry. Subsequent retries use exponential backoff: `delay = min(base_delay * 2^attempt, 30) + jitter`. |
| `continue_on_source_error` | boolean | `false` | When `true`, if a source fails to read, the pipeline continues with remaining sources. When `false` (default), the pipeline aborts on the first source failure. |
| `metrics_output` | string or null | `null` | File path to write JSON metrics after the job completes. Set to `null` to skip writing metrics. Example: `"/tmp/ingest_metrics.json"`. |
| `execution_mode` | string | `"standard"` | Either `"standard"` (Python-native, single machine) or `"spark"` (distributed via PySpark + Neo4j Spark Connector). See [Execution Modes](#execution-modes). |
| `spark` | object | see below | Spark-specific settings. Only used when `execution_mode` is `"spark"`. |

#### `settings.spark`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `app_name` | string | `"neo4j-ingest"` | Spark application name (visible in Spark UI). |
| `master` | string or null | `null` | Spark master URL (e.g., `"spark://master:7077"`, `"local[*]"`). When `null`, uses the existing SparkSession or Spark's default. Omit on Databricks (auto-managed). |
| `partitions` | integer or null | `null` | Number of partitions for DataFrame repartitioning before writing to Neo4j. Higher values = more parallelism. When `null`, uses Spark's default partitioning. |
| `neo4j_connector_batch_size` | integer | `5000` | Batch size for the Neo4j Spark Connector. Controls how many records each executor sends per write operation. |
| `spark_config` | object | `{}` | Arbitrary key-value pairs passed to `SparkSession.builder.config()`. Example: `{"spark.sql.shuffle.partitions": "200"}`. |

---

### `sources`

A list of data sources to read from. Each source has a `name` (used to reference it from node/relationship mappings), a `type`, and type-specific fields.

```yaml
sources:
  - name: my_source_name
    type: csv
    path: data.csv
```

The `name` field must be unique across all sources. The `type` field determines which reader is used. Built-in types: `csv`, `json`, `sql`, `rest`. Spark types (requires `pip install neo4j-ingest[spark]`): `spark_csv`, `spark_json`, `spark_parquet`, `spark_delta`, `spark_jdbc`, `spark_table`. Custom types can be added via the [plugin system](#plugin-system).

#### Common Fields (all source types)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Unique identifier for this source. Referenced by node and relationship mappings. |
| `type` | string | required | Source type. Determines which reader function is used. |

See [Data Sources](#data-sources) for type-specific fields.

---

### `nodes`

A list of node mappings. Each mapping tells the framework: "For each record from source X, create or merge a node with label Y, using field Z as the deduplication key."

```yaml
nodes:
  - source: employees        # Which source to read from
    label: Person             # Neo4j node label
    key: emp_id               # Property used for MERGE (deduplication)
    properties:               # Fields to map
      - source_field: emp_id
      - source_field: name
      - source_field: email
        target: email_address
        transform:
          type: lowercase
    validation:               # Optional validation rules
      on_error: skip
      rules:
        - field: emp_id
          rule: required
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source` | string | required | Name of a source defined in the `sources` list. |
| `label` | string | required | Neo4j node label (e.g., `Person`, `Company`). Used in the `MERGE` clause. |
| `key` | string | required | The property name used for deduplication. The generated Cypher is `MERGE (n:Label {key: row.key})`. This field must exist in the `properties` list (either as `source_field` or `target`). |
| `properties` | list | required | List of property mappings. See [Property Mapping](#property-mapping) below. |
| `validation` | object or null | `null` | Optional validation rules applied to source records before writing. See [Validation](#validation). |

#### Property Mapping

Each entry in the `properties` list maps a field from the source record to a property on the Neo4j node.

```yaml
properties:
  - source_field: full_name    # Field name in the source record
    target: name               # Property name on the Neo4j node (optional)
    transform:                 # Transform(s) to apply (optional)
      type: uppercase
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_field` | string | required | The field name in the source record (e.g., a CSV column name). |
| `target` | string or null | `null` | The property name on the Neo4j node. When `null`, uses `source_field` as-is. Use this to rename fields (e.g., `full_name` → `name`). |
| `transform` | object, list, or null | `null` | One or more transforms to apply to the value. See [Transforms](#transforms). |

**How `key` works:** The `key` field in the node mapping must match a `target` (or `source_field` if no target is set) in the properties list. This is used in the `MERGE` clause to deduplicate nodes. For example, if `key: emp_id`, the generated Cypher is:

```cypher
UNWIND $rows AS row
MERGE (n:Person {emp_id: row.emp_id})
SET n.name = row.name, n.email = row.email
```

---

### `relationships`

A list of relationship mappings. Each mapping tells the framework: "For each record from source X, find the start node and end node by matching fields, then create a relationship between them."

```yaml
relationships:
  - source: employees
    rel_type: WORKS_IN
    from_label: Person
    from_key: emp_id
    from_field: emp_id
    to_label: Department
    to_key: dept_id
    to_field: dept_id
    properties:
      - source_field: start_date
        target: since
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source` | string | required | Name of a source defined in the `sources` list. |
| `rel_type` | string | required | Neo4j relationship type (e.g., `WORKS_IN`, `PURCHASED`). Used in the `MERGE` clause. |
| `from_label` | string | required | Label of the start node. |
| `from_key` | string | required | Property on the start node used for matching. |
| `from_field` | string | required | Field in the source record whose value matches `from_key` on the start node. |
| `to_label` | string | required | Label of the end node. |
| `to_key` | string | required | Property on the end node used for matching. |
| `to_field` | string | required | Field in the source record whose value matches `to_key` on the end node. |
| `properties` | list | `[]` | Optional list of property mappings to set on the relationship. Same format as node property mappings. |
| `validation` | object or null | `null` | Optional validation rules. Same format as node validation. |

**Generated Cypher:**

```cypher
UNWIND $rows AS row
MATCH (a:Person {emp_id: row.from_val})
MATCH (b:Department {dept_id: row.to_val})
MERGE (a)-[r:WORKS_IN]->(b)
SET r.since = row.since
```

**Important:** The start and end nodes must already exist before relationships can be created. The framework always writes all nodes before writing any relationships.

---

### `pre_hooks` / `post_hooks`

Lists of Cypher queries to run before (`pre_hooks`) or after (`post_hooks`) the ingestion pipeline. Common uses:

- **Pre-hooks:** Create indexes, constraints, or seed data
- **Post-hooks:** Compute aggregations, clean up temporary data, run analytics

```yaml
pre_hooks:
  - cypher: "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.emp_id IS UNIQUE"
    description: "Unique constraint on Person.emp_id"
  - cypher: "CREATE INDEX person_email IF NOT EXISTS FOR (p:Person) ON (p.email)"
    description: "Index on Person.email"

post_hooks:
  - cypher: >-
      MATCH (d:Department)<-[:WORKS_IN]-(p:Person)
      WITH d, count(p) AS cnt
      SET d.employee_count = cnt
    description: "Compute employee count per department"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cypher` | string | required | The Cypher query to execute. |
| `description` | string | `""` | Human-readable description (logged during execution). If empty, the first 60 characters of the Cypher query are logged instead. |

Hooks run sequentially in the order they are listed. If a hook fails, the pipeline aborts.

---

## Environment Variable Substitution

Any string value in the config file can reference environment variables using the `${VAR}` syntax. This keeps secrets out of config files.

### Syntax

| Pattern | Behavior |
|---------|----------|
| `${VAR}` | **Required.** Replaced with the value of `VAR`. Raises `MissingEnvironmentVariable` if `VAR` is not set. |
| `${VAR:-default}` | **Optional.** Replaced with the value of `VAR` if set, otherwise uses `default`. |
| `${VAR:-}` | Optional with empty default. Resolves to `""` if `VAR` is not set. |

### How It Works

1. The config file is loaded as raw YAML/JSON.
2. Before Pydantic validation, every string value in the parsed structure is scanned for `${...}` patterns.
3. The scanning is recursive — it processes strings inside nested dicts and lists.
4. Non-string values (integers, booleans, null) are left untouched.

### Examples

```yaml
neo4j:
  uri: ${NEO4J_URI:-bolt://localhost:7687}      # Uses env var or default
  password: ${NEO4J_PASSWORD}                     # Required — fails if not set
  database: ${NEO4J_DB:-neo4j}                   # Optional with default

sources:
  - name: api_data
    type: rest
    url: ${API_BASE_URL}/v1/data
    headers:
      Authorization: "Bearer ${API_TOKEN}"        # Works inside nested structures
```

### Setting Environment Variables

```bash
# Inline
NEO4J_PASSWORD=secret neo4j-ingest run config.yaml

# Export
export NEO4J_PASSWORD=secret
neo4j-ingest run config.yaml

# .env file (using direnv, dotenv, etc.)
echo "NEO4J_PASSWORD=secret" >> .env
```

### Error on Missing Required Variables

If you use `${VAR}` (without `:-default`) and `VAR` is not set in the environment, the framework raises a clear error:

```
MissingEnvironmentVariable: Required environment variable 'NEO4J_PASSWORD' is not set.
Use ${'NEO4J_PASSWORD':-default} to provide a fallback.
```

---

## Data Sources

### CSV

Reads records from a CSV file on disk.

```yaml
sources:
  - name: employees
    type: csv
    path: data/employees.csv
    encoding: utf-8
    delimiter: ","
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `path` | string | — | yes | Path to the CSV file. Relative to the working directory. |
| `encoding` | string | `"utf-8"` | no | File encoding. Common values: `utf-8`, `latin-1`, `cp1252`. |
| `delimiter` | string | `","` | no | Column delimiter. Use `"\t"` for TSV, `"|"` for pipe-delimited, `";"` for semicolons. |

The first row of the CSV is treated as the header row (column names). Each subsequent row becomes a dict where the keys are the column names.

### JSON

Reads records from a JSON file. The file must contain either a top-level array of objects, or an object with a nested array accessible via `json_root`.

```yaml
sources:
  # Top-level array: [{"id": 1}, {"id": 2}]
  - name: items
    type: json
    path: data/items.json

  # Nested array: {"response": {"data": [{"id": 1}]}}
  - name: nested_items
    type: json
    path: data/response.json
    json_root: response.data
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `path` | string | — | yes | Path to the JSON file. |
| `encoding` | string | `"utf-8"` | no | File encoding. |
| `json_root` | string or null | `null` | no | Dotted path to the array of records within the JSON structure. Example: `"response.data.items"`. When `null`, the top-level value must be an array. |

**How `json_root` works:** The path is split on `.` and traversed step by step. Each segment is used as a dictionary key. If a segment encounters a list, it uses the segment as an integer index. Example:

```json
{"response": {"data": {"items": [{"id": 1}, {"id": 2}]}}}
```

With `json_root: response.data.items`, the framework traverses `response` → `data` → `items` and returns the array.

### SQL

Reads records from any SQL database supported by SQLAlchemy.

```yaml
sources:
  - name: customers
    type: sql
    connection_string: postgresql://user:pass@localhost:5432/mydb
    query: "SELECT id, name, email FROM customers WHERE active = true"
    chunk_size: 10000
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `connection_string` | string | — | yes | SQLAlchemy connection URL. Examples: `postgresql://user:pass@host:5432/db`, `mysql+pymysql://user:pass@host/db`, `sqlite:///path/to/db.sqlite`. |
| `query` | string | — | yes | SQL query to execute. Must return rows. |
| `chunk_size` | integer or null | `null` | no | When set, reads rows in chunks of this size using `fetchmany()` instead of loading everything at once with `fetchall()`. Use for large result sets to control memory usage. |

**Chunked reads:** When `chunk_size` is set, the framework calls `fetchmany(chunk_size)` in a loop until no more rows are returned. This prevents loading millions of rows into memory at once. The final result is still a single list — chunking only affects how rows are fetched from the database.

### REST API

Reads records from an HTTP API endpoint.

```yaml
sources:
  - name: users
    type: rest
    url: https://api.example.com/v1/users
    method: GET
    headers:
      Authorization: "Bearer ${API_TOKEN}"
      Accept: application/json
    params:
      status: active
    timeout: 30.0
    json_root: data.users
    rate_limit:
      requests_per_second: 5.0
      burst: 1
    pagination:
      type: offset
      page_param: page
      page_size_param: per_page
      page_size: 100
      max_pages: 50
```

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `url` | string | — | yes | Full URL of the API endpoint. |
| `method` | string | `"GET"` | no | HTTP method. One of: `GET`, `POST`, `PUT`, `PATCH`. |
| `headers` | object | `{}` | no | HTTP headers as key-value pairs. |
| `params` | object | `{}` | no | URL query parameters as key-value pairs. |
| `body` | object or null | `null` | no | JSON request body (for POST/PUT/PATCH requests). |
| `timeout` | float | `60.0` | no | Request timeout in seconds. |
| `json_root` | string or null | `null` | no | Dotted path to the array of records in the JSON response body. Same behavior as JSON source `json_root`. |
| `rate_limit` | object or null | `null` | no | Rate limiting configuration. See below. |
| `pagination` | object or null | `null` | no | Pagination configuration. See below. |

#### Rate Limiting

Controls how fast requests are sent to the API. Uses a token-bucket algorithm.

```yaml
rate_limit:
  requests_per_second: 5.0
  burst: 1
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `requests_per_second` | float | `10.0` | Maximum average request rate. |
| `burst` | integer | `1` | Maximum number of requests that can be sent immediately before rate limiting kicks in. |

**How it works:** A token bucket starts with `burst` tokens. Each request consumes one token. Tokens are replenished at `requests_per_second` rate. When no tokens are available, the framework sleeps until one is replenished.

#### Pagination

Automatically fetches multiple pages from paginated APIs.

```yaml
pagination:
  type: offset
  page_param: page
  page_size_param: per_page
  page_size: 100
  max_pages: 1000
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"offset"` | Pagination strategy. One of: `"offset"`, `"cursor"`, `"page"`. |
| `page_param` | string | `"page"` | Query parameter name for the page number. |
| `page_size_param` | string | `"per_page"` | Query parameter name for the page size. |
| `page_size` | integer | `100` | Number of records per page. |
| `max_pages` | integer | `1000` | Maximum number of pages to fetch (safety limit). |
| `cursor_field` | string or null | `null` | For cursor-based pagination: field in the response containing the next cursor. |
| `next_cursor_path` | string or null | `null` | For cursor-based pagination: dotted path to the next cursor value. |

**Pagination stops when:**
1. A page returns fewer records than `page_size` (indicates last page), or
2. A page returns zero records, or
3. `max_pages` is reached, or
4. The `json_root` path fails to resolve (indicates no more data).

### Spark Sources

These source types use PySpark for distributed reading. They are ideal for datasets that are too large to fit in memory on a single machine: multi-GB CSVs, Parquet data lakes, Delta Lake tables, or databases with billions of rows.

**Requirement:** `pip install neo4j-ingest[spark]`

All Spark sources register themselves via the plugin registry when `neo4j_ingest.spark_sources` is imported (this happens automatically when `execution_mode: spark` is set).

#### `spark_csv`

Read CSV files via Spark. Supports glob patterns, S3, HDFS, GCS, and ABFS paths.

```yaml
sources:
  - name: events
    type: spark_csv
    path: s3a://bucket/data/events/*.csv
    encoding: utf-8
    delimiter: ","
    headers:
      multiLine: "true"
      escape: '"'
```

| Field | Description |
|-------|-------------|
| `path` | File path or glob pattern. Supports local, S3 (`s3a://`), HDFS (`hdfs://`), GCS (`gs://`), ABFS (`abfss://`). |
| `encoding` | Character encoding (default: `utf-8`). |
| `delimiter` | Column delimiter (default: `,`). |
| `headers` | Passed as Spark reader options (e.g., `multiLine`, `escape`, `quote`, `nullValue`). |

Spark automatically infers the schema and treats the first row as headers (`header=true`, `inferSchema=true`).

#### `spark_json`

Read JSON files via Spark.

```yaml
sources:
  - name: logs
    type: spark_json
    path: s3a://bucket/logs/2024/01/*.json
```

#### `spark_parquet`

Read Parquet files (columnar, compressed, partitioned).

```yaml
sources:
  - name: customers
    type: spark_parquet
    path: s3a://data-lake/warehouse/customers/
    query: "SELECT * FROM __customers WHERE country = 'US'"
```

| Field | Description |
|-------|-------------|
| `path` | Path to Parquet file(s) or directory. |
| `query` | Optional SQL filter. The DataFrame is registered as a temp view named `__<source_name>`, then this SQL is executed against it. |

#### `spark_delta`

Read Delta Lake tables (ACID transactions, time travel, schema evolution).

```yaml
sources:
  - name: products
    type: spark_delta
    path: s3a://data-lake/delta/products/
```

Requires Delta Lake libraries on the Spark classpath.

#### `spark_jdbc`

Distributed JDBC reads with parallel partitions across Spark executors.

```yaml
sources:
  - name: orders
    type: spark_jdbc
    connection_string: "jdbc:postgresql://db.prod:5432/orders"
    query: "SELECT * FROM orders WHERE created_at > '2024-01-01'"
    headers:
      driver: org.postgresql.Driver
      numPartitions: "16"
      partitionColumn: id
      lowerBound: "1"
      upperBound: "10000000"
      fetchsize: "10000"
```

| Field | Description |
|-------|-------------|
| `connection_string` | JDBC URL. |
| `query` | SQL query (if starts with `SELECT`) or table name. |
| `headers` | JDBC options: `driver`, `numPartitions`, `partitionColumn`, `lowerBound`, `upperBound`, `fetchsize`. |

The `numPartitions` + `partitionColumn` + `lowerBound` + `upperBound` settings tell Spark to split the query across N parallel JDBC connections, each reading a range of the partition column. This is how you achieve parallel reads from a single database.

#### `spark_table`

Read from Spark catalog tables (Hive metastore, Databricks Unity Catalog).

```yaml
sources:
  - name: transactions
    type: spark_table
    query: catalog.schema.transactions

  - name: filtered
    type: spark_table
    query: "SELECT * FROM catalog.schema.transactions WHERE amount > 100"
```

| Field | Description |
|-------|-------------|
| `query` | Either a fully-qualified table name (e.g., `catalog.schema.table`) or a SQL query starting with `SELECT`. |
| `path` | Alternative to `query` for specifying the table name. |

---

## Transforms

Transforms modify field values during ingestion. They are applied per-field in the `properties` list of node or relationship mappings. Transforms run **after** reading from the source and **before** writing to Neo4j.

### Single Transform

```yaml
properties:
  - source_field: email
    transform:
      type: lowercase
```

### Transform with Parameters

```yaml
properties:
  - source_field: created_at
    transform:
      type: to_datetime
      params:
        format: "%Y-%m-%d"
```

### Transform Chain

Apply multiple transforms in sequence. Each transform receives the output of the previous one.

```yaml
properties:
  - source_field: name
    transform:
      - type: strip
      - type: uppercase
```

In this example: `"  alice  "` → `"alice"` → `"ALICE"`.

### Built-in Transforms

| Type | Parameters | Input | Output | Description |
|------|-----------|-------|--------|-------------|
| `to_string` | none | any | `str` or `None` | Converts value to a string. Returns `None` if input is `None`. |
| `to_int` | none | any | `int` or `None` | Converts value to an integer. Returns `None` if input is `None` or `""`. |
| `to_float` | none | any | `float` or `None` | Converts value to a float. Returns `None` if input is `None` or `""`. |
| `to_bool` | none | any | `bool` or `None` | Converts to boolean. `"true"`, `"1"`, `"yes"`, `"y"` (case-insensitive) → `True`. Everything else → `False`. Returns `None` if input is `None`. |
| `to_datetime` | `format` (default: `"%Y-%m-%dT%H:%M:%S"`) | string | `str` (ISO 8601) or `None` | Parses a datetime string using the given `format` (Python `strftime` codes), then returns it in ISO 8601 format (`YYYY-MM-DDTHH:MM:SS`). Returns `None` if input is `None` or `""`. |
| `uppercase` | none | any | `str` or `None` | Converts to uppercase. |
| `lowercase` | none | any | `str` or `None` | Converts to lowercase. |
| `strip` | none | any | `str` or `None` | Removes leading and trailing whitespace. |
| `replace` | `old`, `new` | any | `str` or `None` | Replaces all occurrences of `old` with `new` in the string. |
| `default` | `default` | any | any | Returns `default` when the value is `None` or `""`. Otherwise returns the original value. |
| `template` | `template` (default: `"{value}"`) | any | `str` or `None` | Formats a template string. The original value is available as `{value}`. Example: `"Hello, {value}!"` with input `"Alice"` → `"Hello, Alice!"`. |

### `to_datetime` Format Codes

Common `strftime` format codes for the `format` parameter:

| Code | Meaning | Example |
|------|---------|---------|
| `%Y` | 4-digit year | `2024` |
| `%m` | Zero-padded month | `01`–`12` |
| `%d` | Zero-padded day | `01`–`31` |
| `%H` | Hour (24-hour) | `00`–`23` |
| `%M` | Minute | `00`–`59` |
| `%S` | Second | `00`–`59` |
| `%y` | 2-digit year | `24` |
| `%I` | Hour (12-hour) | `01`–`12` |
| `%p` | AM/PM | `AM`, `PM` |

**Examples:**

```yaml
# ISO 8601: "2024-01-15T14:30:00"
transform:
  type: to_datetime
  params:
    format: "%Y-%m-%dT%H:%M:%S"

# Date only: "2024-01-15"
transform:
  type: to_datetime
  params:
    format: "%Y-%m-%d"

# US format: "01/15/2024"
transform:
  type: to_datetime
  params:
    format: "%m/%d/%Y"

# With time: "15-Jan-2024 02:30 PM"
transform:
  type: to_datetime
  params:
    format: "%d-%b-%Y %I:%M %p"
```

### Null Handling

All built-in transforms return `None` when the input is `None`. This means nulls propagate safely through transform chains without raising errors. The `default` transform is the exception — it replaces `None` with a specified default value.

---

## Validation

Validation rules check each record before it is written to Neo4j. Rules are defined per node mapping or relationship mapping. When a record fails validation, the configured error strategy determines what happens.

### Configuration

```yaml
nodes:
  - source: employees
    label: Person
    key: emp_id
    properties:
      - source_field: emp_id
      - source_field: name
      - source_field: email
    validation:
      on_error: skip
      rules:
        - field: emp_id
          rule: required
        - field: email
          rule: regex
          params:
            pattern: "^[^@]+@[^@]+\\.[^@]+$"
          message: "Invalid email format"
        - field: age
          rule: min
          params:
            value: 0
        - field: age
          rule: max
          params:
            value: 150
```

### Error Strategies

| Strategy | Behavior |
|----------|----------|
| `skip` | Log a warning and skip the invalid record. Continue processing remaining records. This is the default. |
| `fail` | Immediately raise a `ValueError` and abort the entire pipeline. Use when data quality is critical and any bad record is unacceptable. |
| `dead_letter` | Collect invalid records in an error list (accessible via `ValidationResult.errors`). Continue processing valid records. The errors include the record index, the full record, and all error messages. |

### Validation Rules

| Rule | Parameters | Description |
|------|-----------|-------------|
| `required` | none | Field must not be `None` or `""` (empty string). |
| `type` | `expected`: one of `"str"`, `"int"`, `"float"`, `"bool"` | Field value must be the expected type, or convertible to it. The rule attempts conversion — if conversion fails, the rule fails. |
| `regex` | `pattern`: regular expression string | Field value must match the regular expression (uses `re.match`, so it matches from the start of the string). |
| `min` | `value`: number | Field value must be >= the minimum (compared as floats). |
| `max` | `value`: number | Field value must be <= the maximum (compared as floats). |
| `one_of` | `values`: list | Field value must be one of the specified values (exact match). |

### Custom Error Messages

Each rule can have an optional `message` field. When set, this message is used instead of the auto-generated default:

```yaml
rules:
  - field: email
    rule: regex
    params:
      pattern: "^[^@]+@[^@]+\\.[^@]+$"
    message: "Email must be in format user@domain.tld"
```

### Multiple Rules per Field

You can define multiple rules for the same field. All rules are checked — a record fails if any rule fails:

```yaml
rules:
  - field: age
    rule: required
  - field: age
    rule: min
    params:
      value: 0
  - field: age
    rule: max
    params:
      value: 150
```

### Validation Timing

Validation runs **after** reading from the source and **before** applying transforms and writing to Neo4j. This means:

1. Source data is read
2. Validation rules are applied to the raw source records
3. Invalid records are handled according to the error strategy
4. Valid records proceed to transform and write

---

## Execution Modes

### Standard Mode

The default mode. Reads data into Python memory and writes to Neo4j using the Python Neo4j driver. Suitable for datasets up to approximately 10 million records on a single machine.

```yaml
settings:
  execution_mode: standard   # This is the default
  batch_size: 1000
```

**Data flow:**

```
[CSV/JSON/SQL/REST] → Python Memory → Neo4j Python Driver → Neo4j
```

### Spark Mode

Distributed mode using PySpark. Reads data across a Spark cluster and writes to Neo4j using the Neo4j Spark Connector (a JVM library). Scales to billions of records.

```yaml
settings:
  execution_mode: spark
  spark:
    app_name: my-ingest-job
    partitions: 64
    neo4j_connector_batch_size: 10000
    spark_config:
      spark.sql.adaptive.enabled: "true"
      spark.jars.packages: "org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3"
```

**Data flow:**

```
[S3/HDFS/Delta/JDBC] → Spark Executors (distributed) → Neo4j Spark Connector → Neo4j
```

**Prerequisites:**
1. `pip install neo4j-ingest[spark]`
2. Neo4j Spark Connector JAR on the Spark classpath. Add via `spark.jars.packages` in `spark_config`, or pre-install on the cluster.
3. A Spark cluster (or `local[*]` for testing). On Databricks, the cluster is auto-managed.

**When to use Spark mode:**

| Scenario | Recommendation |
|----------|---------------|
| < 1M records | Standard mode |
| 1M – 10M records | Standard mode (tune `batch_size`) |
| 10M – 100M records | Spark mode with moderate parallelism |
| 100M+ records | Spark mode with high parallelism |
| Data already in S3/HDFS/Delta | Spark mode |
| Running on Databricks | Spark mode |
| Simple CSV on local disk | Standard mode |

---

## Resilience

### Retry with Backoff

Every Neo4j batch write is wrapped in retry logic. When a transient error occurs (network blip, Neo4j overloaded), the framework waits and retries automatically.

**Retryable exceptions:**
- `TransientError` (Neo4j driver)
- `ServiceUnavailable` (Neo4j driver)
- `OSError` (network errors)

**Configuration:**

```yaml
settings:
  retry_max_attempts: 3     # Total attempts (including first try)
  retry_base_delay: 1.0     # Base delay in seconds
```

**Backoff formula:**

```
delay = min(base_delay * 2^attempt, 30.0) + random_jitter
```

Where `jitter` is a random value between 0 and 10% of the delay. This prevents thundering herd effects when multiple workers retry simultaneously.

**Example with defaults (3 attempts, 1.0s base):**
1. Attempt 1: immediate
2. Attempt 2: ~1.0s delay (1.0 * 2^0 + jitter)
3. Attempt 3: ~2.0s delay (1.0 * 2^1 + jitter)

If all attempts fail, a `MaxRetriesExceeded` exception is raised with the number of attempts and the last error.

### Circuit Breaker

The `CircuitBreaker` class is available for programmatic use (not configured via YAML). It prevents calling a failing dependency repeatedly.

**States:**
- **CLOSED** (normal): Calls pass through. Failures increment a counter.
- **OPEN** (failing): All calls are rejected immediately with `CircuitBreakerOpen`. Entered after `failure_threshold` consecutive failures.
- **HALF_OPEN** (testing): After `recovery_timeout` seconds, one call is allowed through. If it succeeds, the circuit closes. If it fails, the circuit reopens.

**Usage (Python API):**

```python
from neo4j_ingest.resilience import CircuitBreaker

cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
result = cb.call(some_function, arg1, arg2)
```

### Health Checks

Before starting the pipeline, the framework verifies Neo4j is reachable by running `RETURN 1`. If the check fails, the pipeline aborts with a clear error message.

**Configuration:**

```yaml
settings:
  health_check: true    # Default: true
```

**Checked errors:**
- `ServiceUnavailable`: Neo4j is not running or not reachable
- `AuthError`: Wrong username or password
- Any other connection exception

Set `health_check: false` to skip (useful for dry-run mode or when you know Neo4j is available).

---

## Metrics and Observability

### Structured Logging

All operations log to Python's standard `logging` module under the `neo4j_ingest` logger hierarchy. Log levels:

| Level | What is logged |
|-------|----------------|
| `DEBUG` | Individual batch writes, rate limiter sleeps, SQL chunks, pagination details |
| `INFO` | Source reads (with record counts), node/relationship write totals, hook execution, progress reports, job summary |
| `WARNING` | Validation skips, retry attempts, registry overwrites |
| `ERROR` | Source failures, health check failures, circuit breaker opens |

Set the log level via CLI:

```bash
neo4j-ingest run config.yaml --log-level DEBUG
```

### Progress Reporting

For large datasets, the framework logs progress at regular intervals:

```
[nodes:Person] 5000/50000 (10%) — 2500 records/s
[nodes:Person] 10000/50000 (20%) — 2480 records/s
```

The reporting interval is `max(batch_size, 1000)` records.

### JSON Metrics

When `metrics_output` is set, the framework writes a JSON file after the job completes:

```yaml
settings:
  metrics_output: /tmp/ingest_metrics.json
```

**Example output:**

```json
{
  "job_id": "a1b2c3d4e5f6",
  "config_path": "",
  "status": "completed",
  "duration_seconds": 45.123,
  "total_records_processed": 150000,
  "total_records_failed": 23,
  "steps": [
    {
      "name": "source:employees",
      "status": "completed",
      "records_processed": 50000,
      "records_failed": 0,
      "duration_seconds": 2.5,
      "records_per_second": 20000.0,
      "error": null
    },
    {
      "name": "nodes:Person",
      "status": "completed",
      "records_processed": 49977,
      "records_failed": 23,
      "duration_seconds": 30.1,
      "records_per_second": 1660.4,
      "error": null
    }
  ],
  "errors": []
}
```

**Metrics fields:**

| Field | Description |
|-------|-------------|
| `job_id` | Unique 12-character hex ID for this run |
| `status` | `"completed"`, `"dry_run"`, or `"failed"` |
| `duration_seconds` | Total wall-clock time |
| `total_records_processed` | Sum across all steps |
| `total_records_failed` | Sum of validation failures |
| `steps` | Per-step metrics (source reads, node writes, relationship writes, hooks) |

Each step includes `name`, `status`, `records_processed`, `records_failed`, `duration_seconds`, `records_per_second`, and `error` (null if no error).

---

## Plugin System

The framework uses a registry-based plugin system. Source readers and transforms are registered by name. You can add custom types without modifying core code.

### Custom Source Types

Register a new source reader using the `@source_registry.register()` decorator:

```python
# my_plugin.py
from neo4j_ingest.registry import source_registry
from neo4j_ingest.config import SourceConfig


@source_registry.register("kafka")
def read_kafka(config: SourceConfig) -> list[dict]:
    """Read records from a Kafka topic."""
    from confluent_kafka import Consumer

    consumer = Consumer({
        "bootstrap.servers": config.connection_string,
        "group.id": config.headers.get("group_id", "neo4j-ingest"),
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe([config.query])  # topic name

    records = []
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            break
        if msg.error():
            continue
        records.append(json.loads(msg.value()))

    consumer.close()
    return records
```

**Usage in config:**

```yaml
sources:
  - name: events
    type: kafka
    connection_string: "broker1:9092,broker2:9092"
    query: my-topic
    headers:
      group_id: ingest-consumer
```

**Important:** Your plugin module must be imported before the pipeline runs. You can do this by importing it in your entry point or using Python's entry points mechanism.

### Custom Transforms

Register a new transform using the `@transform_registry.register()` decorator:

```python
# my_transforms.py
from neo4j_ingest.registry import transform_registry


@transform_registry.register("hash_email")
def hash_email(value, *, algorithm="sha256", **kwargs):
    """Hash an email address for privacy."""
    if value is None:
        return None
    import hashlib
    h = hashlib.new(algorithm)
    h.update(str(value).lower().encode())
    return h.hexdigest()


@transform_registry.register("split_first")
def split_first(value, *, delimiter=" ", **kwargs):
    """Return the first part of a split string."""
    if value is None:
        return None
    parts = str(value).split(delimiter)
    return parts[0] if parts else value
```

**Usage in config:**

```yaml
properties:
  - source_field: email
    target: email_hash
    transform:
      type: hash_email
      params:
        algorithm: sha256
  - source_field: full_name
    target: first_name
    transform:
      type: split_first
      params:
        delimiter: " "
```

### How Plugins Are Discovered

The plugin registry is a simple dictionary. When you call `@source_registry.register("mytype")`, the function is stored in the global `source_registry` object. The `read_source()` dispatcher looks up the type in this registry.

For the registry to contain your plugin, its module must be imported. Options:

1. **Import in your script:**
   ```python
   import my_plugin  # registers the source type
   from neo4j_ingest.engine import run_from_file
   run_from_file("config.yaml")
   ```

2. **Import in `__init__.py`** of a package.

3. **Use Python entry points** (advanced — for distributing plugins as packages).

---

## Architecture

### High-Level System Architecture

The framework acts as a bridge between heterogeneous data sources and a Neo4j graph database. It reads structured data, transforms and validates it, and writes it as nodes and relationships.

```mermaid
graph TB
    subgraph "Data Sources"
        CSV["CSV Files"]
        JSON_F["JSON Files"]
        SQL_DB["SQL Databases"]
        REST_API["REST APIs"]
        S3["S3 / HDFS / GCS"]
        DELTA["Delta Lake"]
        JDBC["JDBC Sources"]
        CATALOG["Spark Catalog"]
    end

    subgraph "neo4j-ingest Framework"
        direction TB
        CONFIG["Config Loader<br/>(YAML / JSON)"]
        ENV["Env Var Resolver<br/>(${VAR:-default})"]
        PYDANTIC["Pydantic Validator<br/>(Type-safe config)"]

        subgraph "Source Layer"
            REGISTRY_S["Source Registry<br/>(Plugin System)"]
            STD_READERS["Standard Readers<br/>(csv, json, sql, rest)"]
            SPARK_READERS["Spark Readers<br/>(parquet, delta, jdbc, table)"]
        end

        subgraph "Processing Layer"
            VALIDATOR["Record Validator<br/>(required, type, regex, min, max, one_of)"]
            TRANSFORMER["Transform Pipeline<br/>(to_int, lowercase, template, ...)"]
            CYPHER_GEN["Cypher Generator<br/>(MERGE queries)"]
        end

        subgraph "Write Layer"
            NEO4J_WRITER["Neo4j Writer<br/>(Python Driver)"]
            SPARK_WRITER["Spark Writer<br/>(Neo4j Spark Connector)"]
        end

        subgraph "Infrastructure"
            RETRY["Retry + Backoff"]
            CIRCUIT["Circuit Breaker"]
            HEALTH["Health Check"]
            METRICS_M["Metrics Collector"]
            PROGRESS["Progress Reporter"]
        end
    end

    NEO4J[("Neo4j<br/>Graph Database")]

    CSV --> STD_READERS
    JSON_F --> STD_READERS
    SQL_DB --> STD_READERS
    REST_API --> STD_READERS
    S3 --> SPARK_READERS
    DELTA --> SPARK_READERS
    JDBC --> SPARK_READERS
    CATALOG --> SPARK_READERS

    CONFIG --> ENV --> PYDANTIC

    STD_READERS --> VALIDATOR
    SPARK_READERS --> VALIDATOR
    VALIDATOR --> TRANSFORMER --> CYPHER_GEN
    CYPHER_GEN --> NEO4J_WRITER --> NEO4J
    CYPHER_GEN --> SPARK_WRITER --> NEO4J
    NEO4J_WRITER --> RETRY
    HEALTH --> NEO4J
```

### Module Dependency Map

Each module has a specific responsibility. The dependency arrows show which module imports from which. The design follows a layered architecture where higher-level modules depend on lower-level ones, never the reverse.

```mermaid
graph LR
    subgraph "Entry Points"
        CLI["cli.py<br/>Click commands"]
    end

    subgraph "Orchestration"
        ENGINE["engine.py<br/>Pipeline orchestrator"]
    end

    subgraph "Core Modules"
        CONFIG["config.py<br/>Pydantic models"]
        GRAPH["graph.py<br/>Neo4j writer"]
        SOURCES["sources.py<br/>Source readers"]
        SPARK_S["spark_sources.py<br/>Spark readers"]
        SPARK_W["spark_writer.py<br/>Spark writer"]
    end

    subgraph "Support Modules"
        ENV["env.py<br/>Env var substitution"]
        TRANSFORMS["transforms.py<br/>Data transforms"]
        VALIDATION["validation.py<br/>Record validation"]
        REGISTRY["registry.py<br/>Plugin registry"]
        RESILIENCE["resilience.py<br/>Retry + circuit breaker"]
        METRICS["metrics.py<br/>Job metrics"]
    end

    CLI --> ENGINE
    ENGINE --> CONFIG
    ENGINE --> GRAPH
    ENGINE --> SOURCES
    ENGINE --> SPARK_S
    ENGINE --> SPARK_W
    ENGINE --> METRICS
    ENGINE --> RESILIENCE
    ENGINE --> VALIDATION

    CONFIG --> ENV

    GRAPH --> CONFIG
    GRAPH --> TRANSFORMS
    GRAPH --> RESILIENCE
    GRAPH --> METRICS

    SOURCES --> CONFIG
    SOURCES --> REGISTRY

    SPARK_S --> CONFIG
    SPARK_S --> REGISTRY

    SPARK_W --> CONFIG

    TRANSFORMS --> REGISTRY
```

### Pipeline Execution Flow

This diagram shows the complete step-by-step execution of a pipeline run, from loading the config file to emitting the final metrics report.

```mermaid
flowchart TD
    START([Start: neo4j-ingest run config.yaml]) --> LOAD_FILE[Load YAML / JSON file]
    LOAD_FILE --> RESOLVE_ENV["Resolve env vars<br/>${VAR:-default} → actual values"]
    RESOLVE_ENV --> VALIDATE_CONFIG["Validate with Pydantic<br/>(type checking, required fields)"]
    VALIDATE_CONFIG --> CHECK_MODE{execution_mode?}

    CHECK_MODE -->|standard| STANDARD_PATH
    CHECK_MODE -->|spark| SPARK_PATH

    subgraph STANDARD_PATH["Standard Mode"]
        direction TB
        HEALTH_STD["Health check Neo4j<br/>(RETURN 1)"] --> READ_STD{parallel_sources?}
        READ_STD -->|true| PARALLEL["ThreadPoolExecutor<br/>(max_workers threads)"]
        READ_STD -->|false| SERIAL["Sequential read"]
        PARALLEL --> SOURCES_DONE_STD["All sources loaded<br/>into Python memory"]
        SERIAL --> SOURCES_DONE_STD
    end

    subgraph SPARK_PATH["Spark Mode"]
        direction TB
        INIT_SPARK["Init SparkSession<br/>(app_name, master, config)"] --> READ_SPARK["Read sources via Spark<br/>(distributed across executors)"]
        READ_SPARK --> SOURCES_DONE_SPARK["All sources loaded<br/>as DataFrames / record lists"]
    end

    STANDARD_PATH --> DRY_CHECK
    SPARK_PATH --> DRY_CHECK

    DRY_CHECK{dry_run?}
    DRY_CHECK -->|yes| DRY_LOG["Log record counts<br/>per source"] --> METRICS_OUT
    DRY_CHECK -->|no| PRE_HOOKS

    PRE_HOOKS["Run pre_hooks<br/>(CREATE INDEX, CREATE CONSTRAINT)"]
    PRE_HOOKS --> NODE_LOOP

    subgraph NODE_LOOP["For each node mapping"]
        direction TB
        N_VALIDATE["Validate records<br/>(skip / fail / dead_letter)"]
        N_VALIDATE --> N_TRANSFORM["Apply per-field transforms<br/>(to_int, lowercase, etc.)"]
        N_TRANSFORM --> N_CYPHER["Generate MERGE Cypher<br/>MERGE (n:Label {key: row.key})"]
        N_CYPHER --> N_BATCH["Write in batches<br/>(batch_size records per tx)"]
        N_BATCH --> N_RETRY["Retry on transient errors<br/>(exponential backoff)"]
    end

    NODE_LOOP --> REL_LOOP

    subgraph REL_LOOP["For each relationship mapping"]
        direction TB
        R_VALIDATE["Validate records"]
        R_VALIDATE --> R_TRANSFORM["Apply per-field transforms"]
        R_TRANSFORM --> R_CYPHER["Generate MERGE Cypher<br/>MATCH (a)...MATCH (b)...MERGE (a)-[r]->(b)"]
        R_CYPHER --> R_BATCH["Write in batches"]
        R_BATCH --> R_RETRY["Retry on transient errors"]
    end

    REL_LOOP --> POST_HOOKS["Run post_hooks<br/>(aggregations, cleanup)"]
    POST_HOOKS --> METRICS_OUT

    METRICS_OUT["Emit metrics<br/>(log summary + JSON file)"]
    METRICS_OUT --> DONE([Done: IngestResult])
```

### Config Processing Pipeline

This diagram shows how a raw config file is transformed into a fully validated, type-safe configuration object. Every string in the config passes through environment variable resolution before Pydantic validates the structure.

```mermaid
flowchart LR
    subgraph "Input"
        YAML_FILE["config.yaml<br/>(raw text)"]
    end

    subgraph "Stage 1: Parse"
        YAML_PARSE["PyYAML / JSON<br/>parser"]
        RAW_DICT["Raw Python dict<br/>(strings still have ${...})"]
    end

    subgraph "Stage 2: Env Resolution"
        WALK["Recursive walker<br/>(env.resolve_env_vars)"]
        PATTERN["Pattern: ${VAR:-default}"]
        LOOKUP["os.environ lookup"]
        RESOLVED["Resolved dict<br/>(all strings resolved)"]
    end

    subgraph "Stage 3: Validation"
        PYDANTIC["Pydantic v2<br/>model_validate()"]
        MODELS["Typed models:<br/>Neo4jConnection<br/>JobSettings<br/>SourceConfig<br/>NodeMapping<br/>RelationshipMapping<br/>SchemaHook"]
    end

    subgraph "Output"
        CONFIG_OBJ["IngestConfig<br/>(fully validated,<br/>type-safe object)"]
    end

    YAML_FILE --> YAML_PARSE --> RAW_DICT
    RAW_DICT --> WALK
    WALK --> PATTERN --> LOOKUP --> RESOLVED
    RESOLVED --> PYDANTIC --> MODELS --> CONFIG_OBJ

    style CONFIG_OBJ fill:#2d5,stroke:#000,color:#fff
```

### Record Processing Detail

For each record, the framework applies validation, then transforms, then maps the fields to a Cypher-compatible row format. This diagram shows exactly what happens to a single record as it flows through the system.

```mermaid
flowchart TD
    subgraph "Source Record (raw)"
        RAW["{<br/>&nbsp;&nbsp;emp_id: '42',<br/>&nbsp;&nbsp;full_name: '  Alice  ',<br/>&nbsp;&nbsp;email: 'Alice@CORP.com',<br/>&nbsp;&nbsp;age: '28'<br/>}"]
    end

    RAW --> VAL_CHECK

    subgraph "Validation"
        VAL_CHECK{"Apply rules<br/>(required, regex, min, max)"}
        VAL_CHECK -->|pass| VAL_OK["Record is valid"]
        VAL_CHECK -->|fail + skip| VAL_SKIP["Record skipped<br/>(logged as warning)"]
        VAL_CHECK -->|fail + fail| VAL_ABORT["Pipeline aborts<br/>(ValueError raised)"]
        VAL_CHECK -->|fail + dead_letter| VAL_DL["Record saved to<br/>error list"]
    end

    VAL_OK --> TRANSFORM

    subgraph "Transform Pipeline (per field)"
        TRANSFORM["For each PropertyMapping:"]
        T1["emp_id → to_int<br/>'42' → 42"]
        T2["full_name → strip → uppercase<br/>'  Alice  ' → 'Alice' → 'ALICE'"]
        T3["email → lowercase<br/>'Alice@CORP.com' → 'alice@corp.com'"]
        T4["age → to_int<br/>'28' → 28"]
        TRANSFORM --> T1
        TRANSFORM --> T2
        TRANSFORM --> T3
        TRANSFORM --> T4
    end

    T1 --> ROW_MAP
    T2 --> ROW_MAP
    T3 --> ROW_MAP
    T4 --> ROW_MAP

    subgraph "Row Mapping"
        ROW_MAP["Map source_field → target<br/>(full_name → name)"]
        MAPPED["{<br/>&nbsp;&nbsp;emp_id: 42,<br/>&nbsp;&nbsp;name: 'ALICE',<br/>&nbsp;&nbsp;email: 'alice@corp.com',<br/>&nbsp;&nbsp;age: 28<br/>}"]
    end

    ROW_MAP --> MAPPED --> BATCH

    subgraph "Batch Write"
        BATCH["Collect into batch<br/>(up to batch_size rows)"]
        CYPHER["UNWIND $rows AS row<br/>MERGE (n:Person {emp_id: row.emp_id})<br/>SET n.name = row.name,<br/>&nbsp;&nbsp;&nbsp;&nbsp;n.email = row.email,<br/>&nbsp;&nbsp;&nbsp;&nbsp;n.age = row.age"]
        BATCH --> CYPHER
    end

    CYPHER --> NEO4J[("Neo4j")]
```

### Standard vs. Spark Execution Comparison

The framework supports two execution modes. This diagram shows the architectural differences between them — the same config file works with both, only `execution_mode` changes.

```mermaid
graph TB
    subgraph "Standard Mode (execution_mode: standard)"
        direction TB
        S_SRC["Source Readers<br/>(Python: csv, json,<br/>requests, sqlalchemy)"]
        S_MEM["Python Memory<br/>(list[dict])"]
        S_BATCH["Batch Processor<br/>(UNWIND $rows)"]
        S_DRIVER["Neo4j Python Driver<br/>(bolt protocol)"]
        S_NEO4J[("Neo4j")]

        S_SRC -->|"read into<br/>memory"| S_MEM
        S_MEM -->|"chunk into<br/>batches"| S_BATCH
        S_BATCH -->|"execute per<br/>batch tx"| S_DRIVER
        S_DRIVER -->|"bolt"| S_NEO4J
    end

    subgraph "Spark Mode (execution_mode: spark)"
        direction TB
        K_SRC["Spark Source Readers<br/>(PySpark: parquet, delta,<br/>jdbc, csv, json, table)"]
        K_DF["Spark DataFrames<br/>(distributed across executors)"]
        K_SELECT["DataFrame.select()<br/>(column mapping + aliasing)"]
        K_CONNECTOR["Neo4j Spark Connector<br/>(org.neo4j.spark.DataSource)"]
        K_NEO4J[("Neo4j")]

        K_SRC -->|"distributed<br/>read"| K_DF
        K_DF -->|"repartition +<br/>select"| K_SELECT
        K_SELECT -->|"parallel write<br/>(one per partition)"| K_CONNECTOR
        K_CONNECTOR -->|"bolt<br/>(N connections)"| K_NEO4J
    end

    CONFIG["Same YAML Config<br/>(only execution_mode differs)"]
    CONFIG -->|"standard"| S_SRC
    CONFIG -->|"spark"| K_SRC
```

### Resilience Patterns

#### Retry with Exponential Backoff

Every Neo4j batch write is wrapped in retry logic. When a transient error occurs, the framework waits with exponentially increasing delays before retrying.

```mermaid
sequenceDiagram
    participant Engine as Engine
    participant Retry as retry()
    participant Neo4j as Neo4j

    Engine->>Retry: write_batch(rows)

    Retry->>Neo4j: Attempt 1: UNWIND $rows ...
    Neo4j-->>Retry: TransientError

    Note over Retry: Wait 1.0s + jitter

    Retry->>Neo4j: Attempt 2: UNWIND $rows ...
    Neo4j-->>Retry: TransientError

    Note over Retry: Wait 2.0s + jitter

    Retry->>Neo4j: Attempt 3: UNWIND $rows ...
    Neo4j-->>Retry: Success

    Retry-->>Engine: Result
```

**Backoff formula:** `delay = min(base_delay * 2^attempt, 30.0) + random(0, delay * 0.1)`

#### Circuit Breaker State Machine

The circuit breaker prevents hammering a failing Neo4j instance. It has three states with automatic transitions.

```mermaid
stateDiagram-v2
    [*] --> CLOSED

    CLOSED --> CLOSED : Success — reset failure count
    CLOSED --> OPEN : Failure count >= threshold (default 5)

    OPEN --> OPEN : Call rejected — raises CircuitBreakerOpen
    OPEN --> HALF_OPEN : After recovery_timeout (default 30s)

    HALF_OPEN --> CLOSED : Test call succeeds — reset all counters
    HALF_OPEN --> OPEN : Test call fails — restart timeout
```

**States explained:**
- **CLOSED** (normal operation): All calls pass through. Each failure increments a counter. When failures reach `failure_threshold`, the circuit opens.
- **OPEN** (failing fast): All calls are rejected immediately with `CircuitBreakerOpen`. No requests reach Neo4j. After `recovery_timeout` seconds, the circuit transitions to half-open.
- **HALF_OPEN** (testing recovery): Exactly one call is allowed through. If it succeeds, the circuit closes (full recovery). If it fails, the circuit reopens (still broken).

### Plugin Registry Architecture

The plugin system uses a decorator-based registry pattern. Sources and transforms register themselves at import time. The dispatcher looks up handlers by name at runtime.

```mermaid
flowchart TD
    subgraph "Registration (import time)"
        REG_SOURCE["@source_registry.register('csv')"]
        REG_TRANSFORM["@transform_registry.register('to_int')"]
        SOURCES_MOD["sources.py<br/>(csv, json, sql, rest)"]
        SPARK_MOD["spark_sources.py<br/>(spark_csv, spark_parquet, ...)"]
        TRANSFORM_MOD["transforms.py<br/>(to_int, lowercase, ...)"]
        CUSTOM["my_plugin.py<br/>(kafka, custom_transform)"]

        SOURCES_MOD -->|"registers at import"| REG_SOURCE
        SPARK_MOD -->|"registers at import"| REG_SOURCE
        TRANSFORM_MOD -->|"registers at import"| REG_TRANSFORM
        CUSTOM -->|"registers at import"| REG_SOURCE
        CUSTOM -->|"registers at import"| REG_TRANSFORM
    end

    subgraph "Registry (global dict)"
        S_REG["source_registry<br/>{<br/>&nbsp;&nbsp;'csv': read_csv,<br/>&nbsp;&nbsp;'json': read_json,<br/>&nbsp;&nbsp;'sql': read_sql,<br/>&nbsp;&nbsp;'rest': read_rest,<br/>&nbsp;&nbsp;'spark_csv': read_spark_csv,<br/>&nbsp;&nbsp;'spark_parquet': read_spark_parquet,<br/>&nbsp;&nbsp;'spark_delta': read_spark_delta,<br/>&nbsp;&nbsp;'spark_jdbc': read_spark_jdbc,<br/>&nbsp;&nbsp;'spark_table': read_spark_table,<br/>&nbsp;&nbsp;'kafka': read_kafka<br/>}"]
        T_REG["transform_registry<br/>{<br/>&nbsp;&nbsp;'to_int': to_int_fn,<br/>&nbsp;&nbsp;'to_float': to_float_fn,<br/>&nbsp;&nbsp;'lowercase': lowercase_fn,<br/>&nbsp;&nbsp;...<br/>}"]
    end

    REG_SOURCE --> S_REG
    REG_TRANSFORM --> T_REG

    subgraph "Dispatch (runtime)"
        READ_SOURCE["read_source(config)<br/>↓<br/>handler = source_registry.get(config.type)<br/>return handler(config)"]
        APPLY_TRANSFORM["apply_transform(value, config)<br/>↓<br/>fn = transform_registry.get(config.type)<br/>return fn(value, **config.params)"]
    end

    S_REG --> READ_SOURCE
    T_REG --> APPLY_TRANSFORM
```

### Cypher Generation Detail

The framework generates parameterized Cypher queries that use `UNWIND` for batched operations. This diagram shows exactly how a node mapping and a relationship mapping are translated into Cypher.

**Node Cypher Generation:**

```
NodeMapping:                          Generated Cypher:
┌──────────────────────┐              ┌──────────────────────────────────────┐
│ label: Person        │              │ UNWIND $rows AS row                  │
│ key: emp_id          │──────────▶   │ MERGE (n:Person {emp_id: row.emp_id})│
│ properties:          │              │ SET n.name = row.name,               │
│   - source_field: id │              │     n.email = row.email              │
│     target: emp_id   │              └──────────────────────────────────────┘
│   - source_field: nm │
│     target: name     │              Row mapping:
│   - source_field: em │              ┌──────────────────────────────────────┐
│     target: email    │              │ {id: 1, nm: "Alice", em: "a@b.com"} │
└──────────────────────┘              │           ↓ rename fields            │
                                      │ {emp_id: 1, name: "Alice",          │
                                      │  email: "a@b.com"}                  │
                                      └──────────────────────────────────────┘
```

**Relationship Cypher Generation:**

```
RelationshipMapping:                  Generated Cypher:
┌──────────────────────────┐          ┌───────────────────────────────────────┐
│ rel_type: WORKS_IN       │          │ UNWIND $rows AS row                   │
│ from_label: Person       │          │ MATCH (a:Person {emp_id: row.from_val})│
│ from_key: emp_id         │────────▶ │ MATCH (b:Dept {dept_id: row.to_val}) │
│ from_field: emp_id       │          │ MERGE (a)-[r:WORKS_IN]->(b)          │
│ to_label: Dept           │          │ SET r.since = row.since              │
│ to_key: dept_id          │          └───────────────────────────────────────┘
│ to_field: dept_id        │
│ properties:              │          Row mapping:
│   - source_field: start  │          ┌───────────────────────────────────────┐
│     target: since        │          │ {emp_id: 1, dept_id: 10, start: ".."}│
└──────────────────────────┘          │           ↓ map special fields       │
                                      │ {from_val: 1, to_val: 10,            │
                                      │  since: "2024-01-01"}                │
                                      └───────────────────────────────────────┘
```

**Key concepts:**
- `from_val` and `to_val` are internal aliases. The framework renames `from_field` → `from_val` and `to_field` → `to_val` so the Cypher template is consistent regardless of the source field names.
- The `MERGE` keyword ensures idempotency — running the same ingestion twice produces the same result. Nodes and relationships are matched by their key fields and updated (not duplicated).
- The `UNWIND $rows AS row` pattern sends a batch of records in a single transaction, which is significantly faster than executing individual `MERGE` statements.

### Spark Mode Internals

When running in Spark mode, writes use the Neo4j Spark Connector (a JVM library) instead of the Python Neo4j driver. The Spark Connector opens parallel bolt connections from each executor partition.

```mermaid
flowchart TB
    subgraph "Spark Driver (Python)"
        ENGINE_SP["engine._run_spark()"]
        SPARK_SESSION["SparkSession<br/>(configured via spark_config)"]
        WRITER["SparkNeo4jWriter"]

        ENGINE_SP --> SPARK_SESSION
        ENGINE_SP --> WRITER
    end

    subgraph "Spark Executors (distributed JVM)"
        E1["Executor 1<br/>Partition 0"]
        E2["Executor 2<br/>Partition 1"]
        E3["Executor 3<br/>Partition 2"]
        EN["Executor N<br/>Partition N-1"]
    end

    subgraph "Neo4j Cluster"
        NEO4J_1[("Neo4j")]
    end

    WRITER -->|"df.repartition(N)<br/>.write.format('org.neo4j.spark.DataSource')<br/>.option('query', cypher)"| E1
    WRITER -->|""| E2
    WRITER -->|""| E3
    WRITER -->|""| EN

    E1 -->|"bolt"| NEO4J_1
    E2 -->|"bolt"| NEO4J_1
    E3 -->|"bolt"| NEO4J_1
    EN -->|"bolt"| NEO4J_1
```

**Spark Connector write options:**

| Option | Value | Purpose |
|--------|-------|---------|
| `url` | Neo4j bolt URI | Connection endpoint |
| `authentication.type` | `basic` | Auth method |
| `authentication.basic.username` | Neo4j username | Auth credential |
| `authentication.basic.password` | Neo4j password | Auth credential |
| `database` | Database name | Target database |
| `batch.size` | e.g. `5000` | Records per write batch per executor |
| `query` | MERGE Cypher | The write query (uses `event.` prefix) |

**Important difference:** In Spark mode, the Cypher uses `event.` prefix instead of `row.`:

```cypher
-- Standard mode (Python driver):
UNWIND $rows AS row
MERGE (n:Person {id: row.id})

-- Spark mode (Spark Connector):
MERGE (n:Person {id: event.id})
```

The Spark Connector automatically iterates over DataFrame rows and binds each one as `event`.

### Validation Flow Detail

Records are validated before transforms are applied. Each record is checked against all rules defined in the mapping. The error strategy determines what happens when a record fails.

```mermaid
flowchart TD
    INPUT["Input: list[dict]<br/>(raw source records)"]
    INPUT --> FOR_EACH

    FOR_EACH["For each record"]
    FOR_EACH --> CHECK_RULES

    subgraph "Rule Evaluation"
        CHECK_RULES["Apply all ValidationRules"]
        R1{"required?<br/>field not None/empty"}
        R2{"type?<br/>matches expected type"}
        R3{"regex?<br/>re.match(pattern)"}
        R4{"min?<br/>value >= min"}
        R5{"max?<br/>value <= max"}
        R6{"one_of?<br/>value in allowed list"}

        CHECK_RULES --> R1 --> R2 --> R3 --> R4 --> R5 --> R6
    end

    R6 --> RESULT{All rules passed?}

    RESULT -->|yes| VALID["Add to valid_records"]
    RESULT -->|no| STRATEGY{Error Strategy}

    STRATEGY -->|"skip"| LOG_SKIP["Log warning:<br/>'Skipping record #N: field X failed rule Y'<br/>Continue processing"]
    STRATEGY -->|"fail"| RAISE["Raise ValueError<br/>Pipeline aborts immediately"]
    STRATEGY -->|"dead_letter"| DL["Add to errors list:<br/>{index, record, messages}<br/>Continue processing"]

    VALID --> OUTPUT
    LOG_SKIP --> OUTPUT
    DL --> OUTPUT

    OUTPUT["ValidationResult:<br/>- valid_records: list[dict]<br/>- errors: list[ValidationError]<br/>- total_errors: int"]
```

### Metrics Collection Architecture

The metrics system tracks timing and record counts for every step of the pipeline. Metrics are collected via a context manager that wraps each operation.

```mermaid
flowchart LR
    subgraph "JobMetrics"
        JOB["job_id: 'a1b2c3d4e5f6'<br/>status: 'completed'<br/>start_time / end_time<br/>duration_seconds"]
    end

    subgraph "StepMetrics (one per operation)"
        S1["source:employees<br/>records: 50000<br/>duration: 2.5s<br/>rate: 20000/s"]
        S2["pre_hooks<br/>records: 3<br/>duration: 0.2s"]
        S3["nodes:Person<br/>records: 49977<br/>failed: 23<br/>duration: 30.1s<br/>rate: 1660/s"]
        S4["rels:WORKS_IN<br/>records: 48000<br/>duration: 25.3s<br/>rate: 1897/s"]
        S5["post_hooks<br/>records: 2<br/>duration: 1.5s"]
    end

    JOB --> S1
    JOB --> S2
    JOB --> S3
    JOB --> S4
    JOB --> S5

    subgraph "Output"
        LOG["Structured log<br/>(INFO level)"]
        JSON_OUT["JSON file<br/>(metrics_output path)"]
    end

    JOB --> LOG
    JOB --> JSON_OUT
```

Each step is timed using the `track_step()` context manager:

```python
step = job_metrics.add_step("nodes:Person")
with track_step(step):
    # ... do work ...
    step.records_processed = count
# step.duration_seconds and step.records_per_second are auto-computed
```

### Module Structure

```
src/neo4j_ingest/
├── __init__.py          # Package version
├── cli.py               # CLI entry point (click commands: run, validate, dry-run)
├── config.py            # Pydantic models for config validation
├── engine.py            # Pipeline orchestrator (standard + spark modes)
├── env.py               # Environment variable substitution
├── graph.py             # Neo4j writer (batched MERGE via Python driver)
├── metrics.py           # Job metrics, step metrics, progress reporter
├── registry.py          # Plugin registry for sources and transforms
├── resilience.py        # Retry, circuit breaker, health check
├── sources.py           # Built-in source readers (CSV, JSON, SQL, REST)
├── spark_sources.py     # Spark source readers (Parquet, Delta, JDBC, etc.)
├── spark_writer.py      # Spark-based Neo4j writer (via Spark Connector)
├── transforms.py        # Built-in transforms (type casting, string ops)
└── validation.py        # Record-level validation with error strategies
```

---

## Python API

You can use the framework programmatically instead of through the CLI.

### Running from a Config File

```python
from neo4j_ingest.engine import run_from_file

result = run_from_file("config.yaml")
print(f"Nodes: {result.total_nodes}")
print(f"Relationships: {result.total_relationships}")
print(f"Skipped: {result.records_skipped}")
```

### Running from a Config Object

```python
from neo4j_ingest.config import (
    IngestConfig, Neo4jConnection, SourceConfig,
    NodeMapping, PropertyMapping, JobSettings,
)
from neo4j_ingest.engine import run

config = IngestConfig(
    neo4j=Neo4jConnection(
        uri="bolt://localhost:7687",
        password="secret",
    ),
    settings=JobSettings(batch_size=1000, health_check=False),
    sources=[
        SourceConfig(name="data", type="csv", path="data.csv"),
    ],
    nodes=[
        NodeMapping(
            source="data",
            label="Person",
            key="id",
            properties=[
                PropertyMapping(source_field="id"),
                PropertyMapping(source_field="name"),
            ],
        ),
    ],
)

result = run(config, dry_run=False)
```

### Dry Run

```python
result = run_from_file("config.yaml", dry_run=True)
# result.total_nodes == 0 (nothing written)
# result.metrics.status == "dry_run"
```

### Validate Only

```python
from neo4j_ingest.engine import validate_config

config = validate_config("config.yaml")
print(f"Sources: {len(config.sources)}")
print(f"Nodes: {len(config.nodes)}")
```

### Accessing Metrics

```python
result = run_from_file("config.yaml")
metrics = result.metrics

print(metrics.to_json(indent=2))  # Full JSON metrics
print(metrics.duration_seconds)    # Total time
print(metrics.total_records_processed)

for step in metrics.steps:
    print(f"{step.name}: {step.records_processed} records in {step.duration_seconds}s")
```

---

## Examples

The `examples/` directory contains ready-to-use config files:

| File | Description |
|------|-------------|
| `company_graph.yaml` | Basic example: CSV files → Person and Department nodes with WORKS_IN relationships |
| `enterprise_example.yaml` | Full enterprise features: env vars, hooks, transforms, validation, metrics |
| `spark_datalake.yaml` | Spark mode: Parquet + Delta + JDBC + Unity Catalog → Neo4j with distributed writes |

---

## Testing

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_transforms.py

# Run a specific test
pytest tests/test_transforms.py::TestBuiltinTransforms::test_to_int
```

### Test Structure

```
tests/
├── test_config.py         # Config loading, validation, env var substitution
├── test_engine.py         # Pipeline orchestration (mocked Neo4j + sources)
├── test_env.py            # Environment variable substitution
├── test_graph.py          # Cypher generation, row mapping, transforms
├── test_metrics.py        # Step metrics, job metrics, tracking
├── test_registry.py       # Plugin registry
├── test_resilience.py     # Retry, circuit breaker
├── test_sources.py        # CSV/JSON reading, JSON root resolution
├── test_spark_sources.py  # Spark source readers (mocked PySpark)
├── test_spark_writer.py   # Spark Neo4j writer (mocked PySpark)
├── test_transforms.py     # All built-in transforms
└── test_validation.py     # Validation rules, error strategies
```

All Spark tests use mocked PySpark — they run without PySpark installed.

---

## Troubleshooting

### Common Errors

**`MissingEnvironmentVariable: Required environment variable 'X' is not set`**
You used `${X}` in the config but the environment variable `X` is not set. Either set the variable or add a default: `${X:-default_value}`.

**`CSV source requires 'path'`**
A source with `type: csv` is missing the `path` field.

**`Node mapping references unknown source 'X'`**
A node mapping's `source` field references a name that does not exist in the `sources` list. Check for typos.

**`Neo4j health check failed`**
The framework could not connect to Neo4j. Verify the URI, username, password, and that Neo4j is running. Set `settings.health_check: false` to skip.

**`MaxRetriesExceeded: Failed after N attempts`**
All retry attempts for a Neo4j write failed. Check Neo4j logs, network connectivity, and consider increasing `retry_max_attempts`.

**`Unsupported source type: 'X'`**
The source type is not registered. Built-in types: `csv`, `json`, `sql`, `rest`. Spark types require `pip install neo4j-ingest[spark]`. Custom types require importing the plugin module before running.

**`Unknown transform type 'X'`**
The transform name is not registered. Check spelling. Available built-in transforms: `to_string`, `to_int`, `to_float`, `to_bool`, `to_datetime`, `uppercase`, `lowercase`, `strip`, `replace`, `default`, `template`.

**`ModuleNotFoundError: No module named 'pyspark'`**
You set `execution_mode: spark` or used a `spark_*` source type without installing PySpark. Run `pip install neo4j-ingest[spark]`.
