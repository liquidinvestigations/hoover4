-- The real start of an operation. started_at stays the dispatch time and stays in the
-- sort key. Epoch 0 means the operation has not started.
ALTER TABLE operations ADD COLUMN IF NOT EXISTS run_started_at DateTime DEFAULT toDateTime(0) AFTER started_at;

-- Rows that started before this column existed started at dispatch.
ALTER TABLE operations UPDATE run_started_at = started_at WHERE run_started_at = toDateTime(0) AND state NOT IN ('pending', 'queued') SETTINGS mutations_sync = 2;
