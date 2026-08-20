-- How many tasks are WAITING on each Temporal queue, sampled every few seconds.
-- processing_task_inflight is the other half of the same question: it counts
-- slots that are busy inside a worker process. A 1-slot indexing queue with a
-- 30-hour tail reads as "busy" there and as "N waiters, 1 poller" here.
--
-- Levels, not counters: a reader takes the newest row per task_queue inside a
-- short freshness window. Nothing is written while every queue's backlog is 0,
-- so "no fresh rows" means idle, not a gap. TTL 2 days, same as inflight.
CREATE TABLE IF NOT EXISTS processing_queue_backlog
(
    task_queue LowCardinality(String) COMMENT 'Temporal task queue name, e.g. processing-indexing-queue',
    sampled_at DateTime COMMENT 'When the sample was taken, UTC',
    backlog_count UInt32 COMMENT 'Approximate tasks waiting, from DescribeTaskQueue',
    backlog_age_ms UInt32 COMMENT 'Age of the oldest waiting task in milliseconds, 0 when the server does not report it',
    add_rate Float32 COMMENT 'Tasks added per second, 0 when the server does not report it',
    dispatch_rate Float32 COMMENT 'Tasks dispatched per second, 0 when the server does not report it',
    pollers UInt16 COMMENT 'How many activity pollers DescribeTaskQueue reported for this queue'
)
ENGINE = MergeTree
ORDER BY (sampled_at, task_queue)
TTL sampled_at + INTERVAL 2 DAY
COMMENT 'Sampled Temporal queue waiters. Level samples, not counters. Empty while every queue is idle.';
