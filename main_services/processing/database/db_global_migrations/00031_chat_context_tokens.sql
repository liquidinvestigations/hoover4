-- Token accounting for a chat turn, so a percentage of the context window has a
-- numerator as well as a denominator.
--
-- Two numbers, not one, because they answer different questions and differ by an order
-- of magnitude. The conversation carried into a turn is only its user and assistant
-- text, while the list the model sees inside the turn also holds every tool result it
-- collected. Showing only the first understates what compaction is about, and showing
-- only the second makes an ordinary conversation look enormous.
--
-- context_tokens is what the provider counted for the first model call of the turn: the
-- system prompt, the tool schemas, the history and the question. It is the standing cost
-- of the conversation.
--
-- peak_context_tokens is the largest prompt-plus-completion any single model call in the
-- turn was billed for. It is the number a compaction trigger fires on.
--
-- context_window is copied onto the row from the model catalog at the time of the turn,
-- because the catalog is refreshed and a model re-listed with a different window would
-- otherwise silently restate the past. 0 means the provider never said, and every reader
-- must render that as unknown rather than dividing by it.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS context_tokens UInt32 DEFAULT 0 COMMENT 'Prompt tokens of the first model call of this turn - the conversation as the model received it. 0 when unknown';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS peak_context_tokens UInt32 DEFAULT 0 COMMENT 'Largest prompt plus completion of any single model call in this turn. 0 when unknown';
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS context_window UInt32 DEFAULT 0 COMMENT 'Context window of the model that produced this row, copied from the catalog. 0 means the provider did not say and readers must show unknown';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS peak_context_tokens UInt32 DEFAULT 0 COMMENT 'Running maximum of peak_context_tokens over every turn of this conversation';
