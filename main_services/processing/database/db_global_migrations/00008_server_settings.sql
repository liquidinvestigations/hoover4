CREATE TABLE IF NOT EXISTS server_settings
(
    key LowCardinality(String) COMMENT 'Setting name',
    value String COMMENT 'Setting value, stored as string',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (key)
COMMENT 'Key-value server configuration editable from /admin/settings.';

INSERT INTO server_settings (key, value) VALUES ('session_expiration_seconds', '604800');
INSERT INTO server_settings (key, value) VALUES ('guest_permissions_mode', 'all');
