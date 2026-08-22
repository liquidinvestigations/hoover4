# Database Access, Definitions, and Migrations

This directory centralizes database utilities and schema definitions used by the processing pipeline.

## Contents

- `db_global_migrations/` - SQL migrations for the global ClickHouse database, `Hoover4_Processing`.
- `db_collection_migrations/` - SQL migrations applied to every per-collection ClickHouse database, `Hoover4_Collection_<collectionname>`.
- `clickhouse.py` - ClickHouse client configuration and migration runner.
- `manticore.py` - Manticore index maintenance and search configuration utilities.
- `s3.py` - S3 client helpers and bucket naming for the Garage blob store.
- `chat_todos.py` - the agent's per-chat-session todo list: validation, storage, and the two
  questions that decide whether the agent gets nagged. A `cancelled` item needs a note, and a
  bare status flip is not a change - see the module docstring for why both matter.

## One Garage bucket per collection

`hoover4-c-<collectionname>` holds a collection's ingested blobs and everything derived
from them; `hoover4-system` holds what belongs to no collection, which today is chat
artifacts. `blobs.s3_path` stores the full `s3://<bucket>/<key>`, and every reader takes
the bucket from the path rather than from its own configuration — a reader that rebuilds
the bucket name fetches from wherever it happens to be pointed instead of from where the
object is.

Per-collection *stores* are not possible: Garage has one shared metadata database and
globally content-addressed data blocks. Buckets are, and they make a collection's objects
enumerable without prefix filtering and deletable in one call. Block dedup is global, so
the split costs no storage.

It also turns "`P0_scan_disk` must never walk derived material" from a prefix check
somebody has to remember into a structural property for the chat artifacts: they are in a
bucket no collection's walker looks at. The OCR'd PDFs still share a bucket with the blobs
they were built from, which is why `verify-stack.sh` still asserts that no `blobs` row
references `derived/`.

A collection's bucket is created with the collection and removed with it, which is why the
application's Garage key carries `--create-bucket`. `garage-init` bootstraps only the
system bucket.

**Both halves of a collection's storage are provisioned by one function**,
`s3.ensure_collection_storage`, and every path that can bring a collection into existence
— the admin activity, `create-collection`, `ensure-collection`, `add-disk-dataset` —
calls it. A path that creates only the database leaves a collection that ingests
correctly until the first writer that does not create buckets of its own reaches for it:
the scan stage makes the bucket before its first upload, so a corpus small enough to keep
every blob inline in ClickHouse never uploads, and the first thing to touch the bucket is
the searchable-PDF builder — which answers 500 and parks the plan behind an activity that
can never succeed.

## The two databases

ClickHouse storage is split across `1 + N` databases.

| | Database | Migrations | Holds |
|---|---|---|---|
| Global | `Hoover4_Processing` | `db_global_migrations/` | `users`, `user_groups`, `user_group_membership`, `collections`, `collection_group_permissions`, `web_sessions`, `server_settings`, `dataset`, `search_manticore_cache`, `temp_chat_json_objects`, `processing_eta_samples`, `processing_task_runs` (unroutable activity timings), `processing_queue_backlog`, `bench_runs` |
| Per collection | `Hoover4_Collection_<collectionname>` | `db_collection_migrations/` | blobs, VFS, parsed content, plans, errors, term dictionaries, NLP watermark, Manticore shard ledger |

`collectionname` is a slug matching `[a-z0-9_]{1,48}` that may not end in `_<digits>`
(collides with a Manticore shard name), may not end in `_pages`, `_meta` or `_vectors`
(reserved Manticore table suffixes) and may not be `processing`. `-` is not allowed:
Manticore table names (`<name>_<n>_pages`) are interpolated unquoted in both runtimes,
and a dashed identifier does not parse. The rule is enforced by
`clickhouse.py::validate_collectionname` and, independently, by `collectionname_valid` in
`website/backend/src/api/admin/collections.rs` - a database name cannot be bound as a SQL
parameter, so both runtimes must refuse a bad name on their own.

`dataset` deliberately stays global: it is the registry the website lists before it knows
any collection, and it is what resolves `collection_dataset -> collectionname`. Its
`collectionname` column is fixed when the dataset is created and never changes.

## Picking a client

