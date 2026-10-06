ALTER TABLE text_content ADD COLUMN IF NOT EXISTS language LowCardinality(String) DEFAULT 'und' COMMENT 'Language code of the complete text source';

CREATE TABLE IF NOT EXISTS signal_hit
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of this text source',
    file_hash String COMMENT 'Source document content hash',
    extracted_by String COMMENT 'Stored text source identifier',
    page_id UInt32 COMMENT 'One-based text page or segment',
    signal_set_version String COMMENT 'Content hash of the scanner lexicon',
    category LowCardinality(String) COMMENT 'Signal category identifier',
    starts Array(UInt32) COMMENT 'UTF-8 byte starts in cleaned text',
    ends Array(UInt32) COMMENT 'UTF-8 byte ends in cleaned text',
    terms Array(String) COMMENT 'Matched lexicon terms',
    concepts Array(String) COMMENT 'Shared concept identifiers',
    languages Array(String) COMMENT 'Lexicon languages',
    tiers Array(String) COMMENT 'Lexicon tiers L M or H',
    speakers Array(String) COMMENT 'Lexicon speaker classes',
    flags Array(Array(String)) COMMENT 'Flags of each occurrence',
    texts Array(String) COMMENT 'Exact matched source text',
    text_digest String COMMENT 'SHA-256 of the cleaned UTF-8 text',
    scan_version UInt64 COMMENT 'Version of this completed scan'
)
ENGINE = ReplacingMergeTree(scan_version)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, signal_set_version, category)
COMMENT 'Signal occurrences with parallel arrays and byte offsets';

CREATE TABLE IF NOT EXISTS signal_scanned
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of this text source',
    file_hash String COMMENT 'Source document content hash',
    extracted_by String COMMENT 'Stored text source identifier',
    page_id UInt32 COMMENT 'One-based text page or segment',
    signal_set_version String COMMENT 'Lexicon version that completed scanning',
    text_version UInt64 COMMENT 'Stored text version that was scanned',
    text_digest String COMMENT 'SHA-256 of the cleaned UTF-8 text',
    scan_version UInt64 COMMENT 'Version of the completed scan'
)
ENGINE = ReplacingMergeTree(scan_version)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, signal_set_version)
COMMENT 'Completed signal scans including pages with no hits';

CREATE TABLE IF NOT EXISTS signal_cluster
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of this text source',
    file_hash String COMMENT 'Source document content hash',
    extracted_by String COMMENT 'Stored text source identifier',
    page_id UInt32 COMMENT 'One-based text page or segment',
    category LowCardinality(String) COMMENT 'Qualifying category identifier',
    calibration_hash String COMMENT 'Hash of the scoring configuration',
    start UInt32 COMMENT 'UTF-8 byte start of the cluster',
    end UInt32 COMMENT 'UTF-8 byte end of the cluster',
    points Float64 COMMENT 'Greatest qualifying window score',
    text_digest String COMMENT 'SHA-256 of the scored cleaned text',
    excerpt String COMMENT 'Exact cleaned source excerpt' CODEC(ZSTD(3)),
    hit_starts Array(UInt32) COMMENT 'Relative UTF-8 starts within the excerpt',
    hit_ends Array(UInt32) COMMENT 'Relative UTF-8 ends within the excerpt',
    write_version UInt64 COMMENT 'Version of this complete page replacement'
)
ENGINE = ReplacingMergeTree(write_version)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, category, calibration_hash, start)
COMMENT 'Scored red flag passages computed by the indexer';

CREATE TABLE IF NOT EXISTS signal_storage_ready (ok UInt8) ENGINE = TinyLog;
