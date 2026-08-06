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
| Global | `Hoover4_Processing` | `db_global_migrations/` | `users`, `user_groups`, `user_group_membership`, `collections`, `collection_group_permissions`, `web_sessions`, `server_settings`, `dataset`, `search_manticore_cache`, `temp_chat_json_objects` |
| Per collection | `Hoover4_Collection_<collectionname>` | `db_collection_migrations/` | blobs, VFS, parsed content, plans, errors, term dictionaries, NLP watermark, Manticore shard ledger |

`collectionname` is a slug matching `[a-z0-9_]{1,48}` that may not end in `_<digits>`
(collides with a Manticore shard name), may not end in `_pages` or `_meta` (reserved
Manticore table suffixes) and may not be `processing`. `-` is not allowed: Manticore
table names (`<name>_<n>_pages|_meta`) are interpolated unquoted in both runtimes, and
a dashed identifier does not parse. The rule is enforced by
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

Both sets were collapsed and renumbered from `00001` when storage was split, and
**re-collapsed again** in Part 2 Phase 0: every `ALTER` accumulated since is folded back
into the `CREATE TABLE` it modified, the Milvus create-then-drop trio is deleted outright,
and both directories are contiguous from `00001` with no `ALTER TABLE` and no `DROP TABLE`
anywhere. `COLLAPSED_BASELINE` in `tests/unit/test_migrations_parity.py` is now
`{global: 20, collection: 31}` — files at or below those numbers are the collapsed
baseline and must never be edited again.

The re-collapse was a deliberate, one-time break of the never-edit-history rule, paid for
by a full `./deploy --reset`: it drops all data, and `testdata` is reindexed. There is no
migration path from a pre-collapse database and none is wanted (D1/D2 of `plans/1-part-2.md`).

## Manticore infix indexing (`min_infix_len='3'`)

Both shard table DDLs in `manticore.py` — `pages_table_ddl` and `meta_table_ddl` — set
`min_infix_len='3'`, so `MATCH('doc*')` and `MATCH('*ocument*')` work.

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

`meta_table_ddl` gets it too. Its text fields are `filenames` and `metadata_values`, and a
filename fragment (`*report*` finding `annual_report_2024.pdf`) is the best fuzzy-match
case in the schema. That table is ~0.25% the size of the pages table — 168 KB against
65 MB on `testdata` — so the same percentage cost is close to free in absolute terms.

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

## Navigation

-  [Go Back](../Readme.md)
