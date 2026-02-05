CREATE TABLE IF NOT EXISTS processing_plan_finished
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the plan belongs to',
    plan_hash String COMMENT 'Plan hash that has finished executing',
    finished_at DateTime COMMENT 'UTC timestamp when processing finished'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, plan_hash)
COMMENT 'Plans that have completed processing to avoid reprocessing.';
