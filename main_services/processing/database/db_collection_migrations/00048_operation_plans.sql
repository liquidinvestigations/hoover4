-- One row per plan an operation ran. source is listed for a plan that ExecutePlans listed
-- as pending, and backfill for a plan a collection backfill ran. A continuation listing
-- that repeats a plan writes the same key again.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS operation_plans
(
    op_id String COMMENT 'Operation that ran the plan',
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the plan',
    plan_hash String COMMENT 'processing_plans.plan_hash',
    source LowCardinality(String) COMMENT 'listed or backfill',
    listed_at DateTime64(3) DEFAULT now64(3) COMMENT 'When the operation took the plan, UTC'
)
ENGINE = ReplacingMergeTree(listed_at)
ORDER BY (op_id, collection_dataset, plan_hash)
TTL toDateTime(listed_at) + INTERVAL 180 DAY
COMMENT 'Plans each operation ran. Run progress counts these rows against processing_plan_finished';
