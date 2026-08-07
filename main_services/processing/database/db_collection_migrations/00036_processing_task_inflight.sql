-- Periodic samples of what each worker process is running RIGHT NOW, so the admin
-- processing page can answer "what is it chewing on" while an ingest is in flight.
--
-- Why this is a second table rather than a derivation of `processing_task_runs`. That
-- table gets its row when an execution FINISHES, so a task that has been running for
-- twenty minutes -- exactly the one worth looking at -- is invisible in it until it is
-- over. The only channel between a worker process and the website is ClickHouse, so
-- "currently running" has to be sampled and written.
--
-- Volume is deliberately tiny: `tasks/task_timing.py` writes one row per
-- (dataset, task_name) that has at least one execution in flight, per worker process,
-- every few seconds -- and NOTHING at all when the process is idle. A busy ingest is a
-- few rows per second across the whole worker fleet. Idle costs zero rows, which is
-- also what makes "no recent samples" a reliable reading of "nothing is running".
--
-- Readers must take the newest sample per (worker_id, task_name) inside a short
-- freshness window and sum those, never sum the raw rows: every sample is a level, not
-- an increment, so summing a minute of them multiplies concurrency by the sample count.
--
-- TTL 2 days: this is a live view. Anything older than the current run is answered by
-- `processing_task_runs`, which keeps its rows for 180 days.
CREATE TABLE IF NOT EXISTS processing_task_inflight
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the running executions belong to',
    task_name LowCardinality(String) COMMENT 'Temporal activity type that is running',
    worker_id LowCardinality(String) COMMENT 'host-pid of the sampling worker process. Part of the dedup key when reading',
    sampled_at DateTime COMMENT 'When the sample was taken, UTC',
    in_flight UInt16 COMMENT 'How many executions of this task type were running in this process at that moment',
    oldest_age_ms UInt32 COMMENT 'Age of the longest-running of them, so a stuck task is visible before it finishes'
)
ENGINE = MergeTree
ORDER BY (sampled_at, collection_dataset, task_name)
TTL sampled_at + INTERVAL 2 DAY
COMMENT 'Sampled concurrency: how many executions of each task type each worker process had in flight. Level samples, not counters. This is also the readiness sentinel (see READINESS_SENTINEL) and must stay the last table-creating migration.';
