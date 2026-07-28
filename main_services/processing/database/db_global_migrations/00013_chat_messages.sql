-- AI Chat: the message trajectory of a conversation.
--
-- One row per turn *and* per tool call, so the UI can render what the agent did, not
-- just what it concluded. `seq` orders them within a session and is assigned by the
-- backend rather than derived from the timestamp, because a user message and the tool
-- calls it triggers can land inside the same second.
--
-- `username` is denormalised onto every message so a read never has to join
-- `chat_sessions` to prove ownership — the ACL check is a WHERE clause on the same
-- table as the data.
CREATE TABLE IF NOT EXISTS chat_messages
(
    session_id String COMMENT 'FK chat_sessions.session_id',
    username LowCardinality(String) COMMENT 'Owner, denormalised for permission filtering',
    seq UInt32 COMMENT 'Position within the conversation, 0-based',
    role LowCardinality(String) COMMENT 'user | assistant | tool | error',
    content String COMMENT 'Message text. For tool rows, a JSON summary of the call',
    tool_name String DEFAULT '' COMMENT 'Tool invoked, for role = tool',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (username, session_id, seq)
COMMENT 'AI Chat message trajectory: user turns, assistant answers and tool calls.';
