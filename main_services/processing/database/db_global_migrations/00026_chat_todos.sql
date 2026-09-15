-- The agent's plan for one chat session: a goal and a list of items.
--
-- One logical list per chat session, held as whole-list snapshots rather than one row per
-- item. The list is read and rewritten as a unit by every one of the four tools, and the
-- nag protocol has to compare a whole list against the previous whole list to decide
-- whether it changed, so a per-item table would have to be reassembled on every read for
-- no benefit.
--
-- version is the update counter. It starts at 1 and every write increments it, and it is
-- part of the sort key, so every version is its own row and history survives -- a read that
-- asks for an earlier version still finds it. The current list is the highest version,
-- read with ORDER BY version DESC LIMIT 1.
--
-- The engine is ReplacingMergeTree over that same key so a retried insert of a version
-- already written collapses instead of doubling the row. It never removes an older version,
-- because the version is in the key that decides what a duplicate is.
--
-- items is a JSON array of objects with id, text, status and note. It is a string and not
-- a nested column on purpose: the shape is written and read only by the todo tools, which
-- validate it, and a nested column would make adding a field to an item a migration.
--
-- status of an item is one of pending, in_progress, done, cancelled. cancelled requires a
-- note -- an item abandoned with a reason counts as resolved for the nag, and requiring the
-- reason is what stops cancellation becoming a free exit from a plan.
--
-- There is no TTL. A todo outlives the turn that wrote it, and a chat session that is
-- deleted deletes its rows explicitly.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS chat_todos
(
    session_id String COMMENT 'FK chat_sessions.session_id',
    username   LowCardinality(String) COMMENT 'Owner, denormalised for permission filtering',
    version    UInt32 COMMENT 'Update counter, starting at 1. Also the ReplacingMergeTree version column',
    goal       String DEFAULT '' COMMENT 'The long-term objective, freely rewritten by write_todo',
    items      String DEFAULT '[]' COMMENT 'JSON array of {id, text, status, note}',
    updated_at DateTime64(3) DEFAULT now64(3) COMMENT 'When this version was written'
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (username, session_id, version)
COMMENT 'One agent todo list per chat session, versioned on an update counter.';
