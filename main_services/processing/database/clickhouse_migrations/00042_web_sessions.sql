CREATE TABLE IF NOT EXISTS web_sessions
(
    session_id String COMMENT 'Random 256-bit hex token, stored in the hoover4_session cookie',
    username LowCardinality(String) COMMENT 'FK users.username (may be a guest-N user)',
    created_at DateTime DEFAULT now(),
    expires_at DateTime COMMENT 'created_at + server_settings.session_expiration_seconds',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone (= logout/invalidation)'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (session_id)
COMMENT 'Server-side web sessions; cookie holds only the session_id.';
