-- A shard is capped on ROWS as well as on text bytes. Bytes per row vary by two orders
-- of magnitude across a mixed corpus (an email is ~1.5 kB, a document ~57 kB), while
-- facet and group-by cost tracks rows, so a byte-only budget produces shards whose query
-- cost differs by a factor of 35. These two columns are what the planner packs against,
-- and both are recomputed from index_state after every batch.
ALTER TABLE manticore_shards ADD COLUMN IF NOT EXISTS row_count UInt64 DEFAULT 0 COMMENT 'Manticore rows written into this shard so far';

ALTER TABLE manticore_shard_assignments ADD COLUMN IF NOT EXISTS row_count UInt64 DEFAULT 0 COMMENT 'Manticore rows contributed by this document: its text segments plus its filename row';