```python
from database.clickhouse import (
    get_global_client,        # global tables
    get_collection_client,    # collection is known
    get_client_for_dataset,   # only a collection_dataset is known (resolves, then routes)
)
```

Never read a per-collection table through the global client or vice versa. The resolver
raises `UnknownDatasetError` for a dataset with no registry row rather than silently
falling back to the global database.

`get_*_client` keeps one ClickHouse client per `(thread, database)` for the process
lifetime. Nested `with` blocks on the same thread and database share that client;
the inner exit does not close it. The HTTP pool is sized above the worker's activity
slot count (common and tika are 8) so concurrent activities do not discard TCP
connections.

## Insert durability

`CLIENT_SETTINGS` waits for async inserts (`wait_for_async_insert=1`). An unmarked
`client.insert` / `insert_arrow` stays durable. Pipeline tables written inside a
re-runnable activity opt out through `insert_idempotent` / `insert_arrow_idempotent`
(`wait_for_async_insert=0`): a ClickHouse restart can lose the buffer, and the stage
re-runs until the anti-joins converge. Ledgers and watermarks go through
`insert_durable` / `insert_arrow_durable`, or through unmarked inserts which wait.

The line is drawn by what re-derives the row, not by how important it is. Every P3
parser output qualifies: the parser runs again and writes the same content-addressed
row. A P0 scan row does not — nothing rescans the disk, so a lost `blobs` row is a file
that is never planned and never noticed.

| Wait | Tables |
|---|---|
| Do not wait | every P3 parser output: `file_types`, `text_content`, `tika_metadata`, `emails`, `email_headers`, `email_addresses`, `archives`, `pdfs`, `pdf_metadata`, `pdfs_image`, `pdf_ocr_results`, `raw_ocr_results`, `image`, `image_metadata`, `audio_metadata`, `video_metadata`, `document_dates`, `table_documents`, `table_sheets`, `table_columns`, `table_cells`; plus `entity_hit`, `nlp_processed`, `processing_task_runs`, `ai_service_telemetry` |
| Wait | `blobs`, `blob_values`, `vfs_files`, `vfs_directories`, `processing_plan_finished`, `index_state`, `manticore_shards`, `manticore_shard_assignments`, `dataset`, `processing_plans`, `schema_versions` |

The wait is not a rounding error. One waited insert costs ~60 ms against ~1 ms without;
`parse_email_extract_text_headers` writes three rows per email, so leaving them durable
put ~180 ms of pure waiting into a ~540 ms activity that runs once per message.

## Migrations

Migrations are run by `main.py migrate`, which applies `db_global_migrations/` to
`Hoover4_Processing` and then `db_collection_migrations/` to every non-deleted collection.
`main.py ensure-collection <name>` applies the collection set to a single collection and
creates its database if missing; that is also what the admin UI triggers (via the
`EnsureCollectionDatabase` Temporal workflow) when a collection is created.

Bookkeeping is per database: `clickhouse-migrations` writes a `schema_versions` table
**inside each target database** recording `version`, `status` and the file's MD5. Two
consequences:

- **Never edit an applied migration.** The MD5 check turns any edit or renumbering into an
  `md5-mismatch` failure. A schema change means a *new* numbered file from here on.
- Collections created at different times converge on the same schema at the next
  `migrate` run, because each has its own independent `schema_versions`.

Both sets are **collapsed at a baseline**, then grow by new numbered files.
`COLLAPSED_BASELINE` in `tests/unit/test_migrations_parity.py` is `{global: 20,
collection: 31}` — files at or below those numbers are CREATE-only history and must
never be edited. Files above the baseline may `ALTER TABLE`.

Collapsing is a deliberate break of the never-edit-history rule and is paid for by a full
`./deploy --reset`: it drops all data and reindexes `testdata`. There is no migration path
from a pre-collapse database and none is wanted. Do not collapse again without that reset
being acceptable.

## Every Manticore write goes through `manticore_execute`, never a cursor

`cursor.execute(sql, params)` is not safe for a statement carrying corpus text, and no
amount of escaping makes it safe. The MySQL driver scans the **fully interpolated**
statement for a client-side `DELIMITER` command before sending it, and that scanner does
not understand the backslash escaping the same driver has just applied. A document
containing the word `delimiter` followed by whitespace and a quote — ordinary MediaWiki
markup and manual pages do this — is read as a delimiter change: the statement is either
refused outright (`the backslash (\) character is not a valid delimiter`) or re-split and
re-joined into something Manticore answers with `P01: syntax error`. One such page in a
batch fails the whole indexing activity, and every document in that batch is recorded as
failed, so a single file can hide dozens of healthy ones.

