CREATE TABLE IF NOT EXISTS processing_errors
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links error back to the pipeline for this dataset',
    hash String COMMENT 'Hash of the artifact involved (file/email/pdf/etc.) when available',
    task_name String COMMENT 'Name of the pipeline task that failed',
    run_time_ms UInt32 COMMENT 'Task run time in milliseconds before failure',
    error_logs String COMMENT 'Error output and stack traces as string',
    timestamp DateTime COMMENT 'ISO timestamp when the error occurred'
)
ENGINE = MergeTree
ORDER BY (collection_dataset, hash, task_name, timestamp)
COMMENT 'Processing errors and diagnostics. Centralized error log for ingestion and processing tasks.';
