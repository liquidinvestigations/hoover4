-- Processing updates: the state that brings stored results of existing datasets up to date.
--
-- An update step is one entry of tasks/P_admin/updates/registry.py. Its scope is a dataset
-- (`scope_id` is `collection_dataset`) or a collection (`scope_id` is `collectionname`).
-- A desired fingerprint names what a step should produce now: its version, the versions
-- of the stages that it runs, the settings it depends on, and for some steps the input
-- revision of the dataset. Three tables keep three facts apart, and each has one kind of
-- writer, so no writer can overwrite a field of another.
--
-- `stage_versions` records each stage version the code has run. The worker inserts the
-- missing pairs at start. `baseline = 1` marks the first version of a stage that the
-- table holds. Errors of a baseline version get no automatic retry, because no earlier
-- version of that stage existed to change them.
CREATE TABLE IF NOT EXISTS stage_versions
(
    stage LowCardinality(String) COMMENT 'Canonical stage identity, tasks/stage_versions.py',
    version UInt32 COMMENT 'Stage output version',
    baseline UInt8 COMMENT '1 when no earlier version of the stage was recorded',
    first_seen_at DateTime64(6) COMMENT 'When a worker first recorded the pair, UTC'
)
ENGINE = ReplacingMergeTree(first_seen_at)
ORDER BY (stage, version)
COMMENT 'Stage versions that the code has run. Read with FINAL.';

-- The newest calculation of each step: its desired fingerprint, the files that it
-- selects and how long the calculation took. The coordinator and a requested check
-- write it. The admin pages read only this table and the two below, so a page load runs
-- no count query. `step_id = ''` holds the totals of the scope: unique files across all
-- waiting steps and the calculation time. `checked_at` is the version column.
CREATE TABLE IF NOT EXISTS processing_update_checks
(
    scope_kind LowCardinality(String) COMMENT 'dataset or collection',
    scope_id String COMMENT 'collection_dataset or collectionname',
    collectionname LowCardinality(String),
    step_id LowCardinality(String) COMMENT 'Update step, empty for the totals row',
    desired_fingerprint String COMMENT 'What the step should produce now',
    pending_files UInt64 COMMENT 'Files that a manual run of the step changes',
    pending_bytes UInt64 COMMENT 'Bytes of those files',
    automatic_files UInt64 COMMENT 'Files that the automatic run may change, at most pending_files',
    executions UInt64 COMMENT 'Step runs of the scope, totals row only',
    detail String COMMENT 'JSON: version, target_key, input_revision, title, explanation, runs',
    check_ms UInt32 COMMENT 'Calculation time in milliseconds',
    checked_at DateTime64(6) COMMENT 'Calculation time, UTC, and the version column'
)
ENGINE = ReplacingMergeTree(checked_at)
ORDER BY (scope_id, step_id)
COMMENT 'Newest selection of each processing update step. Read with FINAL.';

-- One row for each step of each attempt. `row_version` follows the rule of the
-- operations table: a running row has rank 0 and a terminal row rank 1, in the top bits,
-- above a microsecond value, so a late progress write cannot replace a terminal row. A
-- running row whose operation row is terminal reads as that operation's end
-- (database/processing_updates.py). `snapshot` holds the fingerprint, the settings and
-- the input revision that the attempt ran for.
CREATE TABLE IF NOT EXISTS processing_update_attempts
(
    scope_kind LowCardinality(String),
    scope_id String,
    collectionname LowCardinality(String),
    step_id LowCardinality(String),
    op_id String COMMENT 'The update operation',
    desired_fingerprint String COMMENT 'The fingerprint of the snapshot',
    automatic UInt8 COMMENT '1 when the coordinator started the operation',
    state LowCardinality(String) COMMENT 'running, succeeded, failed, cancelled or skipped',
    error String,
    snapshot String COMMENT 'JSON of the step snapshot',
    started_at DateTime64(6),
    ended_at DateTime64(6) COMMENT 'Epoch 0 while running',
    row_version UInt64 COMMENT 'Rank and microseconds, see the header'
)
ENGINE = ReplacingMergeTree(row_version)
ORDER BY (scope_id, step_id, op_id)
COMMENT 'Attempts of processing update steps. Read with FINAL.';

-- The fingerprint that a step last produced and verified. Only output settlement writes
-- it, or a check that finds no file to change. An older attempt writes its own snapshot
-- fingerprint, so a newer desired fingerprint stays waiting. `applied_at` is the version.
CREATE TABLE IF NOT EXISTS processing_update_applied
(
    scope_kind LowCardinality(String),
    scope_id String,
    collectionname LowCardinality(String),
    step_id LowCardinality(String),
    applied_fingerprint String,
    op_id String COMMENT 'The operation that settled it, empty for a check without work',
    detail String COMMENT 'JSON of the snapshot that settled',
    applied_at DateTime64(6) COMMENT 'Settlement time, UTC, and the version column'
)
ENGINE = ReplacingMergeTree(applied_at)
ORDER BY (scope_id, step_id)
COMMENT 'Verified output of each processing update step. Read with FINAL.';

-- The automatic retry entitlement of failed files. A retry of a stage version for a
-- dataset claims the pair when its step starts. The automatic run retries only pairs
-- without a claim, so each changed stage version gets one automatic retry. A manual
-- retry claims too and stays available.
CREATE TABLE IF NOT EXISTS processing_retry_claims
(
    collection_dataset String,
    collectionname LowCardinality(String),
    stage LowCardinality(String),
    stage_version UInt32,
    op_id String,
    claimed_at DateTime64(6) COMMENT 'Version column'
)
ENGINE = ReplacingMergeTree(claimed_at)
ORDER BY (collection_dataset, stage, stage_version)
COMMENT 'Automatic retry claims of failed stage versions. Read with FINAL.'
