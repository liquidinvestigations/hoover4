# Database Access, Definitions, and Migrations

This directory centralizes database utilities and schema definitions used by the processing pipeline.

## Contents

- `db_global_migrations/` - SQL migrations for the global ClickHouse database, `Hoover4_Processing`.
- `db_collection_migrations/` - SQL migrations applied to every per-collection ClickHouse database, `Hoover4_Collection_<collectionname>`.
- `clickhouse.py` - ClickHouse client configuration and migration runner.
- `manticore.py` - Manticore index maintenance and search configuration utilities.
- `minio.py` - MinIO client helpers and bucket initialization.
- `milvus_example.py` - Example integration pattern for Milvus vector storage.

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

Both sets were collapsed and renumbered from `00001` when storage was split, so every
`ALTER` was folded into the `CREATE TABLE` it modified and neither directory contains an
`ALTER TABLE`. `tests/test_migrations_parity.py` asserts that, plus that no table is
declared in both directories.

## Navigation

-  [Go Back](../Readme.md)
