CREATE TABLE IF NOT EXISTS table_generation_owners
(
    file_hash String COMMENT 'Collection content hash',
    generation UInt32 COMMENT 'Allocated generation',
    attempt_token String COMMENT 'Exclusive writer identity',
    owner_op String COMMENT 'Operation that allocated the generation',
    state LowCardinality(String) COMMENT 'Writing, published, or retired',
    revision UInt64 DEFAULT toUInt64(toUnixTimestamp64Micro(now64(6))) COMMENT 'Command write revision'
)
ENGINE = ReplacingMergeTree(revision)
ORDER BY (file_hash, generation)
COMMENT 'Owned table generations. Writing generations do not expire.'
