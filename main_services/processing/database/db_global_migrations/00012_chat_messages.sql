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
    -- The whole tool call, not only a 400-char summary: the UI renders arguments and
    -- results behind a disclosure, and truncating them here would make that impossible.
    tool_input String DEFAULT '' COMMENT 'JSON arguments the model passed to the tool',
    tool_output String DEFAULT '' COMMENT 'JSON result, truncated to TOOL_PAYLOAD_CHARS',
    doc_refs String DEFAULT '' COMMENT 'JSON array of documents this step surfaced, for result cards',
    -- The agent call is retried with exponential backoff. When every attempt fails the
    -- transcript gets one error row, and the final error is often the least informative
    -- of the set -- a timeout that followed a real 500 says much less than the 500 did.
    retry_errors String DEFAULT '' COMMENT 'JSON array of the errors from earlier attempts, oldest first. Empty when the turn succeeded first try',
    -- Model selection is per message, not frozen on the session: a mid-conversation model
    -- change is coherent in a way a mid-conversation tool-set change is not.
    model LowCardinality(String) DEFAULT '' COMMENT 'LLM model id that produced this row, empty for user turns',
    reasoning String DEFAULT '' COMMENT 'Reasoning/thinking content stripped out of the answer body, rendered behind a disclosure',
    created_ms DateTime64(3) DEFAULT now64(3) COMMENT 'Millisecond creation time. created_at has second granularity and cannot order a turn against the tool calls it triggered',
    agent_duration_ms UInt32 DEFAULT 0 COMMENT 'Wall time the agent took to produce this row, 0 for user turns',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (username, session_id, seq)
COMMENT 'AI Chat message trajectory: user turns, assistant answers and tool calls.';
