CREATE TABLE IF NOT EXISTS operations_row_version
(
    op_id String,
    kind LowCardinality(String),
    target_kind LowCardinality(String),
    collectionname LowCardinality(String),
    collection_dataset String,
    state LowCardinality(String),
    started_at DateTime,
    finished_at DateTime DEFAULT toDateTime(0),
    updated_at DateTime DEFAULT now(),
    progress_done UInt64,
    progress_total UInt64,
    eta_seconds UInt32,
    detail String DEFAULT '',
    error String DEFAULT '',
    user_id String,
    rerun_of String DEFAULT '',
    row_version UInt64
)
ENGINE = ReplacingMergeTree(row_version)
ORDER BY (started_at, op_id);

INSERT INTO operations_row_version
SELECT op_id, kind, target_kind, collectionname, collection_dataset,
       state, started_at, finished_at, updated_at,
       progress_done, progress_total, eta_seconds, detail, error, user_id, rerun_of,
       bitShiftLeft(multiIf(state = 'cancelled', toUInt64(2),
                            state IN ('finished', 'errored'), toUInt64(1), toUInt64(0)), 62)
       + toUInt64(toUnixTimestamp64Micro(toDateTime64(updated_at, 6)))
FROM operations FINAL;

RENAME TABLE operations TO operations_updated_at, operations_row_version TO operations;

DROP TABLE operations_updated_at;
