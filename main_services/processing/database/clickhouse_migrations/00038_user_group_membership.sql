CREATE TABLE IF NOT EXISTS user_group_membership
(
    username LowCardinality(String) COMMENT 'FK users.username',
    groupname LowCardinality(String) COMMENT 'FK user_groups.groupname',
    is_group_admin Bool DEFAULT false COMMENT 'Group admin flag; stored only, grants nothing yet',
    origin LowCardinality(String) DEFAULT 'manual' COMMENT 'header = synced from X-Forwarded-Groups (reconciled on login), manual = created in admin UI',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (username, groupname)
COMMENT 'N:M user to group membership.';
