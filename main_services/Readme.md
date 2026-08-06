# Hoover4 Main Services

This directory contains the core data plane for Hoover4. It includes database infrastructure, ingestion workflows, and operational tooling required to parse, store, and serve content.

## What This Contains

- Processing pipelines and workers that scan datasets, parse files, and index results.
- Database schema definitions and migrations for ClickHouse and Manticore — including the global telemetry tables (`processing_eta_samples`, `usage_events`, `api_events`) that feed the admin processing and metrics pages.
- Operational assets for running dependencies via Docker Compose (Temporal, ClickHouse, Manticore, MinIO, Tika, Redis, and monitoring UIs).
- Convenience scripts (`run.sh`, `start-docker.sh`, `reset-docker.sh`, `run-uv.sh`) for local orchestration — the docker ones are thin aliases for `./deploy` at the repo root — plus `verify-stack.sh` for end-to-end smoke checks against a live stack (migrations, ingestion, sharding invariants, website search).

## Subdirectories

- `agents/` - the six MCP tool servers and the two research agents (moved out of `ai_services` in plan 1 part 1).
- `docs/` - Architecture diagrams and system-level illustrations.
- `processing/` - Click-based CLI, workflow definitions, workers, and database clients.
- `ops/` - Docker compose configurations and environment-level operational notes.
- `ocr_tesseract/` - Tesseract OCR over HTTP (`hoover4-tesseract-cpu`).
- `ner_spacy/` - spaCy NER over HTTP (`hoover4-ner-spacy`).

### Why the CPU twins live here and not in `ai_services`

Both services above are the CPU half of a capability whose other half runs on the
optional GPU tier, and they speak the **same HTTP contract** as their GPU counterparts
so `processing/tasks/remote.py` falls back between them without branching at the call
site. They are on the main side deliberately: a twin that shares a host with the thing
it is a twin of is not a twin. Their model and language data is baked into the image for
the same reason — one that needs the internet to come up is not a fallback either.

The fallback is not symmetric across capabilities. NER degrades GPU → CPU and records
which provider served each row. OCR does **not** fall back between engines, because the
engine is part of the storage key (`ocr_easyocr_en` vs `ocr_tesseract_eng`): serving one
engine's request from the other would file its text under a name that did not produce
it. An unconfigured OCR engine simply produces no variant.

## Navigation

-  [Go Back](../Readme.md)

- [docs/Readme.md](docs/Readme.md)
- [processing/Readme.md](processing/Readme.md)
- [ops/Readme.md](ops/Readme.md)