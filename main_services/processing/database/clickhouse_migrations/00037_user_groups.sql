CREATE TABLE IF NOT EXISTS user_groups
(
    groupname LowCardinality(String) COMMENT 'Unique group identifier, from X-Forwarded-Groups or admin UI',
    fullname String DEFAULT '' COMMENT 'Human-readable group display name',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (groupname)
COMMENT 'User groups; membership grants collection read permissions.';

INSERT INTO user_groups (groupname, fullname) VALUES ('admin', 'Administrators');
INSERT INTO user_groups (groupname, fullname) VALUES ('superuser', 'Superusers');
