-- Per-user settings of the website.
--
-- One row per user and key. The website is the only writer. A write inserts a new row
-- with a later updated_at, and a cleared setting writes is_deleted = 1. Readers use FINAL.
-- Keys: ui.language holds the interface language code. agent.language holds the agent
-- language code, and an empty value means the interface language.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS user_settings
(
    username LowCardinality(String) COMMENT 'The user that owns the setting',
    key LowCardinality(String) COMMENT 'The setting name, for example ui.language',
    value String DEFAULT '' COMMENT 'The setting value',
    updated_at DateTime64(3) DEFAULT now64(3) COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (username, key)
COMMENT 'Website settings of each user, such as the interface and agent languages.'
