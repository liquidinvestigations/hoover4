CREATE TABLE IF NOT EXISTS collection_group_permissions
(
    groupname LowCardinality(String) COMMENT 'FK user_groups.groupname',
    collectionname LowCardinality(String) COMMENT 'FK collections.collectionname',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone (= permission revoked)'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (groupname, collectionname)
COMMENT 'Row present (and not deleted) = members of group can read the collection.';