`manticore_execute(cnx, sql, params)` substitutes the parameters with the connection's own
escaping and sends the bytes with `cmd_query`, which has no splitter in front of it. The
statement template is split on `%s` rather than `%`-formatted, so a `%s` inside a document
is just text.

Two properties this depends on, both of which have to be handled and neither of which can
be assumed:

* **A quote is escaped with a backslash, never by doubling.** Manticore's parser rejects
  the SQL-standard `''`. That is the driver's behaviour and the reason the driver does the
  escaping here rather than any hand-written routine.
* **Which connection class `mysql.connector.connect` returns depends on import order.**
  The C-extension one exposes `prepare_for_mysql` and no `converter`; the pure-Python one
  is the other way round. The worker gets one and a script that imported the driver first
  gets the other, so `quote_manticore_values` handles both.

## Manticore infix indexing (`min_infix_len='3'`)

`pages_table_ddl` in `manticore.py` sets `min_infix_len='3'`, so `MATCH('doc*')` and
`MATCH('*ocument*')` work.

### Why, and what "before" actually looked like

Without it the star is dropped during tokenisation and the query silently becomes an exact
search for a truncated word. That is not "wildcards are unsupported"; it is a **wrong
answer that nobody notices**. Measured on the real `testdata` shard (156 pages, 26 MB):

| query | before | after |
|---|---|---|
| `document` | 16 | 16 |
| `docum*` | 0 | 19 |
| `*ocument*` | 0 | 42 |
| `doc*` | **7 — wrong, not zero** | 34 |
| `te*t` | **3 — wrong, not zero** | 28 |

The `filename_index` row is a pages row like any other, so a filename fragment
(`*report*` finding `annual_report_2024.pdf`) is infix-matched by the same setting — the
best fuzzy-match case in the schema.

### The value is a statement of intent, not a tuning knob

In this Manticore version `min_infix_len` is an **on/off switch, not a threshold**: 2, 3
and 4 are byte-for-byte identical in size *and* behaviour, and `do*` (2 characters) matches
even at 4. Pick 3 and move on.

`min_prefix_len` *is* a real threshold and is the wrong tool — it gives no infix matching
at all, and makes stars work only for prefixes longer than the minimum, which is worse than
either alternative.

### Storage cost: honestly, unmeasurable at this size

`SHOW TABLE ... STATUS` `disk_bytes` on an RT table depends on chunk-merge state. The same
no-infix configuration measured 16.6 MB, 33.6 MB and 65.4 MB at different points in one
session. Under identical treatment (pipeline reindex, then `FLUSH` + `OPTIMIZE`):

| configuration | disk_bytes | ram_bytes |
|---|---|---|
| no infix | 33,588,034 | 35,407,056 |
| `min_infix_len='3'` | 26,013,634 | 17,537,550 |

The infix build measured *smaller*, which is not a credible causal effect — read it as the
metric being noisy at this corpus size. A controlled probe (two tables, the same 156 pages,
same flush/optimise) put the difference at **+0.8%**. Re-measure on a real-sized collection
before treating infix indexing as a storage problem.

### Two traps

**`ALTER TABLE` does not reindex.** It changes metadata only:

```
ALTER TABLE testdata_1_pages min_infix_len='3'   -- succeeds
SHOW TABLE testdata_1_pages SETTINGS             -- reports min_infix_len = 3
SELECT COUNT(*) FROM testdata_1_pages WHERE MATCH('doc*')   -- still the old wrong 7
```

Existing data is not re-indexed. Everything looks configured and nothing has changed. A
settings change means a reindex, which drops and recreates the physical tables:

```bash
main_services/run.sh reindex-collection testdata
main_services/run.sh reindex-collection other
```

Stop indexing workers first, or make sure no `IndexDatasetPlan` is running for that
collection.

**The worker must be restarted after editing this file.** `hoover4-worker` is a
long-running process that imported `database.manticore` at startup; a reindex triggered
without restarting it recreates the tables from the *old* DDL, and `SHOW TABLE ... SETTINGS`
will show the setting missing with no other sign anything went wrong.

