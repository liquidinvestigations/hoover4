-- Byte length of `text`, written at insert, so ETA sampling and anything else that
-- needs size never scans the body. Existing rows get 0 until they are rewritten.
ALTER TABLE text_content ADD COLUMN IF NOT EXISTS text_bytes UInt64 DEFAULT 0 COMMENT 'Byte length of text, written at insert';
