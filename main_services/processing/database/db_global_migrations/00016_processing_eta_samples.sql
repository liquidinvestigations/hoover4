-- Rolling history of processing deadline estimates, written by the
-- CollectEtaSamples workflow (tasks/P_admin) and read by the admin processing page.
--
-- Global rather than per-collection: one query then serves the whole admin UI,
-- and the collector walks every collection in a single pass anyway.
CREATE TABLE IF NOT EXISTS processing_eta_samples
(
    collectionname LowCardinality(String),
    collection_dataset String,
    stage LowCardinality(String) COMMENT 'One of the STAGE_* constants in processing_types.rs',
    sampled_at DateTime,
    done UInt64,
    total UInt64,
    rate_items_per_sec Float64,
    rate_bytes_per_sec Float64,
    eta_seconds UInt64 COMMENT '0 when no estimate could be made',
    deadline DateTime COMMENT 'sampled_at + eta_seconds, what the chart plots',
    collection_duration_ms UInt32 COMMENT 'How long this sample cost to compute, for the 20x throttle'
)
ENGINE = ReplacingMergeTree(sampled_at)
ORDER BY (collectionname, collection_dataset, stage, sampled_at)
TTL sampled_at + INTERVAL 30 DAY
COMMENT 'Rolling history of processing deadline estimates, newest 100 per stage shown on the admin page.';
