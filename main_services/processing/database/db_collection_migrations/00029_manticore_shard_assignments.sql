CREATE TABLE IF NOT EXISTS manticore_shard_assignments
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset within this collection',
    file_hash String COMMENT 'Document hash',
    shard_name LowCardinality(String) COMMENT 'Shard the document was written to',
    text_bytes UInt64 COMMENT 'Text bytes contributed by this document',
    indexed_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash)
COMMENT 'Document to shard mapping. A re-indexed document must go back to the same shard.';
