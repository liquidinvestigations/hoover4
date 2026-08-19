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
- Send only the variants worth reading (below) and drop the values that are
  debris rather than entities (`tasks/entity_stoplist.py`).
- Call the remote NER service in batches of `NLP_BATCH_TEXTS = 64` texts per
  request, via `tasks.remote.post_json` over an ordered endpoint list
  (`NER_URL` primary, `NER_URL_FALLBACK` the `hoover4-ner-spacy` CPU twin, which is
  rendered only when `[main_services] ner_spacy_enabled = true` — off by default,
  because spaCy's accuracy on real corpora is poor and its noise makes the entity
  facets unusable. With it off there is no fallback and an unreachable GPU fails
  fast naming the url, which is the intent).
  Calls use a `(connect, read)` timeout pair and a per-endpoint,
  time-boxed circuit breaker; a connect failure falls back, a read timeout
  does not (the host is alive — degrading would mask a server-side fault).
- Write `entity_hit` rows and populate the `ner` string-term dictionary. **Each
  entity row carries the `nlp_model` that served its text**, and `nlp_model` is
  part of `entity_hit`'s `ORDER BY`, so two providers' hits for the same
  `(file, variant, page, type)` coexist instead of one replacing the other.

## What the model is allowed to read, and what it is allowed to return

A model labels whatever it is handed, so both of these are correctness questions about
the Entities facet rather than tuning.

**Which variant.** `text_sources.ner_reads_variant` drops a stored variant that is a
worse copy of another variant of the same document. Today that is exactly one case: a
mail file has both `raw_text` (its MIME envelope — header block, boundaries, base64
payloads) and `email_parser` (the body alone), and running the model over the envelope
makes every header name an entity on every message in the corpus. The predicate is
structural — a file HAS a parsed body or it does not — so mail whose only body part is
HTML produces no `email_parser` rows and keeps its `raw_text` entities instead of
silently losing all of them.

Skipped segments still get an `nlp_processed` watermark, carrying the **configured**
model (no service saw them to claim it). Without it the stage would re-read them every
run, P6 would warn `no nlp_processed watermark` for each one, and the stage's progress
bar would never reach its own segment count.

Deliberately *not* used here: `text_quality.non_linguistic_reason`, which P5 applies to
chunks. Its unit is a chunk; this stage's unit is a whole page or a 256 KB segment, and
one mostly-base64 page whose remaining fifth is prose would lose that prose's entities
entirely — the failure mode this stage exists to avoid.

**Which values.** `tasks/entity_stoplist.py` rejects what cannot be an entity: mail and
MIME header names (`X-` extension headers by shape, so no corpus's private ones need
enumerating), day and month names, SMTP/MIME protocol words, quoted-printable soft-break
fragments (`of=`), long case-shuffled base64 runs, single latin characters, four or more
single-character tokens (letter-spaced PDF headings such as `F O N T Y S`), and anything
long enough to be a paragraph. Every rule matches the **whole** value, which is what
makes dropping `May` safe while `May Chen` stays.

`Mr`, `Inc`, `NA` and `Rights Reserved` are deliberately kept. A list that guesses at
what is uninteresting removes real names; one that removes only what cannot be an entity
does not. The same line is drawn inside the reply-block rule, which drops the header
keyword a mail client prints under a name (`Eric Cc`, `Larry Sent`): `Date` and `To` are
ordinary English words as well as headers, so they count only with the header's colon
still attached (`Sara Shackleton To:`) and `Blind Date` stays searchable.

The website applies the same rules again when it renders entities
(`website/common/src/entity_stoplist.rs`), because rows written before a rule existed
keep their values until this stage is re-run over the collection. The two copies cannot
share a file — the two test suites run in containers that mount different trees — so each
hashes its own rule data and canonical cases into `STOPLIST_PARITY_DIGEST` and asserts the
same literal, which makes a one-sided change fail a test rather than drift.

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

**Fallback is verified, not assumed.** Stopping
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
