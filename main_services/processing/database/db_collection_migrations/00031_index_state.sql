-- The backfill from manticore_shard_assignments that used to live here is gone with the
-- re-collapse: it existed for collections indexed before this table did, and after the
-- collapse there is no such collection -- every database is built from this file set in
-- one pass. This used to be the readiness sentinel, which moved to `vfs_nodes` in
-- 00034 when plan 3 appended three tables above the collapsed baseline. The rule is
-- unchanged: the sentinel names whatever the LAST table-creating migration creates,
-- because "collection is ready" means the schema is fully built.
--
-- These lines are ABOVE the statement, not below it. The migration runner splits the
-- file on the statement separator without parsing SQL, so a comment after the last one
-- is its own fragment -- comments only, no statement -- and ClickHouse answers
-- `Code: 62, Empty query`, naming neither the file nor the comment.
CREATE TABLE IF NOT EXISTS index_state
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset within this collection',
    file_hash String COMMENT 'Document hash',
    shard_name LowCardinality(String) COMMENT 'Shard the document was actually written to',
    indexed_at DateTime DEFAULT now() COMMENT 'When the writers committed this document',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash)
COMMENT 'Which docs have been written to which shard and when. Written only after the indexing writers committed, unlike manticore_shard_assignments which is the reservation. The shard ledger fill levels are recomputed from this table.';
