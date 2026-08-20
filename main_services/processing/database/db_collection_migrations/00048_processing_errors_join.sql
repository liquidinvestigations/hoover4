-- Join key from processing_task_runs (outcome = error) onto this stack-trace
-- table. attempt is the Temporal activity attempt when the caller has it, else 0.
-- workflow_run_id is the parent workflow run. Missing values stay at the default
-- so a writer that does not know them still succeeds.
ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS attempt UInt16 DEFAULT 0;
ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS workflow_run_id String DEFAULT '';
