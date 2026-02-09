# Operations

This directory provides the runtime environment for Hoover4 main services. The `docker/` folder contains Docker Compose definitions and configuration overrides used to run processing dependencies.

## Docker Compose Services

The stack includes:

- Workflow orchestration: Temporal with Cassandra and Elasticsearch backends, plus the Temporal UI.
- Primary data stores: ClickHouse for structured processing tables, Manticore for text search, MinIO for object storage, and Redis for auxiliary caching.
- Parsing and enrichment: Apache Tika and OCR-related workers that connect to the processing pipeline.
- Monitoring and admin UIs: ClickHouse monitoring and CH-UI.

## Common Endpoints (Local)

- Temporal UI: `http://localhost:8081`
- ClickHouse HTTP: `http://localhost:8123`
- ClickHouse Native: `http://localhost:9000`
- Manticore SQL: `http://localhost:9306`
- Manticore HTTP: `http://localhost:9308`
- Apache Tika: `http://localhost:9998`
- MinIO Console: `http://localhost:8084` (default credentials are documented in Docker Compose)
- Redis: `tcp://localhost:6379`

## Technical Details

This directory provides Docker Compose configuration and runtime overrides for the processing stack and its dependencies, including Temporal, ClickHouse, Manticore, MinIO, Redis, and supporting UIs.

Configuration is organized under `docker/`, which includes compose files, `.env` values, service overrides, and helper scripts. Use `docker compose up -d` from `docker/` after setting environment variables in the local `.env` file.

## Navigation

-  [Go Back](../Readme.md)
# Ops

## Docker

The docker containers start up the following services:

### Web Interfaces

- **Temporal UI**: [http://localhost:8081](http://localhost:8081) - Temporal UI Dashboard
- **ClickHouse Monitoring 3000**: [http://localhost:3000](http://localhost:3000) - ClickHouse monitoring dashboard
- **CH-UI (ClickHouse UI) 5521**: [http://localhost:5521](http://localhost:5521) - ClickHouse web interface
- **Apache Tika**: [http://localhost:9998](http://localhost:9998) - Document parsing service
- **Minio**: [http://localhost:8084](http://localhost:8084) - Minio S3 Dashboard
  - `hoover4` / `hoover4-secret`

### Search Engines

- **Manticore Search**: [http://localhost:9306](http://localhost:9306) - Primary Manticore instance (SQL port)
- **Manticore Search HTTP**: [http://localhost:9308](http://localhost:9308) - Primary Manticore HTTP API
- **Manticore Search 2**: [http://localhost:19306](http://localhost:19306) - Secondary Manticore instance (SQL port)
- **Manticore Search 2 HTTP**: [http://localhost:19308](http://localhost:19308) - Secondary Manticore HTTP API
- **DejaVu (Elasticsearch UI)**: [http://localhost:1358](http://localhost:1358) - Elasticsearch data browser

### Database Connections

- **Redis**: [http://localhost:6379](http://localhost:6379) - Redis database (TCP, not HTTP)
- **ClickHouse Native**: [http://localhost:9000](http://localhost:9000) - ClickHouse native protocol
- **ClickHouse HTTP Interface**: [http://localhost:8123](http://localhost:8123) - ClickHouse database HTTP API
- **Temporal**: [http://localhost:7233](http://localhost:7233) - Temporal workflow engine
- **Temporal Cassandra**: [http://localhost:9042](http://localhost:9042) - Temporal's Cassandra database
- **Temporal Elasticsearch**: [http://localhost:9200](http://localhost:9200) - Elasticsearch REST API

