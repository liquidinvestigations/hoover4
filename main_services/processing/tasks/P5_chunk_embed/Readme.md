# P5 - Chunk + Embed

This stage chunks every text segment of a plan and embeds every chunk, writing the
**durable** vector store. It runs after P4 and before P6: P6's vector indexer copies
the `text_chunk_vectors` rows written here into the Manticore `_vectors` shards (the
disposable, RAM-resident HNSW copy). Chunking and embedding run **per text variant** —
a file with native text plus two OCR variants is three chunk sets and three vector
sets. That is the accepted cost of complete attribution, and the largest GPU line item
of the AI stack.

## Key Responsibilities

- Read `text_content` **with `FINAL`** for a plan's hashes and chunk each segment with
  `chunking.chunk_page_text`: word-boundary chunks of at most `CHUNK_MAX_BYTES = 1200`
  bytes with ~`CHUNK_OVERLAP_BYTES = 200` overlap, addressed by **byte offsets into
  the UTF-8 encoding** (never character offsets — Python slices by character and
  ClickHouse counts bytes, and mixing them corrupts multibyte text silently).
  Chunking is deterministic, which is what makes the re-run key below correct. `FINAL`
  is load-bearing: `text_content` is a `ReplacingMergeTree`, a re-parse leaves two rows
  for the same segment until a merge collapses them, and the two copies chunk to
  *identical* keys — so neither is excluded by the anti-join and the page is embedded
  twice at full GPU cost.
- Hold back chunks that are not language (`tasks/text_quality.py`): base64 attachment
  bodies, XPM colour tables, XBM byte dumps. Extraction is greedy on purpose, so it
  produces these; embedding them buys a vector that then wins searches it has no business
  winning, because noise is close to everything. Counted as
  `chunks_skipped_non_linguistic`, never silently. `text_content` still holds every byte.
- Embed with the e5 prefix from `embedding_prefix.embedding_input` — the ONE function
  that owns the convention, keyed off the **probed** serving model id
  (`server_settings.embeddings_serving_model`, written by `main.py
  probe-embeddings`), never the ini. The search-side half of the same convention lives
  in `agent_common/embeddings.py`; the two are duplicated deliberately and must agree.
- Skip chunks already present in `text_chunk_vectors` for the serving model (left-anti
  join on `(collection_dataset, file_hash, extracted_by, page_id, chunk_index,
  embedding_model)`), so the stage is resumable and cheaply re-runnable.
- Write `text_chunks` (model-independent) before the first vector of their page, then
  `text_chunk_vectors` with the model and dims the endpoint **actually** served.

## Loud refusals (non-retryable)

- `embeddings_serving_model`/`_dim` missing from `server_settings` → run
  `main.py probe-embeddings`. The embed and indexing workers run that probe at their own
  startup, and `./deploy --ai-services` re-runs it, so this is only reachable when the
  endpoint was down at both moments. Never make the refusal permanent: it must stay
  recoverable without a human remembering a command nothing points them at.
- The endpoint serves a different model id or dimension than the probe recorded → the
  probe is stale; proceeding would write vectors under a convention the search side
  does not share, and the anti-join would never match them (re-embedding forever).
- `EMBEDDINGS_URL` empty (`embeddings_provider = none`) is NOT an error: the stage is
  a logged no-op.

## Entry Points

- Workflow: `ChunkEmbedForPlan` in `workflows.py` (common queue, like all workflows).
- Activity: `chunk_embed_for_hashes` in `activities.py` — runs on
  `processing-embed-queue` with a dedicated worker (`main.py worker embed`,
  concurrency 2; concurrency pipelines HTTP to the GPU tier, not local CPU).
- Triggered by P2 (`ExecuteSinglePlan`) after `ExtractEntitiesForPlan` and strictly
  before `IndexDatasetPlan`; `main.py backfill-vectors <collection>` runs it for
  already-finished plans.

## Failure Policy

Same as P4: errors are not swallowed — the activity fails, Temporal retries
(`maximum_attempts=3`), and an exhausted chunk becomes one `processing_errors` row per
hash. A document with no vectors is a visible failure, never a silently empty result.

## Navigation

- [Go Back](../Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)
- [P6 - Index Data](../P6_index_data/Readme.md)

## A hash is a file, and a file is not a unit of work

`chunk_embed_for_hashes` pages its input: it reads `text_content` `SEGMENT_PAGE_ROWS`
segments at a time, keyset-paginated on `(file_hash, extracted_by, page_id)`, and runs
the whole chunk/anti-join/embed/write pipeline per page.

The paging is not an optimisation. `ChunkEmbedForPlan` batches by hash count, and a hash
is one file: a single large text document expands to millions of chunks, and holding all
of them -- the rows, the chunk dicts, the anti-join key set and the insert rows are four
separate copies -- takes the worker container past its memory limit. The kernel then
kills a process inside the cgroup, which need not even be the one that allocated;
Temporal loses the activity, notices only at the heartbeat deadline, and the retry
repeats it. Caller-side batching cannot prevent this, because one hash is indivisible
there.

The already-embedded lookup is scoped to the page's keys for the same reason: scoping it
by `file_hash` would pull a whole multi-million-chunk file's vector keys back into
memory and undo the paging.

Progress survives a kill either way -- vectors are inserted per embed batch and the
anti-join skips what is already stored -- but "survives" is not "finishes", and before
paging a large enough file never finished.
