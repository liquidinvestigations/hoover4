ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS op_id String DEFAULT '';
ALTER TABLE processing_task_runs ADD COLUMN IF NOT EXISTS activity_id String DEFAULT '';
