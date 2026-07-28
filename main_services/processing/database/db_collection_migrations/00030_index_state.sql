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

-- Backfill for collections indexed before this table existed: assignments are the
-- best available approximation of what was indexed (correct on any stack whose
-- writers all succeeded). A stack with permanently failed writer chunks should run
-- `main.py reindex-collection <name>` instead of trusting the backfill.
INSERT INTO index_state (collection_dataset, file_hash, shard_name, indexed_at)
SELECT collection_dataset, file_hash, shard_name, indexed_at
FROM manticore_shard_assignments FINAL
WHERE (collection_dataset, file_hash) NOT IN (SELECT collection_dataset, file_hash FROM index_state FINAL);
