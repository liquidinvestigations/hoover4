CREATE TABLE IF NOT EXISTS processing_plans
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the plan belongs to',
    plan_hash String COMMENT 'SHA1 of JSON(sorted list of item hashes))',
    item_hashes Array(String) COMMENT 'List of blob hashes included in the plan',
    plan_size_bytes UInt64 COMMENT 'Total size of all blobs in the plan',
    created_at DateTime COMMENT 'Creation time (UTC)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, plan_hash)
COMMENT 'Batches of new blobs to process grouped into plans.';
