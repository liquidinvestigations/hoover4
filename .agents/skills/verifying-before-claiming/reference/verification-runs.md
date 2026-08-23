# Reading a stack verification run

`main_services/verify-stack.sh` drives a real ingestion through the deployed stack and
asserts on the result. It runs for tens of minutes and it runs **inside** the worker
container.

## Running it without losing it

- Start it backgrounded with its full output redirected to a file, and grep the file. A tail
  of the last lines hides the phase that actually failed.
- **Any deploy recreates the worker and kills the run** with a signal exit. Check whether a
  run is in flight before deploying, and batch pending fixes so one restart serves several.
- A partial run is evidence for the phases it completed and evidence for **nothing** after
  them. Say which phase you reached.

## The phases, in order

1. Wait for the datastores, the worker and the workflow service to answer.
2. Ensure the fixture corpus is present.
3. Run the migrations.
4. Ensure the collections under test are registered.
5. Ingest the canonical datasets and poll until every plan finishes, with a per-collection
   timeout.
6. Assert the invariants below.
7. Exercise the site.

## What it asserts

- **The global database holds only global tables**, and no per-collection table has leaked
  into it.
- **Every collection database carries the full collection table set**, parsed from the
  migrations rather than written down, and no collection data sits in the global database or
  the reverse.
- **The shard ledger matches what the search engine actually holds**, in both directions.
- **No shard exceeds either of its budgets**, except a shard holding a single document, which
  legitimately can.
- **Every `(collection_dataset, file_hash)` pair lives in exactly one shard**, and the
  committed index-state rows match the real row counts. Document identity is the *pair*: the
  same content in two datasets of one collection is indexed twice, on purpose.
- **The website answers**, and a search through its HTTP interface returns hits for a word
  known to be in the fixtures. The interface's URL carries a build hash, so the run discovers
  it from the served bundle rather than assuming a layout, and it checks the *content* it got
  back, because the site serves its shell for any unrecognised path and therefore answers 200
  for everything.
- **A configuration fingerprint agrees between hosts** where a second tier is enabled,
  because the configuration file is copied by hand and will drift.
- **Nothing derived is reachable as source.** No blob row may reference the derived prefix.
  That prefix is where OCR output and captured chat artefacts live; if the disk-scan stage
  ever walked it, each derived object would be ingested, re-derived, and produce another
  one without end. A blob row pointing into it is the signature of that loop having started.

## Away from the fixture corpus

The run assumes the datasets it ingests. On a host whose fixtures sit at a different depth,
the ingest-root overrides are mandatory; without them the run fails by naming a dataset that
does not exist, which reads as a broken stack and is not.
