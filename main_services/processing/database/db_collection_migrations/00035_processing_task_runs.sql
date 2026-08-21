-- One row per ACTIVITY EXECUTION, successful or not. The success side of
-- `processing_errors` (00015), which records only failures. Without both, the only
-- answer to "where does processing time go" is Temporal's own history, which is
-- retained for days and cannot be aggregated.
--
-- Written by the worker-side Temporal activity interceptor in
-- `tasks/task_timing.py`, batched a few hundred rows at a time. One row per *attempt*:
-- a Temporal retry is a second execution and gets a second row, which is what makes
-- "this task costs 40 minutes" include the time spent failing.
--
-- Relationship to `processing_errors`: an execution that raised appears HERE with
-- outcome = 'error' (so failures are inside the same aggregate, never a separate one),
-- and in `processing_errors` with the stack trace. The join key is
-- (collection_dataset, hash) plus a time window. The names differ on purpose in one
-- case: the workflows record detector failures under a descriptive
-- `detector_error_<name>` label, while this table always names the activity that
-- actually ran.
--
-- MEASUREMENT CAVEAT, so nobody reads more into these numbers than they carry: the
-- interceptor wraps the activity from the moment the worker accepts the task, which for
-- a sync activity includes the hand-off to the thread-pool executor. The worker sets
-- max_concurrent_activities equal to the pool size, so a task is only ever delivered
-- when a slot is free and that hand-off is microseconds -- but it is not zero, and it
-- is why this is called wall duration, not CPU time.
--
-- Sort key: (collection_dataset, task_name, started_at). The two aggregations this
-- table exists for are "group by task_name" (a sort-key prefix once a dataset is
-- picked) and "the last N seconds" (a range on the trailing column). A full ingest of
-- ~200k files produces single-digit millions of rows, which is a fraction of a second
-- to scan either way.
--
-- TTL 180 days: long enough that a release measurement is still there next quarter,
-- short enough that a machine left ingesting for a year does not accumulate forever.
CREATE TABLE IF NOT EXISTS processing_task_runs
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the execution belongs to, empty when the activity is not dataset-scoped',
    task_name LowCardinality(String) COMMENT 'Temporal activity type, e.g. run_tika_and_store. This is the unit the breakdown groups by',
    hash String COMMENT 'Artifact the execution worked on when one is identifiable (file/pdf/email/archive hash, else the plan hash), empty otherwise',
    outcome Enum8('ok' = 0, 'error' = 1) COMMENT 'Whether the activity body returned or raised. Raised executions still carry their run time',
    run_time_ms UInt32 COMMENT 'Wall duration of this execution in milliseconds',
    started_at DateTime64(3) COMMENT 'When the execution started, UTC, millisecond precision',
    attempt UInt16 COMMENT 'Temporal attempt number, 1 for the first try. Retries are separate rows',
    task_queue LowCardinality(String) COMMENT 'Queue the execution ran on, which is also which worker tier it consumed',
    worker_id LowCardinality(String) COMMENT 'host-pid of the worker process, so concurrency can be split per process'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(started_at)
ORDER BY (collection_dataset, task_name, started_at)
TTL toDateTime(started_at) + INTERVAL 180 DAY
COMMENT 'One row per Temporal activity execution with its wall duration and outcome. The durable record behind the admin time breakdown and the per-task performance report.';
