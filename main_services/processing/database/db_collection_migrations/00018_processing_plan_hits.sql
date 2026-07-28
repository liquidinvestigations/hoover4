CREATE TABLE IF NOT EXISTS processing_plan_hits
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the hit belongs to',
    item_hash String COMMENT 'Blob hash included in some plan',
    plan_hash String COMMENT 'The plan that contains this item'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, item_hash)
COMMENT 'Mapping of individual items to the plan that processed them.';
