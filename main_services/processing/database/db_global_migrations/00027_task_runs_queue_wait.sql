-- Same queue-wait columns as the per-collection processing_task_runs table.
-- Unroutable activities (collect_eta_samples, temp-dir helpers, chat writes)
-- land here, so they must carry the same shape.
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS scheduled_at DateTime64(3) DEFAULT toDateTime64(0, 3);
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS schedule_to_start_ms UInt32 DEFAULT 0;
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS retry_backoff_ms UInt32 DEFAULT 0;
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_id String DEFAULT '';
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_run_id String DEFAULT '';
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_type LowCardinality(String) DEFAULT '';
