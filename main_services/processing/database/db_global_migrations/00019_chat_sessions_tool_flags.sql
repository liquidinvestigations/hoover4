-- AI Chat: freeze the Deep Research / Internet tools choice onto the conversation.
--
-- These two switches change which agent answers and therefore which tools exist. Once
-- a conversation has a turn in it the choice cannot be revised without making the
-- transcript incoherent -- half the answers would have had web access and half not --
-- so the UI locks them after the first message and reads the locked values from here.
-- Before the first message both are unset and the composer defaults apply.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on
-- that character without parsing quotes or comments.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS use_internet_tools UInt8 DEFAULT 0 COMMENT 'Locked at the first turn - selects the full research agent with web tools';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS deep_research UInt8 DEFAULT 0 COMMENT 'Locked at the first turn - routes turns to the Temporal ResearchTask instead of answering inline';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS options_locked UInt8 DEFAULT 0 COMMENT 'Set once the first message is sent - after this the two switches above are read-only';
