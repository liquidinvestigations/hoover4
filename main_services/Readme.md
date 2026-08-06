# Hoover4 Main Services

This directory contains the core data plane for Hoover4. It includes database infrastructure, ingestion workflows, and operational tooling required to parse, store, and serve content.

## What This Contains

- Processing pipelines and workers that scan datasets, parse files, and index results.
- Database schema definitions and migrations for ClickHouse and Manticore — including the global telemetry tables (`processing_eta_samples`, `usage_events`, `api_events`) that feed the admin processing and metrics pages.
- Operational assets for running dependencies via Docker Compose (Temporal, ClickHouse, Manticore, MinIO, Tika, Redis, and monitoring UIs).
- Convenience scripts (`run.sh`, `start-docker.sh`, `reset-docker.sh`, `run-uv.sh`) for local orchestration, plus `verify-stack.sh` for end-to-end smoke checks against a live stack (migrations, ingestion, sharding invariants, website search).

## Subdirectories

- `docs/` - Architecture diagrams and system-level illustrations.
- `processing/` - Click-based CLI, workflow definitions, workers, and database clients.
- `ops/` - Docker compose configurations and environment-level operational notes.

## Navigation

-  [Go Back](../Readme.md)

- [docs/Readme.md](docs/Readme.md)
- [processing/Readme.md](processing/Readme.md)
- [ops/Readme.md](ops/Readme.md)