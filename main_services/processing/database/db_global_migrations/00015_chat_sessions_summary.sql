-- AI Chat: one-or-two sentence LLM summary shown on the homepage cards.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on
-- that character without parsing quotes or comments.
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summary String DEFAULT '' COMMENT 'One-or-two sentence LLM summary shown on the homepage cards';
