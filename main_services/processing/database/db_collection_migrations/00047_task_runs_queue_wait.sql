-- Queue wait on each activity execution. processing_task_runs already records
-- start-to-close wall time, which is the 6% the worker spent running the body.
-- These columns are the other 94%: how long the task sat eligible on its queue
-- before a worker accepted it, and which workflow that wait belonged to.
--
-- scheduled_at is Temporal's scheduled_time, UTC, naive like started_at.
-- schedule_to_start_ms is started_time minus scheduled_time (0 if either is missing).
-- retry_backoff_ms is current_attempt_scheduled_time minus scheduled_time.
-- workflow_id / workflow_run_id / workflow_type come off activity.info().
-- Defaults keep rows written before this migration readable.
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS scheduled_at DateTime64(3) DEFAULT toDateTime64(0, 3);
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS schedule_to_start_ms UInt32 DEFAULT 0;
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS retry_backoff_ms UInt32 DEFAULT 0;
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_id String DEFAULT '';
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_run_id String DEFAULT '';
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS workflow_type LowCardinality(String) DEFAULT '';
