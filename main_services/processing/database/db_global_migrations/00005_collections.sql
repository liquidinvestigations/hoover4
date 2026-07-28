CREATE TABLE IF NOT EXISTS collections
(
    collectionname LowCardinality(String) COMMENT 'Unique collection identifier (slug)',
    fullname String DEFAULT '' COMMENT 'Human-readable collection display name',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collectionname)
COMMENT 'Collections group datasets for permissioning and admin.';
