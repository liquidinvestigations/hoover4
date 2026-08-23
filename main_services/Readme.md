# Hoover4 Main Services

This directory contains the core data plane for Hoover4. It includes database infrastructure, ingestion workflows, and operational tooling required to parse, store, and serve content.

## What This Contains

- Processing pipelines and workers that scan datasets, parse files, and index results.
- Database schema definitions and migrations for ClickHouse and Manticore, including the global telemetry tables (`processing_eta_samples`, `usage_events`, `api_events`) that feed the admin processing and metrics pages.
- Operational assets for running dependencies via Docker Compose (Temporal, ClickHouse, Manticore, Garage, Tika, Redis, and monitoring UIs).
- Convenience scripts (`run.sh`, `start-docker.sh`, `reset-docker.sh`, `run-uv.sh`, `restart-worker.sh`) for local orchestration: `restart-worker.sh` is how the worker is restarted by hand, because a direct `docker restart` both refuses under a rootless runtime and kills through the graceful drain after ten seconds (the docker ones are thin aliases for `./deploy` at the repo root) plus `verify-stack.sh` for end-to-end smoke checks against a live stack (migrations, ingestion, sharding invariants, website search). Its invariants run against **every** registered collection, read from `Hoover4_Processing.collections` rather than a hardcoded `testdata other`. A leftover collection that no check iterated is exactly how the Manticore/ledger equality check stopped noticing things. Its `--restart-resilience` flag runs a different check instead: one fixture ingest interrupted by a worker stop/start, asserting that every document still ends up with chunks, vectors and an index row. It is not on the per-deploy path. See `docs/development/Running_Checks.md`.
- `task-time-report.sh`, where processing time went, out of `processing_task_runs`: per-task-type totals, shares, counts, mean/p50/p95/p99/max, per-queue and per-dataset splits, the twenty slowest single executions, the headline trio of summed task time, wall clock and achieved parallelism, plus the per-activity overhead floor, per-file wall-vs-busy, and dataset-scoped P6 repeats. `--csv` for a spreadsheet, `--since '<UTC timestamp>'` to scope it to one ingest, `--dataset NAME` to restrict to one `collection_dataset`. Read-only, and it ingests nothing.
- `bench-ingest.sh`, repeatable ingest of a named fixture (`smoke` / `medium` / `large`) into collection `bench`. Purges first, waits for quiescence, asserts correctness, writes `Hoover4_Processing.bench_runs`, then purges again unless `--keep`.
- `bench-overhead.py`, per-probe p50/mean/min/max for ClickHouse client/insert, Magika, extractous and `file`, including the pooled-client and helper-pool paths. Runs inside `hoover4-worker`: `docker exec -i hoover4-worker uv run python - < main_services/bench-overhead.py`.

## Subdirectories

- `agents/` - the six MCP tool servers and the two research agents. They run here, not in `ai_services`, because they read ClickHouse and Manticore directly.
- `docs/` - Architecture diagrams and system-level illustrations.
- `processing/` - Click-based CLI, workflow definitions, workers, and database clients.
- `ops/` - Docker compose configurations and environment-level operational notes.
- `ocr_tesseract/` - Tesseract OCR over HTTP (`hoover4-tesseract-cpu`).
- `ocr_pdf/` - searchable-PDF assembly over HTTP (`hoover4-ocr-pdf`). Renders a PDF's
  pages, sends each to the OCR tier above, and writes back a PDF with an invisible text
  layer. It owns no engine and no language data. See its Readme for the derived-prefix
  guard that keeps the ingest walker from re-ingesting what it writes.
- `ner_spacy/` - spaCy NER over HTTP (`hoover4-ner-spacy`). Off unless
  `[main_services] ner_spacy_enabled` is true: its accuracy on real corpora is poor
  and its output noisy enough that the entity facets become unusable.

### Why the CPU twins live here and not in `ai_services`

Both services above are the CPU half of a capability whose other half runs on the
optional GPU tier, and they speak the **same HTTP contract** as their GPU counterparts
so `processing/tasks/remote.py` falls back between them without branching at the call
site. They are on the main side deliberately: a twin that shares a host with the thing
it is a twin of is not a twin. Their model and language data is baked into the image for
the same reason, one that needs the internet to come up is not a fallback either.

The fallback is not symmetric across capabilities. NER degrades GPU → CPU and records
which provider served each row. OCR does **not** fall back between engines, because the
engine is part of the storage key (`ocr_easyocr_en` vs `ocr_tesseract_eng`): serving one
engine's request from the other would file its text under a name that did not produce
it. An unconfigured OCR engine simply produces no variant.

## Navigation

-  [Go Back](../Readme.md)

- [ocr_pdf/Readme.md](ocr_pdf/Readme.md)
- [ocr_tesseract/Readme.md](ocr_tesseract/Readme.md)
- [docs/Readme.md](docs/Readme.md)
- [processing/Readme.md](processing/Readme.md)
- [ops/Readme.md](ops/Readme.md)