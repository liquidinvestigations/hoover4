-- Every chat and every investigation board belongs to one group.
--
-- owner_group is the group of the item. Every member of the group reads the item, continues
-- a chat and acts on a board. Only the creator (chat_sessions.username, boards.owner) and
-- administrators delete it. The website applies the rule (website/backend/src/auth/item_access.rs).
-- The creator stays the storage key of every row of a chat.
--
-- Every writer of chat_sessions and boards writes the whole row, so every writer carries
-- owner_group. A row without it has the empty group, and the empty group has no member.
--
-- A chat or board from before this migration has no group, so this migration deletes it.
-- A chat gets a tombstone row in chat_sessions (is_deleted = 1). The daily artifact sweeper
-- reads the tombstone and removes the artifacts of the chat with their blob-store objects.
-- The other rows of the chat are deleted here: messages, stream rows, plans, runs, run
-- messages, stop rows, compactions, workspace files and workspace receipts. The explore
-- chats of a board are chats with the prefix board-, so the same statements delete them.
-- A board loses its rows in every board table, and then its definition.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS owner_group String DEFAULT ''
    COMMENT 'The group of the chat. Every member reads and continues it. Empty belongs to nobody';

ALTER TABLE boards
    ADD COLUMN IF NOT EXISTS owner_group String DEFAULT ''
    COMMENT 'The group of the board. Every member reads it and acts on it. Empty belongs to nobody';

DELETE FROM chat_messages WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM chat_message_stream WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM chat_todos WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM agent_runs WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM agent_run_messages WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM agent_turn_stops WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM chat_compactions WHERE session_id IN
    (SELECT session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM chat_workspace_files WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

DELETE FROM chat_workspace_receipts WHERE (username, session_id) IN
    (SELECT username, session_id FROM chat_sessions WHERE owner_group = '');

INSERT INTO chat_sessions (session_id, username, title, summary, collections, created_at,
                           updated_at, is_deleted, use_internet_tools, options_locked,
                           peak_context_tokens, owner_group)
SELECT session_id, username, title, summary, collections, created_at,
       greatest(now(), updated_at + 1), 1, use_internet_tools, options_locked,
       peak_context_tokens, ''
FROM chat_sessions FINAL
WHERE owner_group = '' AND is_deleted = 0;

DELETE FROM board_events WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_state WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_intents WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_facts WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_fact_citations WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_labels WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_assessments WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_command_inputs WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM board_command_receipts WHERE board_id IN (SELECT board_id FROM boards WHERE owner_group = '');

DELETE FROM boards WHERE owner_group = '';
