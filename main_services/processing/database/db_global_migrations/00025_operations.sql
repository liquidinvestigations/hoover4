-- The record that a long operation was asked for, by whom, and how it ended.
--
-- It exists because Temporal's namespace retention here is 24 hours and a CLI process is
-- mortal: without this table an ingest interrupted by a lost ssh session leaves a
-- half-built collection and no evidence anywhere that the command was ever run. The log
-- has no TTL, because it exists to answer that question about something that happened
-- longer ago than a workflow history survives.
--
-- op_id is also the Temporal workflow id, and it carries a timestamp, so two dispatches
-- can never collapse into one execution and every attempt gets its own row. Locking is a
-- separate question from identity: a second dispatch is refused while a non-terminal row
-- exists for the same kind and target, and a row that has stopped reporting is NOT
-- treated as free, because a run that stopped heartbeating may still have activities in
-- flight.
--
-- started_at leads the sort key because it is immutable for a given op_id and because
-- the admin list reads the newest rows first. With it first, that list reads the tail of
-- the primary key instead of sorting the table.
CREATE TABLE IF NOT EXISTS operations
(
    op_id String COMMENT 'kind-target-timestamp, and the Temporal workflow id',
    kind LowCardinality(String) COMMENT 'add_dataset, rescan_dataset, execute_plans, export_collection, ...',
    target_kind LowCardinality(String) COMMENT 'collection | dataset | global',
    collectionname LowCardinality(String) COMMENT 'Collection the operation acts on, empty for global kinds',
    collection_dataset String COMMENT 'Dataset the operation acts on, empty for collection and global kinds',
    state LowCardinality(String) COMMENT 'pending | running | finished | errored | cancelled',
    started_at DateTime COMMENT 'Immutable, and the newest-first sort key',
    finished_at DateTime DEFAULT toDateTime(0) COMMENT 'Terminal timestamp, epoch 0 while running',
    updated_at DateTime DEFAULT now() COMMENT 'Version column, and the staleness clock',
    progress_done UInt64 COMMENT 'Units completed, in whatever unit the kind counts',
    progress_total UInt64 COMMENT 'Units expected, 0 when not yet known',
    eta_seconds UInt32 COMMENT 'Seconds remaining, 0 when no estimate can be made',
    detail String DEFAULT '' COMMENT 'JSON: the parameters it was dispatched with, and per-stage counters',
    error String DEFAULT '' COMMENT 'Failure text, empty otherwise',
    user_id String COMMENT 'Who asked for it',
    rerun_of String DEFAULT '' COMMENT 'op_id this run was created from, empty for a first attempt'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (started_at, op_id)
COMMENT 'Every significant long-running operation, its progress and its outcome. Permanent.';