Always verify the **behaviour**, not just the settings:

```bash
docker exec hoover4-mcp-collections python -c "
from collection_search_server.backends import manticore_query as q
print(q('SHOW TABLE testdata_1_pages SETTINGS'))
for w in ['document','docum*','*ocument*','doc*','wat*']:
    print(w, q(\"SELECT COUNT(*) c FROM testdata_1_pages WHERE MATCH('\"+w+\"')\")[0]['c'])"
```

`docum*` and `*ocument*` must be non-zero, and `doc*` must be **larger** than the 7 it
returns without infix indexing, not equal to it.

## Migrations above the collapsed baseline

`COLLAPSED_BASELINE` is `{global: 20, collection: 31}`. Files at or below those numbers
are the collapsed baseline and must never be edited. Above them the collection set carries
appended tables and column-adding migrations; the global set does the same.

| | |
|---|---|
| `00024_eta_samples_ttl.sql` | Global. `processing_eta_samples` TTL is 3 days. `sampled_at` stays in the sort key so the admin page can plot the newest 100 samples per stage. |
| `00025_processing_task_runs.sql` | Global. Same columns as the collection table of this name. Activities whose parameters name no collection write here with an empty `collection_dataset`. |
| `00026_bench_runs.sql` | Global. One row per `bench-ingest.sh` run, sorted `(fixture, started_at)`. |
| `00027_task_runs_queue_wait.sql` | Global. Same queue-wait columns as collection `00047` on the unroutable `processing_task_runs` copy. |
| `00028_processing_queue_backlog.sql` | Global. Sampled Temporal queue waiters (`DescribeTaskQueue`): backlog count, age, add/dispatch rates, pollers. Level samples, nothing written while every queue is idle. TTL 2 days. Distinct from `processing_task_inflight`, which is busy slots inside a worker process. |
| `00032_email_addresses.sql` | Structured sender/recipient rows written by `parse_email`. |
| `00033_document_dates.sql` | Every confirmed historical date for a document, with the metadata key it came from. |
| `00034_vfs_nodes.sql` | The folder tree, one row per path node. |
| `00035_processing_task_runs.sql` | One row per Temporal activity execution: task, dataset, hash, wall duration, outcome, attempt, queue, worker. The success side of `processing_errors`, which only records failures. `MergeTree`, partitioned by month, sorted `(collection_dataset, task_name, started_at)`, TTL 180 days. |
| `00036_processing_task_inflight.sql` | Sampled concurrency: what each worker process is running right now. Level samples, not counters — read the newest per worker and sum those. TTL 2 days. |
| `00037_shard_row_budget.sql` | `row_count` on `manticore_shards` and `manticore_shard_assignments`: the shard planner caps a shard on Manticore rows as well as on text bytes. An `ALTER`, because both tables are in the collapsed baseline. |
| `00042_table_cells.sql` | One row per non-empty cell of a tabular document, keyed `(file_hash, sheet_id, column_id, row_id)` — column-major, because every operation the grid performs is scoped to one column. No `collection_dataset` column: one parse serves every dataset in the collection holding the same file. |
| `00043_table_documents.sql` | The per-`(collection_dataset, hash)` manifest for those cells: reader, format, counts, and the truncation record. The only thing that authorises a cell read. |
| `00044_table_sheets.sql` | Per-sheet extents. Every cell read is bounded by these, which is how a re-parse that produces fewer rows leaves the old tail unreachable rather than needing a mutation. |
| `00045_table_columns.sql` | Per-column header, inferred type, per-kind counts, value range and samples. Real columns rather than JSON, so "every document with a column called IBAN" is a SQL query. |
| `00046_text_content_bytes.sql` | `text_bytes` on `text_content`: byte length of `text`, written at insert so size queries never scan the body. |
| `00047_task_runs_queue_wait.sql` | Queue wait on `processing_task_runs`: `scheduled_at`, `schedule_to_start_ms`, `retry_backoff_ms`, plus `workflow_id` / `workflow_run_id` / `workflow_type`. Defaults keep older rows readable. |
| `00048_processing_errors_join.sql` | `attempt` and `workflow_run_id` on `processing_errors`, so an `outcome = error` row in `processing_task_runs` can join its stack trace without a hash+time window. |
| `00049_regex_entity_hit.sql` | One row per `(file, variant, segment, rule set, entity type)` holding the segment's deduplicated values in five parallel arrays. Not one row per occurrence: 193 real segments produced 325 365 entities, and density per segment is unbounded. `rule_set_version` is in the sort key so two rule sets' results coexist rather than replace one another. |
| `00050_regex_scanned.sql` | The scan stage's watermark, per rule set version. A bump makes every segment eligible again and nothing re-runs until a rescan is asked for. Segments the variant filter skipped are watermarked too, or they are reconsidered on every run for ever. |
| `00029_operations.sql` | Global. One row per long-running operation: kind, target, state, progress, ETA, error, who asked. No TTL — its whole value is answering "was this ever run" about something that happened longer ago than a Temporal history survives (24 hours here). `op_id` carries a timestamp and is also the workflow id, so two dispatches can never collapse into one execution. |

