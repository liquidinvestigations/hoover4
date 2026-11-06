ALTER TABLE ocr_detection ADD COLUMN IF NOT EXISTS model String DEFAULT '';

CREATE TABLE IF NOT EXISTS automatic_ocr_plans
(
    collection_dataset LowCardinality(String),
    hash String,
    plan_digest String,
    source_revision String,
    capability_digest String,
    policy_version UInt16,
    expected_pages UInt32,
    plan_json String,
    state LowCardinality(String),
    reason String DEFAULT '',
    has_ocr_output UInt8 DEFAULT 0,
    revision UInt64
)
ENGINE = ReplacingMergeTree(revision)
ORDER BY (collection_dataset, hash, plan_digest);

CREATE TABLE IF NOT EXISTS automatic_ocr_output
(
    collection_dataset LowCardinality(String),
    hash String,
    plan_digest String,
    output_id String,
    payload String,
    revision UInt64
)
ENGINE = ReplacingMergeTree(revision)
ORDER BY (collection_dataset, hash, plan_digest, output_id);

CREATE TABLE IF NOT EXISTS automatic_ocr_ready (ok UInt8) ENGINE = TinyLog;
