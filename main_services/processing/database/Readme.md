# Database Access, Definitions, and Migrations

This directory centralizes database utilities and schema definitions used by the processing pipeline.

## Contents

- `db_global_migrations/` - SQL migrations for the global ClickHouse database, `Hoover4_Processing`.
- `db_collection_migrations/` - SQL migrations applied to every per-collection ClickHouse database, `Hoover4_Collection_<collectionname>`.
- `clickhouse.py` - ClickHouse client configuration and migration runner.
- `manticore.py` - Manticore index maintenance and search configuration utilities.
- `minio.py` - MinIO client helpers and bucket initialization.

## The two databases

ClickHouse storage is split across `1 + N` databases.

| | Database | Migrations | Holds |
|---|---|---|---|
| Global | `Hoover4_Processing` | `db_global_migrations/` | `users`, `user_groups`, `user_group_membership`, `collections`, `collection_group_permissions`, `web_sessions`, `server_settings`, `dataset`, `search_manticore_cache`, `temp_chat_json_objects`, `processing_eta_samples`, `processing_task_runs` (unroutable activity timings) |
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

The last two are written by `tasks/task_timing.py` (a Temporal activity interceptor,
batched, best-effort but never silent) and read by the admin processing page and
`main_services/task-time-report.sh`. Volume, so nobody is surprised by it: a full ~200k-file
ingest produces single-digit millions of `processing_task_runs` rows (a handful of
activities per file), which is a fraction of a second to aggregate and a few tens of
megabytes on disk. The in-flight table is thousands of rows for the same run, and zero
while nothing is being processed.

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
