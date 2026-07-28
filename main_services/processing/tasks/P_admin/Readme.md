# P_admin - Collection database lifecycle

Administrative workflows that create and drop the per-collection ClickHouse databases
(`Hoover4_Collection_<collectionname>`). Not a pipeline stage: these run on demand, from
the admin UI or the CLI, rather than as part of ingestion.

## Key Responsibilities

- Provision a collection database (create if missing, then apply `db_collection_migrations/`).
- Drop a collection database when the collection is deleted.

The website backend never owns migration SQL; it triggers these workflows so the schema has
exactly one source of truth in Python.

## Entry Points

- Workflows: `EnsureCollectionDatabase`, `DropCollectionDatabase` in `workflows.py`
- Activities: `ensure_collection_database`, `drop_collection_database` in `activities.py`
- Queue: `processing-common-queue`
- CLI: `main.py ensure-collection <collectionname>`
- Website: `api/admin/temporal_trigger.rs` kinds `ensure_collection` / `drop_collection_database`

## Technical Details

`ensure_collection_database` is idempotent - `clickhouse-migrations` keeps a `schema_versions`
table inside each database, so collections created at different times converge to the same
schema on the next run. `drop_collection_database` issues `DROP DATABASE IF EXISTS` and is
irreversible; `admin_delete_collection` gates it on the collection having no datasets and on
a typed confirmation in the UI.

## Navigation

- [Go Back](../Readme.md)
