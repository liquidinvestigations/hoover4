# Hoover4 Main Services

This directory contains the core data plane for Hoover4. It includes database infrastructure, ingestion workflows, and operational tooling required to parse, store, and serve content.

## This directory contains the main services.

- Processing pipelines and workers that scan datasets, parse files, and index results.
- Database schema definitions and migrations for ClickHouse and Manticore, including the global telemetry tables (`processing_eta_samples`, `usage_events`, `api_events`) that feed the admin processing and metrics pages.
- Operational assets for running dependencies via Docker Compose (Temporal, ClickHouse, Manticore, Garage, Tika, Redis, and monitoring UIs).
- Convenience scripts ([run.sh](run.sh), [start-docker.sh](start-docker.sh), [reset-docker.sh](reset-docker.sh), [run-uv.sh](run-uv.sh), [restart-worker.sh](restart-worker.sh)) for local orchestration: [restart-worker.sh](restart-worker.sh) is how the worker is restarted by hand, because a direct `docker restart` both refuses under a rootless runtime and kills through the graceful drain after ten seconds (the docker ones are thin aliases for `./deploy` at the repo root) plus [verify-stack.sh](verify-stack.sh) for end-to-end smoke checks against a live stack (migrations, ingestion, sharding invariants, website search). Its invariants run against **every** registered collection, read from `Hoover4_Processing.collections` rather than a hardcoded `testdata other`. A leftover collection that no check iterated is exactly how the Manticore/ledger equality check stopped noticing things. Its `--restart-resilience` flag runs a different check instead: one fixture ingest interrupted by a worker stop/start, asserting that every document still ends up with chunks, vectors and an index row. It is not on the per-deploy path. See [docs/quality-assurance/Running_Checks.md](../docs/quality-assurance/Running_Checks.md).
- [task-time-report.sh](task-time-report.sh), where processing time went, out of `processing_task_runs`: per-task-type totals, shares, counts, mean/p50/p95/p99/max, per-queue and per-dataset splits, the twenty slowest single executions, the headline trio of summed task time, wall clock and achieved parallelism, plus the per-activity overhead floor, per-file wall-vs-busy, and dataset-scoped P6 repeats. `--csv` for a spreadsheet, `--since '<UTC timestamp>'` to scope it to one ingest, `--dataset NAME` to restrict to one `collection_dataset`. Read-only, and it ingests nothing.
- [bench-ingest.sh](bench-ingest.sh), repeatable ingest of a named fixture (`smoke` / `medium` / `large`) into collection `bench`. Purges first, waits for quiescence, asserts correctness, writes `Hoover4_Processing.bench_runs`, then purges again unless `--keep`.
- [bench-overhead.py](bench-overhead.py), per-probe p50/mean/min/max for ClickHouse client/insert, Magika, extractous and `file`, including the pooled-client and helper-pool paths. Runs inside `hoover4-worker`: `docker exec -i hoover4-worker uv run python - < main_services/bench-overhead.py`.
- [verify-reruns.sh](verify-reruns.sh) tests Error selection and recovery against the local stack. It removes its test collection and Failure trees before each run. It writes a browser operation id under `website/test_reports/`.
- [test-verify-stack-tables.sh](test-verify-stack-tables.sh) checks the final table set after migration rename statements.

## Subdirectories

- [agents/](agents) - the six MCP tool servers and the two research agents. They run here, not in `ai_services`, because they read ClickHouse and Manticore directly.
- [docs/](docs) - Architecture diagrams and system-level illustrations.
- [processing/](processing) - Click-based CLI, workflow definitions, workers, and database clients.
- [ops/](ops) - Docker compose configurations and environment-level operational notes.
- [ocr_tesseract/](ocr_tesseract) - Tesseract OCR over HTTP (`hoover4-tesseract-cpu`).
- [ocr_pdf/](ocr_pdf) - searchable-PDF assembly over HTTP (`hoover4-ocr-pdf`). Renders a PDF's
  pages, sends each to the OCR tier above, and writes back a PDF with an invisible text
  layer. It owns no engine and no language data. See its Readme for the derived-prefix
  guard that keeps the ingest walker from re-ingesting what it writes.
- [ner_spacy/](ner_spacy) - spaCy NER over HTTP (`hoover4-ner-spacy`). Enable it with `[main_services] ner_spacy_enabled` when the selected NER configuration requires it.
  Verify model output against the intended corpus before selecting a provider.

### CPU services run with the main services.

Tesseract OCR and spaCy NER run independently of the optional GPU tier.
Their model and language data are packaged in their images.
[The remote client](processing/tasks/remote.py) applies bounded timeouts and caller-supplied endpoint selection.
The NER caller can supply an enabled spaCy fallback after its GPU endpoint.
OCR callers keep separate endpoints and source identities for each engine.
An unconfigured OCR engine produces no variant.
[AI architecture](../docs/architecture/AI_Services.md) describes disabled capabilities and fallback conditions.

## Navigation

-  [Go Back](../Readme.md)

- [ocr_pdf/Readme.md](ocr_pdf/Readme.md)
- [ocr_tesseract/Readme.md](ocr_tesseract/Readme.md)
- [docs/Readme.md](docs/Readme.md)
- [processing/Readme.md](processing/Readme.md)
- [ops/Readme.md](ops/Readme.md)
