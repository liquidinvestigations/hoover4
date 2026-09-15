-- One row per Error event of an operation: an Error the operation wrote, or what the
-- operation decided about an Error that an earlier operation wrote.
--
-- event is one of error, selected, removed_stage_off, without_plan, recovered and
-- still_failing. A retried activity writes the same key again, and the
-- ReplacingMergeTree keeps the newest row. The sort key starts with op_id, so the rows
-- of one operation are a prefix read.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS operation_error_events
(
    op_id String COMMENT 'Operation this event belongs to',
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the Error',
    hash String COMMENT 'Document hash of the Error, empty for a dataset-level Error',
    task_name String COMMENT 'processing_errors.task_name of the Error',
    event LowCardinality(String) COMMENT 'error, selected, removed_stage_off, without_plan, recovered or still_failing',
    error_logs String DEFAULT '' COMMENT 'The first 2000 characters of the error text, only on an error event',
    created_at DateTime64(3) DEFAULT now64(3) COMMENT 'When the event was written, UTC'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (op_id, collection_dataset, hash, task_name, event)
TTL toDateTime(created_at) + INTERVAL 180 DAY
COMMENT 'Error events of each operation. The final counts stay on the operations row after these rows expire';
