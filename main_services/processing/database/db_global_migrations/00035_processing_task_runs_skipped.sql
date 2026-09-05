-- Adds `skipped` to `outcome` as ordinal 2, matching the per-collection table that
-- `db_collection_migrations/00051_processing_task_runs_skipped.sql` changes. The two
-- copies of this column hold the same values written by the same code: an activity that
-- carries no collection is recorded here instead of beside its collection, so a value
-- this column does not name would be lost at insert time rather than refused loudly.
-- Appending keeps every row written before this migration readable, because an Enum8's
-- existing names keep their ordinals.
ALTER TABLE processing_task_runs MODIFY COLUMN outcome Enum8('ok' = 0, 'error' = 1, 'skipped' = 2) COMMENT 'Whether the activity body returned data, raised, or decided the input needs nothing. A skip still ran to completion and consumed no retry';
