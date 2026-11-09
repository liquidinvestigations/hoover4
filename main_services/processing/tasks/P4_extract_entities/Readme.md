# P4 - Extract Entities

Two extractors read the parsed text content of a plan, *before* indexing: a
named-entity model, and the regex entity scanner. They are separate stages sharing a
directory because they ask the same question of the same rows and write to disjoint
tables, neither waits on the other, and `ExecuteSinglePlan` runs both concurrently.

NER was split out of the indexing stage so the remote NER service (the slowest and least
reliable link) gets its own task queue, retries and worker, and so NER results are
reusable when indexing is re-run.

There is no P4b or P4.5. The stage numbers are a stored contract: `STAGE_INDEX` is a
value in `processing_eta_samples` and is mirrored in the website, so a new number
between P4 and P5 would move a number that existing rows already hold.

## Key Responsibilities

- Read `text_content` for a plan's hashes, skipping only current `nlp_processed` rows with matching provider, stage version, source version, and source digest. The recorded `nlp_model` is the provider that **served
  each batch** (`NLP_MODEL_BY_PROVIDER`: `gpu → ner-gpu-xlmr`).
  Earlier rows can hold `ner-spacy-xx`, and readers keep that identity.
- Send only the eligible source variants described below and drop the values that are
  debris rather than entities ([tasks/entity_stoplist.py](../entity_stoplist.py)).
- Call the remote NER service in batches of `NLP_BATCH_TEXTS = 32` texts per
  request (and `NLP_BATCH_CHARS = 250_000` characters), via `tasks.remote.post_json` over the GPU endpoint
  (`NER_URL`).
  NER has no CPU path, so an unreachable GPU tier fails fast and names the url.
  Calls use a `(connect, read)` timeout pair and a per-endpoint,
  time-boxed circuit breaker. The call has one endpoint, so a connect failure or a
  read timeout fails the activity and Temporal retries it.
- Save results after each `NER_SAVE_BYTES = 8 MB` of text. A retry skips the saved pages, so a plan that outlasts the 30-minute activity timeout still advances.
- Write `entity_hit` rows and populate the `ner` string-term dictionary. **Each
  entity row carries the `nlp_model` that served its text**, and `nlp_model` is
  part of `entity_hit`'s `ORDER BY`, so two providers' hits for the same
  `(file, variant, page, type)` coexist instead of one replacing the other.

## Entity extraction uses a bounded input and output contract.

A model labels whatever it is handed, so both of these are correctness questions about
the Entities facet rather than tuning.

**Which variant.** `text_sources.ner_reads_variant` drops a stored variant that is a
worse copy of another variant of the same document. A mail file can have `raw_text`
(its MIME envelope), `email_parser` (the selected body), and converted HTML or RTF
alternatives. When the selected body exists, the model reads that source. It skips the
envelope and body alternatives for entity work. The alternatives remain stored and
selectable in the viewer. When no readable body exists, the model can read `raw_text`.

Skipped segments still get an `nlp_processed` watermark, carrying the **configured**
model (no service saw them to claim it). Without it the stage would re-read them every
run, P6 would warn `no nlp_processed watermark` for each one, and the stage's progress
bar would never reach its own segment count.

Deliberately *not* used here: `text_quality.non_linguistic_reason`, which P5 applies to
chunks. Its unit is a chunk; this stage's unit is a whole page or a 256 KB segment, and
one mostly-base64 page whose remaining fifth is prose would lose that prose's entities
entirely. The failure mode this stage exists to avoid.

**Which values.** [tasks/entity_stoplist.py](../entity_stoplist.py) rejects what cannot be an entity: mail and
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
([website/common/src/entity_stoplist.rs](../../../../website/common/src/entity_stoplist.rs)), because rows written before a rule existed
keep their values until this stage is re-run over the collection. The two copies cannot
share a file (the two test suites run in containers that mount different trees), so each
hashes its own rule data and canonical cases into `STOPLIST_PARITY_DIGEST` and asserts the
same literal, which makes a one-sided change fail a test rather than drift.

## Stored hits of several providers

New hits come from the GPU model only. Earlier rows of another provider can remain in storage,
and their hits retain provider identity. The storage and indexing contracts require these properties:

1. **`entity_hit` must carry `nlp_model`.** With it empty, both providers land on
   the same key and whichever ran last is the only one with entities.
2. **P6 must UNION the two, not take the last one.** `union_entities_by_segment`
   in [P6_index_data/activities.py](../P6_index_data/activities.py) does this and deduplicates. The providers
   agree on most entities, and the same term id twice in a Manticore MVA inflates
   every facet count that includes it.

Read timeouts and busy responses retain their separate retry behavior.
[The remote client](../remote.py) defines the connection and circuit-breaker conditions.
- Write `nlp_processed` watermark rows, including `text_bytes`. The byte
  length of the cleaned source text (`len(clean_text(text).encode('utf-8'))`).
  The Manticore shard planner (part 6) sizes shards from this column.

## Regex entity scanning

[scan_regex_entities.py](scan_regex_entities.py) sends the same segments to `hoover4-regex-entity-scanner` and
writes `regex_entity_hit` plus the `regex_scanned` watermark. It reads the same variants
NER does (`text_sources.ner_reads_variant`), applies the same `clean_text`, and
watermarks the segments it skipped for the same reason.

Everything else about it is different from NER, and the differences are the design:

