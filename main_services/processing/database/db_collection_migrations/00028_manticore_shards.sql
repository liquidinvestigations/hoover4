CREATE TABLE IF NOT EXISTS manticore_shards
(
    shard_name LowCardinality(String) COMMENT 'Manticore logical shard, e.g. testdata_1',
    shard_index UInt32 COMMENT 'Numeric suffix, 1-based',
    text_bytes UInt64 COMMENT 'Total text bytes written into this shard so far',
    doc_count UInt64 COMMENT 'Distinct file_hash count written into this shard',
    is_open UInt8 DEFAULT 1 COMMENT '1 = accepting new documents, 0 = sealed (over budget)',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (shard_name)
COMMENT 'Shard ledger for this collection. Drives the <=1GB-per-shard indexing planner.';
