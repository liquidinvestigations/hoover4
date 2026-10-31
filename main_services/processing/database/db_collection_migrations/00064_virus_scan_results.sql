-- One row per antivirus scan attempt of a file. The table keeps every attempt.
-- attempt_status is completed, incomplete, skipped_size, skipped_disabled or failed.
-- verdict is clean or infected on a completed attempt, and empty on every other attempt.
-- The effective verdict of a hash is the verdict of its completed attempt with the highest result_seq, in any dataset of the collection.
-- A failed, incomplete, skipped or disabled attempt therefore never replaces a known verdict.
-- result_seq orders the attempts. scan_version is the logical version of the stage and repeats across attempts.
-- collection_dataset is the dataset whose processing wrote the attempt, so a dataset purge reaches the rows.
CREATE TABLE IF NOT EXISTS virus_scan_results
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset whose processing wrote the attempt',
    hash String COMMENT 'Content hash of the scanned file',
    attempt_status LowCardinality(String) COMMENT 'completed, incomplete, skipped_size, skipped_disabled or failed',
    verdict LowCardinality(String) COMMENT 'clean or infected on a completed attempt, else empty',
    signature String COMMENT 'Signature name of an infected or incomplete result, else empty',
    engine_version String COMMENT 'ClamAV engine version that answered',
    database_version String COMMENT 'Signature database version that answered',
    config_fingerprint String COMMENT 'Hash of the clamd settings that change a verdict',
    scan_version UInt16 COMMENT 'Logical version of the scan stage',
    result_seq UInt64 COMMENT 'Monotonic attempt number, nanoseconds since the epoch of the attempt',
    error String COMMENT 'Why a failed attempt failed, else empty',
    scanned_at DateTime64(3) DEFAULT now64(3) COMMENT 'Write time, UTC'
)
ENGINE = MergeTree
ORDER BY (hash, result_seq)
