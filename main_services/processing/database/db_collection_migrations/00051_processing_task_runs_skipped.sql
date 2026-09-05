-- Adds `skipped` to `outcome` as ordinal 2, after `ok` = 0 and `error` = 1. An
-- activity body can decide an input needs no work (an image too small to hold text,
-- a CSV with too few cells to be a table) and still return normally, which the
-- existing two values could not tell apart from real output: both looked like `ok`.
-- Appending the new value keeps every row written before this migration readable,
-- because an Enum8's existing names keep their ordinals.
ALTER TABLE processing_task_runs MODIFY COLUMN outcome Enum8('ok' = 0, 'error' = 1, 'skipped' = 2) COMMENT 'Whether the activity body returned data, raised, or decided the input needs nothing. A skip still ran to completion and consumed no retry';
