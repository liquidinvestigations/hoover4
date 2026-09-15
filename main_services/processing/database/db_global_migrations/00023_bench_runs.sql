-- One row per ingest-benchmark run. Tiny, kept for years so successive runs of
-- the same fixture are a prefix scan on (fixture, started_at).
CREATE TABLE IF NOT EXISTS bench_runs
(
    label LowCardinality(String) COMMENT 'Tag written by the harness, default git sha',
    fixture LowCardinality(String) COMMENT 'smoke, medium, large, or a custom path slug',
    started_at DateTime64(3) COMMENT 'Wall-clock start of the ingest, UTC',
    wall_clock_ms UInt64 COMMENT 'Quiescence end minus start, milliseconds',
    summed_task_ms UInt64 COMMENT 'Sum of processing_task_runs.run_time_ms for the dataset',
    achieved_parallelism Float64 COMMENT 'summed_task_ms divided by wall_clock_ms',
    files UInt32 COMMENT 'vfs_files row count after ingest',
    plans UInt32 COMMENT 'uniqExact(plan_hash) in processing_plans',
    overhead_floor_p50_ms UInt32 COMMENT 'p50 of detect_mime_from_name run_time_ms',
    per_file_busy_ms UInt32 COMMENT 'Mean per-hash sum of P3 run_time_ms',
    per_file_wall_ms UInt32 COMMENT 'Mean per-hash span from first P3 start to last P3 end',
    p6_vfs_runs UInt32 COMMENT 'count of index_vfs_structure for the dataset',
    errors UInt32 COMMENT 'processing_errors rows for the dataset',
    git_sha LowCardinality(String) COMMENT 'git rev-parse --short HEAD at run start'
)
ENGINE = MergeTree
ORDER BY (fixture, started_at)
COMMENT 'One row per bench-ingest.sh run, comparable without copying numbers by hand';