- **No stop-list.** Values are checksummed and normalised; `entity_stoplist` exists to
  drop what a *model* mislabels, and against an IBAN that passed its check digits it
  would only do damage. This is also why the facet term fields are `regex_*` and never
  `ner`: the website applies the stop-list to whatever maps to the `ner` field.
- **No fallback twin.** The service is CPU-only already, so there is nothing to fall back
  to and nothing to prefer. A 503 from it is admission control, which
  `tasks.remote.post_json` raises as retryable. The answer to a full scan queue is to
  come back, never to scan somewhere else.
- **The rule set version is part of the key.** It is read from `/health` once per
  activity and every batch response is checked against it: an image swapped mid-activity
  would otherwise file the new rules' values under the old version's watermark, and
  nothing downstream would ever reconsider them. Two rule sets' rows coexist in
  `regex_entity_hit`, so a version bump makes every segment eligible for a rescan without
  destroying what the previous version found.
- **Batches are bounded by characters** (`REGEX_BATCH_CHARS = 1_000_000`,
  `REGEX_BATCH_TEXTS = 64`), an order of magnitude above NER's, because the scanner holds
  188 MB at full load with no per-request growth and runs at about 0.85 MB/s per thread.
  A megabyte is roughly a second of one thread's work rather than a queue-blocking unit.

**An entity on the boundary of two PDF rows is lost.** Unpaged segments overlap by about
256 bytes, so a value on their cut appears whole in one segment, and a repeated value can
appear in both. PDF rows have no overlap, so a value across two PDF parts is seen by neither.

The derived facets (the money magnitude ladder, the day snap, the date plausibility window)
are **not** here. They live in [tasks/regex_entities.py](../regex_entities.py), which the indexing stage imports
too: changing any of them means a rescan and a reindex together, and a rule that lives in
one stage is a rule the other can drift away from.

## Entry Points

- Workflow: `ExtractEntitiesForPlan` in [workflows.py](workflows.py) (runs on the common queue,
  like all workflows).
- Workflow: `ScanRegexEntitiesForPlan` in [workflows.py](workflows.py), a sibling of it rather than a
  successor.
- Activity: `scan_regex_entities_for_hashes` in [scan_regex_entities.py](scan_regex_entities.py), on
  `processing-common-queue`, not on a queue of its own: the CPU work is in another
  container and this activity only moves rows.
- Activity: `extract_entities_for_hashes` in [activities.py](activities.py), runs on
  `processing-nlp-queue` with a dedicated worker (`main.py worker nlp`,
  concurrency 2; concurrency here pipelines HTTP to the remote service, not
  local CPU).
- NER client: [extract_ner_from_text.py](extract_ner_from_text.py).

## Failure Policy

When `NER_URL` is empty, the activity returns zero counts before it opens ClickHouse. This
skip applies when `[ai_services] ner_enabled` or `ai_server_enabled` is false, or when the GPU tier is off.

NER errors are **not** swallowed. The activity fails and Temporal retries it
(`maximum_attempts=3`, 30 min `start_to_close_timeout`); after retries are
exhausted the workflow records one `processing_errors` row per affected hash.
An operation-owned successful chunk records one document outcome per member hash.
A document with no entities is a visible failure, never a silently empty result.

## Usage

- Triggered by P2 (`ExecuteSinglePlan`) after parsing/cleanup and strictly
  before `IndexDatasetPlan`.

## Navigation

- [Go Back](../Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
- [P6 - Index Data](../P6_index_data/Readme.md)

## Busy responses

NER and scanner activities preserve busy state in heartbeat details.
A busy response uses `Retry-After` within 5 to 120 seconds and preserves ordinary failure tries.
The busy budget is half the activity timeout, measured from its first busy response across attempts.
The activity reports `ServiceStayedBusy` when that budget ends.
Ordinary failures stop after five tries. Cancellation still propagates.
P6 can shorten encoded runs after the source text measurement.

## Signal scans

The regex activity also calls signal_batch with spans enabled for pages without a current signal watermark.
It reads and cleans each text once for both scanner routes.
Signal and regex versions remain independent.
A signal-only rescan preserves current regex rows and watermarks.
The activity verifies response versions, result counts, and the spans_served value.
A failed response writes no signal watermark.
It writes signal_hit with waited inserts before it writes signal_scanned.
Both tables retain source byte offsets and the cleaned text digest.
A completed empty scan supersedes earlier hits.
Readers use the newest completed watermark to select its signal version and scan version.

Run `uv run main.py scan-signals-collection <collectionname>` to scan the collection's finished plans.
The command uses the existing Temporal scan workflow and waits for each plan.
Run reindex-collection after the scan to apply current calibration.
Failed-file retry clears signal rows, watermarks, and clusters with regex state.

## Historical entity replacement

Entity stage version 2 selects earlier successful completion through the `entities` processing update.
GPU responses must report coverage version 2 and the exact input count.
The CPU provider retains its separate model identity and complete-input usage contract.
A disabled provider selects no work. Enabling it changes the desired fingerprint and selects missing output.

Inference completes before existing provider groups are replaced.
Replacement preserves other providers, datasets, and unchanged variants.
Current source versions and digests prevent changed text from satisfying completion.
The update changes only NER search attributes and searchable terms after inference.
It preserves indexed text, other search attributes, signals, regex output, and embeddings.
Missing index publication keeps the update selected after model inference completes.
Current stored completion and searchable output are verified before settlement.
