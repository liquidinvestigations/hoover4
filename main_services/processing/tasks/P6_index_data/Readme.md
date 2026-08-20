# P6 - Index Data

This stage indexes parsed text and metadata into Manticore to enable search and entity retrieval. It is P6, not P4 or P5: entity extraction (P4) and chunk embedding (P5) both run before it.

## Key Responsibilities

- Load plan item hashes and fetch text content for indexing.
- Read the `entity_hit` rows written by the P4 entity-extraction stage and map entity values to string-term ids (cache hits — P4 already populated the `ner` term dictionary; ids are content-derived via `hash_string_to_uint63`).
- Resolve each document's metadata — file types, MIME types, extensions, folder closure, dates, sizes, email addresses — and write it onto every one of the document's rows.

## Entry Points

- Workflow: `IndexDatasetPlan` in `workflows.py`
- Activities: `index_text_pages`, `index_vectors`, `build_vfs_nodes`, `index_vfs_structure`, `build_email_graph`, `optimize_shard_tables` in `activities.py`
- Helpers: `email_graph.py` (the pure edge rules), `document_metadata` (the per-document read half of the writer), `string_term_encodings.py`; `fetch_plan_hashes` and `clean_text` are shared and live in `tasks/plan_utils.py`

`build_vfs_nodes` and `resolve_canonical_file_type` run once per `ExecutePlans` batch,
before the per-plan `IndexDatasetPlan` children; `build_vfs_nodes` then
`index_vfs_structure` run once more after them. `IndexDatasetPlan` itself writes shards
and the email graph.

## Technical Details

A shard is ONE Manticore table, `<shard>_pages`, and the document's metadata is denormalized onto each of its rows. That is why `index_text_pages` writes both the text rows and the synthetic `filename_index` row: the result list reads the metadata off whichever row of a `GROUP BY file_hash` Manticore returns, so a row written with different values than its siblings is a document with a non-deterministic date and size. See [`../../database/Readme.md`](../../database/Readme.md) for why the alternative — a per-document table joined at query time — is both slower and wrong.

Rows are inserted grouped by `(collection_dataset, file_hash, page_id)`. The columnar engine picks a storage scheme per block, so a block whose rows all belong to one document stores one repeated value per metadata column; that ordering is the difference between paying ~15% for the duplication and paying several times over.

Every writer here sends its rows with `database.manticore.manticore_execute`, never through a MySQL cursor: the driver's cursor mangles a statement whose data contains the word `delimiter` followed by whitespace and a quote, which is ordinary MediaWiki text. See [`../../database/Readme.md`](../../database/Readme.md). One page like that fails the whole activity, and the workflow then records an error for every document in the batch — so a single file can present as dozens of unindexable ones.

Indexing batches items in fixed chunk sizes (`INDEX_ROW_CHUNK_SIZE = 512`) to limit transaction sizes. Entity MVAs (`ner_per/org/loc/misc`) are built from `entity_hit` and are per SEGMENT, not per document; if a segment has no `nlp_processed` watermark the stage logs a WARNING and indexes it with empty entity MVAs — a missing entity list must not block search. String term IDs are derived from deterministic hashes and stored in lookup tables for reuse.

`index_vfs_structure` copies ClickHouse `vfs_nodes` into `<coll>_vfs` with one multi-row
`REPLACE INTO … VALUES (…),(…),…` per 512-node chunk. Deterministic ids make REPLACE
idempotent, so there is no dataset-wide DELETE first. A reconciliation pass then deletes
Manticore rows whose `node_key` is not in the current ClickHouse tree, by id. During an
ingest the `_vfs` row count never falls to zero because of this activity.

That pass reads the indexed ids a keyset page at a time, with an explicit `LIMIT` and a
matching `OPTION max_matches`. A Manticore `SELECT` with no limit clause returns twenty
rows and any result set is capped at `max_matches` (default 1000), so an unbounded scan
would compare twenty arbitrary nodes against the tree and leave every other removed node
in the index.

`optimize_shard_tables` runs once at the end of the workflow, per shard the plan wrote to, and compacts a table whose `killed_rate` is over 20% or whose `disk_chunks` is over 12 (`OPTIMIZE TABLE … OPTION cutoff=1`, asynchronous). It is a **storage** win — a re-ingested corpus reclaimed 32–58% of its disk — and not a latency one: killed rows are cheap to skip at query time. It skips itself entirely while another plan of the same collection is still in flight, because a merge competing with a write batch for I/O turns seconds into minutes.

`build_email_graph` materialises the email connection graph into `email_identity`,
`email_edges` and `email_clusters`. It is the one activity here that is COLLECTION-scoped
rather than dataset-scoped, because its most common edge is `identity` — the same message
present in two custodians' mailboxes — and an edge builder that could only see one dataset
would never find one. The identity rows for the dataset that just finished are refreshed
first, then the whole collection's edges and clusters are rebuilt and swept.

Three of the four edge kinds come from an exact key (the message id, an RFC threading
header, `vfs_files.container_hash`) and record `confidence = 1.0`. The fourth is inferred
from an equal normalised subject plus a participant overlap and records `0.5`, because the
corpora this runs against carry `In-Reply-To` on well under 1% of their messages and a
graph built on threading headers alone would be empty. The inference is guarded three ways
— a subject-length floor, a cap on how many messages may share one normalised subject, and
a time window — and every guard is a module constant in `email_graph.py` with the number it
was chosen against. `build_email_graph` logs the edge count per kind and what each guard
dropped in one line, so a threshold change is visible in the worker log rather than in a
graph nobody can read.

`email_clusters` holds a row only for a message that has at least one edge, and the size it
records is the TRUE size of the component, never the reader's render budget.

## Usage

- Triggered by P2 after the P4 entity-extraction stage completes.
- Indexing activities run on `processing-indexing-queue`.

## Navigation

- [Go Back](../Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)

## The canonical file type

`resolve_canonical_file_type` runs once per `ExecutePlans` batch, after the VFS tree and
before the shard writers. It reads every detector's `file_types` row and every parser's
output, and writes one row per document to `file_type_canonical`: the winning MIME, the
winning coarse type, the rule that chose it, and every detection that lost.

The rank table is in `canonical_file_type.py`. The rule that matters is the first one: a
document is a docx because the docx parser read text out of it, not because a lookup
table says `.docx` is not a zip. An archive that produced no members at all is demoted
there too — an empty tar is text, and an email whose attachment extraction failed is an
email.

`document_metadata` reads this table rather than unioning `file_types`, which is what
makes the file-type facet single-valued per document. Nothing is lost: the losing
detections stay in `file_types` and on `file_type_canonical.losers`, both of which the
raw metadata tab shows.
