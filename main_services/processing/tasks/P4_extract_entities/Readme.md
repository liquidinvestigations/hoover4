# P4 - Extract Entities (NLP/NER)

This stage runs named-entity recognition over the parsed text content of a plan,
*before* indexing. It was split out of the indexing stage so the remote NER
service (the slowest and least reliable link) gets its own task queue, retries
and worker, and so NER results are reusable when indexing is re-run.

## Key Responsibilities

- Read `text_content` for a plan's hashes, skipping segments already present in
  `nlp_processed` for the current `nlp_model` (left-anti join — the stage is
  cheaply re-runnable). The recorded `nlp_model` is the provider that **served
  each batch** (`NLP_MODEL_BY_PROVIDER`: `gpu → ner-gpu-xlmr`,
  `spacy → ner-spacy-xx`), not the configured one — under fallback the two
  differ, and that difference is the only evidence an outage happened.
- Call the remote NER service in batches of `NLP_BATCH_TEXTS = 64` texts per
  request, via `tasks.remote.post_json` over an ordered endpoint list
  (`NER_URL` primary, `NER_URL_FALLBACK` the `hoover4-ner-spacy` CPU twin).
  Calls use a `(connect, read)` timeout pair and a per-endpoint,
  time-boxed circuit breaker; a connect failure falls back, a read timeout
  does not (the host is alive — degrading would mask a server-side fault).
- Write `entity_hit` rows and populate the `ner` string-term dictionary. **Each
  entity row carries the `nlp_model` that served its text**, and `nlp_model` is
  part of `entity_hit`'s `ORDER BY`, so two providers' hits for the same
  `(file, variant, page, type)` coexist instead of one replacing the other.

## Two providers, and the two places they collide

Both providers run over every text variant, and both sets are kept — that is the
design, not an accident. It has two consequences that are invisible when broken:

1. **`entity_hit` must carry `nlp_model`.** With it empty, both providers land on
   the same key and whichever ran last is the only one with entities.
2. **P6 must UNION the two, not take the last one.** `union_entities_by_segment`
   in `P6_index_data/activities.py` does this and deduplicates — the providers
   agree on most entities, and the same term id twice in a Manticore MVA inflates
   every facet count that includes it.

The CPU twin maps spaCy's multilingual labels onto the GPU model's CoNLL-03
vocabulary (`GPE → LOC`, `PERSON → PER`). Without that the same entity arrives
under two different `entity_type` values depending on which provider served it,
and the union above renders them as two facets — which reads as duplicate data
rather than as one entity found twice.

**Fallback is verified, not assumed** (`plans/1-part-3.md` §5.1): stopping
`hoover4-ai-server` makes NER fail over to `ner-spacy-xx` in ~0.02 s, the breaker
opens for 60 s after three consecutive connect failures, and work returns to
`ner-gpu-xlmr` once the host is back.
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
- [P6 - Index Data](../P6_index_data/Readme.md)
