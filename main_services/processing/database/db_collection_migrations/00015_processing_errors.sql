-- Join key from processing_task_runs (outcome = error) onto this stack-trace
-- table. attempt is the Temporal activity attempt when the caller has it, else 0.
-- workflow_run_id is the parent workflow run. Missing values stay at the default
-- so a writer that does not know them still succeeds.
CREATE TABLE IF NOT EXISTS processing_errors
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links error back to the pipeline for this dataset',
    hash String COMMENT 'Hash of the artifact involved (file/email/pdf/etc.) when available',
    task_name String COMMENT 'Name of the pipeline task that failed',
    run_time_ms UInt32 COMMENT 'Task run time in milliseconds before failure',
    error_logs String COMMENT 'Error output and stack traces as string',
    timestamp DateTime COMMENT 'ISO timestamp when the error occurred',
    attempt UInt16 DEFAULT 0 COMMENT 'Temporal activity attempt number, 0 when unavailable',
    workflow_run_id String DEFAULT '' COMMENT 'Parent Temporal workflow run ID, empty when unavailable',
    op_id String DEFAULT '' COMMENT 'Operation that wrote this row, empty when no operation did'
)
ENGINE = MergeTree
ORDER BY (collection_dataset, hash, task_name, timestamp)
COMMENT 'Processing errors and diagnostics. Centralized error log for ingestion and processing tasks.';
