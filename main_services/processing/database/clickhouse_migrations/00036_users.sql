CREATE TABLE IF NOT EXISTS users
(
    username LowCardinality(String) COMMENT 'Unique login name from X-Forwarded-User, or generated guest-N id',
    fullname String DEFAULT '' COMMENT 'Display name from X-Forwarded-Preferred-Username',
    email String DEFAULT '' COMMENT 'Email from X-Forwarded-Email',
    is_admin Bool COMMENT 'True if forwarded groups include admin or superuser (header users), or set manually',
    created_at DateTime DEFAULT now() COMMENT 'ISO datetime when user was first seen',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (username)
COMMENT 'Website users, auto-provisioned from reverse-proxy headers or guest fallback.';
