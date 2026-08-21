-- Streaming chat: what makes an in-flight turn collision-safe and progressively
-- renderable.
--
-- message_uuid: next_seq is max(seq)+1 with no database-side sequence behind it, so
-- two senders in one session can pick the same seq. Carrying a per-turn uuid on every
-- row makes that collision detectable (same seq, different uuid) instead of silently
-- keeping one message.
--
-- tool_call_index: a turn emits several tool rows before its answer. Each in-flight
-- tool row gets its own seq (the same seq the finalised chat_messages row will take),
-- and this index is its order within the turn, so the UI can show them appearing one
-- by one rather than all at once at the end.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE chat_message_stream ADD COLUMN IF NOT EXISTS message_uuid String DEFAULT '' COMMENT 'Per-turn uuid, shared by every row the turn writes. Detects seq collisions between two senders';
ALTER TABLE chat_message_stream ADD COLUMN IF NOT EXISTS tool_call_index UInt32 DEFAULT 0 COMMENT '0-based order of this tool row within its turn. 0 for the assistant row';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS message_uuid String DEFAULT '' COMMENT 'Per-turn uuid, shared by every row the turn writes. Detects seq collisions between two senders';
