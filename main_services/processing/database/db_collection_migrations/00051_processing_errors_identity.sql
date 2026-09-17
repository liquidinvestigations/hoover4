CREATE TABLE IF NOT EXISTS processing_errors_next
(
    collection_dataset LowCardinality(String),
    hash String,
    task_name String,
    run_time_ms UInt32,
    error_logs String,
    timestamp DateTime,
    attempt UInt16 DEFAULT 0,
    workflow_run_id String DEFAULT '',
    op_id String DEFAULT '',
    error_identity String,
    write_version UInt64
)
ENGINE = ReplacingMergeTree(write_version)
ORDER BY (collection_dataset, error_identity);

INSERT INTO processing_errors_next
SELECT collection_dataset, hash, task_name, run_time_ms, error_logs,
       timestamp, attempt, workflow_run_id, op_id,
       concat('legacy-', toString(generateUUIDv4())), toUInt64(0)
FROM processing_errors;

RENAME TABLE processing_errors TO processing_errors_legacy,
             processing_errors_next TO processing_errors;

DROP TABLE processing_errors_legacy;

CREATE TABLE IF NOT EXISTS processing_errors_identity_ready
(
    version UInt8
)
ENGINE = TinyLog;
