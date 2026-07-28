-- AI Chat: keep the whole tool call, not only a 400-char summary.
--
-- 00013 is history and must not be edited. ALTER is allowed above the collapsed
-- baseline of 10 (see tests/unit/test_migrations_parity.py).
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on
-- that character without parsing quotes or comments.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_input String DEFAULT '' COMMENT 'JSON arguments the model passed to the tool';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_output String DEFAULT '' COMMENT 'JSON result, truncated to TOOL_PAYLOAD_CHARS';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS doc_refs String DEFAULT '' COMMENT 'JSON array of documents this step surfaced, for result cards';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS created_ms DateTime64(3) DEFAULT now64(3) COMMENT 'Millisecond creation time. created_at has second granularity and cannot order a turn against the tool calls it triggered';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS agent_duration_ms UInt32 DEFAULT 0 COMMENT 'Wall time the agent took to produce this row, 0 for user turns';
