-- Long-running admin-dispatched jobs per dataset. The admin form polls state.
--
-- A form that disables itself while a job runs must be able to see the job, or it locks
-- forever. This row is that visibility, and it is also the lock: a second dispatch for
-- the same (dataset, kind) is refused server-side while a running row exists. Two admins
-- in two browsers are not stopped by a disabled button.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS dataset_jobs
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the job runs against',
    job_id             String   COMMENT 'Temporal workflow id',
    kind               LowCardinality(String) COMMENT 'change_ocr_languages | ...',
    state              LowCardinality(String) COMMENT 'running | done | failed',
    detail             String   DEFAULT ''    COMMENT 'JSON: what changed, progress counters',
    error              String   DEFAULT '',
    started_at         DateTime,
    finished_at        DateTime DEFAULT toDateTime(0),
    updated_at         DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree. Also the staleness clock: a running row that has not advanced is a stuck job',
    is_deleted         UInt8 DEFAULT 0
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, kind, job_id)
COMMENT 'Long-running admin-dispatched jobs per dataset. The admin form polls state.';
