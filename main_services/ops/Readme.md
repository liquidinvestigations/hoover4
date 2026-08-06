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

## Rate-limit environment (paste into the `hoover4-website` service)

The website rate limiter (`website/backend/src/api/rate_limit.rs`) defaults every knob
in Rust, so the stack runs unconfigured. These are the same names and values, ready to
paste into `docker/docker-compose.yaml` for the integrator to tune — **the block is not
in the compose file yet** (tracked in `plans/3-auth-and-ai/open-questions.md`).

```yaml
    environment:
      # Chat messages per minute per user. Default 40: ~10x the fastest
      # substantive agent turn measured on the dev GPU (16.2 s for a full
      # research turn; a degenerate 4.4 s list_collections turn was ignored as
      # not a real question). Production hardware should re-measure.
      HOOVER4_RATE_CHAT_PER_MINUTE: "40"
      # API (server-function) calls per minute per user, guests included.
      # Default 1000. Measured baseline on this host: a scripted 5-minute
      # flood of representative calls (search + admin + document fetches)
      # recorded 1380 api_events = 276 calls/min sustained; a realistic
      # human sweep of every route is ~100 calls total. 1000 is ~10x the
      # human sweep and ~3.6x even the scripted flood.
      HOOVER4_RATE_API_PER_MINUTE: "1000"
      # Window ladder factors: budget in a window is X * minutes * factor, so
      # the sustained rate decays the longer the burst lasts. 0 disables the
      # window. Defaults shown.
      HOOVER4_RATE_CHAT_W10M_FACTOR: "1.00"
      HOOVER4_RATE_CHAT_W30M_FACTOR: "0.75"
      HOOVER4_RATE_CHAT_W1H_FACTOR: "0.50"
      HOOVER4_RATE_CHAT_W6H_FACTOR: "0.30"
      HOOVER4_RATE_CHAT_W24H_FACTOR: "0.20"
      HOOVER4_RATE_API_W10M_FACTOR: "1.00"
      HOOVER4_RATE_API_W30M_FACTOR: "0.75"
      HOOVER4_RATE_API_W1H_FACTOR: "0.50"
      HOOVER4_RATE_API_W6H_FACTOR: "0.30"
      HOOVER4_RATE_API_W24H_FACTOR: "0.20"
```

The counters are **in-process** (a `Mutex<HashMap>` in the website, pruned on access),
correct only while the website is a single container. Redis was considered and rejected
for now: the container runs with `--maxmemory-policy allkeys-lru`, which would silently
evict counters under memory pressure — a limiter that quietly stops limiting is worse
than none. Scaling the website out needs a shared store, and that is the point at which
Redis gets its own database index and eviction policy.

How to re-measure the API baseline once `api_events` is recording:

```bash
docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 \
  -q "SELECT count() FROM Hoover4_Processing.api_events WHERE event_ts >= now() - INTERVAL 5 MINUTE"
```

Drive a browser across every page as fast as possible for 5 minutes, read the count,
and set `HOOVER4_RATE_API_PER_MINUTE` to 10x that rate (count / 5 * 10). The baseline
above was measured this way on 2026-08-05 (scripted flood, 1380 calls / 5 min).

