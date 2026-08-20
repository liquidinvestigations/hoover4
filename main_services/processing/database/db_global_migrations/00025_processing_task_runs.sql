-- Activities whose parameters name no collection (collect_eta_samples, temp-dir
-- helpers, chat writes) have no collection database to land in. Those rows go
-- here, with an empty collection_dataset, so they are still counted. Same columns
-- as the per-collection table of the same name: two tables, two databases.
CREATE TABLE IF NOT EXISTS processing_task_runs
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the execution belongs to, empty when the activity is not dataset-scoped',
    task_name LowCardinality(String) COMMENT 'Temporal activity type, e.g. collect_eta_samples',
    hash String COMMENT 'Artifact the execution worked on when one is identifiable, empty otherwise',
    outcome Enum8('ok' = 0, 'error' = 1) COMMENT 'Whether the activity body returned or raised. Raised executions still carry their run time',
    run_time_ms UInt32 COMMENT 'Wall duration of this execution in milliseconds',
    started_at DateTime64(3) COMMENT 'When the execution started, UTC, millisecond precision',
    attempt UInt16 COMMENT 'Temporal attempt number, 1 for the first try. Retries are separate rows',
    task_queue LowCardinality(String) COMMENT 'Queue the execution ran on, which is also which worker tier it consumed',
    worker_id LowCardinality(String) COMMENT 'host-pid of the worker process, so concurrency can be split per process'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (collection_dataset, task_name, started_at)
TTL toDateTime(started_at) + INTERVAL 180 DAY
COMMENT 'One row per Temporal activity execution that names no collection. Same shape as the per-collection table of this name';
