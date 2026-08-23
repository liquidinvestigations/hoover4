-- What layer two of compaction left behind, added to the compaction trail.
--
-- Layer one evicts old tool results. Layer two runs when that was not enough: it drops
-- whole call-and-result groups and puts a structured handoff document in their place.
-- The transcript is still never edited, so this table remains the only record that a
-- model saw something different from what chat_messages holds - and for a summarisation
-- that difference is the model's own prose, which makes the record the only place the
-- replacement can be read back.
--
-- summary is the handoff document whole, not a digest of it. handles lists every
-- citation handle that had been issued when the compaction ran. All of them are carried
-- through by construction - the messages that issued them are never summarised - and
-- this column is what an answer's citations are checked against afterwards.
--
-- list_before and list_after are the model-visible message list either side of the
-- compaction, one line per message. Layer one rows carry them too.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE chat_compactions
    ADD COLUMN IF NOT EXISTS summary String DEFAULT '' COMMENT 'The handoff document layer two produced, whole. Empty for an eviction',
    ADD COLUMN IF NOT EXISTS summarised_count UInt32 DEFAULT 0 COMMENT 'Messages layer two replaced with the handoff document',
    ADD COLUMN IF NOT EXISTS preserved_count UInt32 DEFAULT 0 COMMENT 'Messages layer two copied through unchanged - the user turns, the todo, everything carrying a citation handle, and the most recent exchanges',
    ADD COLUMN IF NOT EXISTS handles Array(String) COMMENT 'Citation handles already issued when the compaction ran. Every one of them survives it',
    ADD COLUMN IF NOT EXISTS list_before String DEFAULT '' COMMENT 'Model-visible message list before the compaction, one line per message',
    ADD COLUMN IF NOT EXISTS list_after String DEFAULT '' COMMENT 'Model-visible message list after the compaction, one line per message';
