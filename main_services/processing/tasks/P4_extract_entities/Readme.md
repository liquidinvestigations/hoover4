# P4 - Extract Entities (NLP/NER)

This stage runs named-entity recognition over the parsed text content of a plan,
*before* indexing. It was split out of the indexing stage so the remote NER
service (the slowest and least reliable link) gets its own task queue, retries
and worker, and so NER results are reusable when indexing is re-run.

## Key Responsibilities

- Read `text_content` for a plan's hashes, skipping segments already present in
  `nlp_processed` for the current `nlp_model` (left-anti join — the stage is
  cheaply re-runnable).
- Call the remote NER service (`NER_URL`) in batches of `NLP_BATCH_TEXTS = 64`
  texts per request.
- Write `entity_hit` rows and populate the `ner` string-term dictionary.
- Write `nlp_processed` watermark rows, including `text_bytes` — the byte
  length of the cleaned text actually indexed (`len(clean_text(text).encode('utf-8'))`).
  The Manticore shard planner (part 6) sizes shards from this column.

## Entry Points

- Workflow: `ExtractEntitiesForPlan` in `workflows.py` (runs on the common queue,
  like all workflows).
- Activity: `extract_entities_for_hashes` in `activities.py` — runs on
  `processing-nlp-queue` with a dedicated worker (`main.py worker nlp`,
  concurrency 2; concurrency here pipelines HTTP to the remote service, not
  local CPU).
- NER client: `extract_ner_from_text.py`.

## Failure Policy

NER errors are **not** swallowed. The activity fails and Temporal retries it
(`maximum_attempts=3`, 30 min `start_to_close_timeout`); after retries are
exhausted the workflow records one `processing_errors` row per affected hash.
A document with no entities is a visible failure, never a silently empty result.

## Usage

- Triggered by P2 (`ExecuteSinglePlan`) after parsing/cleanup and strictly
  before `IndexDatasetPlan`.

## Navigation

- [Go Back](../Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
- [P5 - Index Data](../P5_index_data/Readme.md)
