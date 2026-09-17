CREATE TABLE IF NOT EXISTS processing_document_outcomes
(
    op_id String,
    collection_dataset LowCardinality(String),
    hash String,
    error_task_name LowCardinality(String),
    activity_name LowCardinality(String),
    workflow_run_id String,
    activity_id String,
    attempt UInt16,
    outcome Enum8('ok' = 0, 'skipped' = 2),
    recorded_at DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (op_id, collection_dataset, error_task_name, hash, workflow_run_id, activity_id, attempt)
TTL toDateTime(recorded_at) + INTERVAL 180 DAY;
