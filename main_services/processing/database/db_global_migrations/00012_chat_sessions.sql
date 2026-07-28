-- AI Chat: one row per conversation.
--
-- Global rather than per-collection: a conversation may range over several collections
-- (whichever the user picked), so it belongs to no single collection database.
--
-- Ownership is by `username`, and every read path filters on it. A chat transcript can
-- quote documents from restricted collections, so a session must never be reachable by
-- anyone but its owner — not even by another user who happens to know the id.
CREATE TABLE IF NOT EXISTS chat_sessions
(
    session_id String COMMENT 'Unique conversation id (uuid)',
    username LowCardinality(String) COMMENT 'Owner. Every query filters on this.',
    title String DEFAULT '' COMMENT 'Display title, seeded from the first user message',
    -- NOTE: keep semicolons out of this file except as the final statement terminator.
    -- The migration runner splits a multi-statement file on that character without
    -- parsing quotes or comments, so one anywhere else truncates the statement and
    -- fails with "Single quoted string is not closed" or "Unmatched parentheses".
    collections Array(String) COMMENT 'Collections the user selected for this chat, re-checked against live permissions on every message. A preference, not a grant.',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree, and the sort key of the session list',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (username, session_id)
COMMENT 'AI Chat conversations, owned by a user.';