`processing_task_runs` and `processing_task_inflight` are written by `tasks/task_timing.py`
(a Temporal activity interceptor, batched, best-effort but never silent) and read by the
admin processing page and `main_services/task-time-report.sh`. Queue waiters are a third
table, global `processing_queue_backlog`, sampled from Temporal `DescribeTaskQueue` by
the same daemon. Volume, so nobody is surprised by it: a full ~200k-file ingest produces
single-digit millions of `processing_task_runs` rows (a handful of activities per file),
which is a fraction of a second to aggregate and a few tens of megabytes on disk. The
in-flight table is thousands of rows for the same run, and zero while nothing is being
processed. The backlog table is a handful of rows per sample while any queue has waiters,
and zero while every queue is idle.

Two baseline files carry edits made in place: `00005_vfs_files.sql` (`container_hash` in
the sort key, plus `mtime`/`mtime_source`) and `00008_email_headers.sql`
(`date_sent_known`). **Do not take that as licence to do it again.** Editing an applied
migration is normally impossible: the runner records an md5 per file and an edit fails
every deployment that already ran it. It was survivable only because the rollout was a
docker reset, which wipes the applied-migration table, and that excuse expires the moment
a deployment exists that must be upgraded rather than rebuilt. `COLLAPSED_BASELINE` was
deliberately not raised over those edits, so the next schema change is a new numbered file.

`vfs_files`'s sort key needs `container_hash` because two containers holding the same
inner path — two copies of one archive — otherwise collapse into a single
ReplacingMergeTree row and the second container loses its children. The P0 dedupe read
carries the same filter for the same reason.

**The readiness sentinel names whatever the LAST table-creating migration creates**,
because "ready" means the schema is fully built. It is currently `table_columns`
and must be updated in both copies (`db_collection_migrations/READINESS_SENTINEL` and
`website/backend/src/db_auth/READINESS_SENTINEL`) whenever a table-creating migration is
appended. `00034_vfs_nodes.sql` contains a comment claiming it must stay last; that
sentence is wrong and is **left alone on purpose**, because it is applied history whose md5
is recorded. The rule it states still holds — that is why the sentinel is not there.

## `table_cells` is keyed by hash, and that is why it needs a sweeper

`purge_dataset_from_clickhouse` enumerates `SHOW TABLES`, runs `DESCRIBE TABLE` on each,
and **skips every table with no `collection_dataset` column**. `table_cells` has none, on
purpose: cells are shared by every dataset in the collection that holds the same file, so
one workbook mailed to forty people is parsed once. A dataset purge therefore reaches
`table_documents`, `table_sheets` and `table_columns` and leaves the cells alone — which
is correct while another dataset still claims them, and a leak once none does.

`sweep_orphan_table_cells` closes that: it deletes the cells of every hash with no
`table_documents` row in `('ok', 'parsing')`, in bounded batches, and it **refuses to run
against an empty manifest** and logs the refusal. An authority table with no rows is a
symptom — an unapplied migration, a failed query — and never a licence to delete every
cell in the collection. `'parsing'` counts as a claim so a sweep cannot race an in-flight
parse, and a `parsing` row older than a day is tombstoned to `failed` by the same pass,
which is what releases a genuinely abandoned parse's cells on the next one.

Collection deletion needs none of this: `drop_collection_db` drops the whole database.

## Navigation

-  [Go Back](../Readme.md)
