-- The references of the texts that people send to a model.
--
-- A reference is a Hoover link that a person pasted into a chat message or a board text.
-- The text holds the marker [R1], [R2] and so on at the place of each link. This column holds
-- the JSON array of the references, each with its handle, link, label, kind, tool, arguments
-- and url. An empty value means no reference.
--
-- chat_messages: the website writes it on a user row. The worker reads it when the turn
-- opens and gives the model the text with a References block. A board explore writes it on
-- the user row of its brief.
-- board_facts: the command writer writes it on a goal, the background and a correction.
-- board_events: the command writer writes it on a hint, a goal, a rejection, a correction and
-- a question of a person. The command writer numbers the references of one board in one
-- sequence.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS references_json String DEFAULT ''
    COMMENT 'JSON array of the references of a user row, empty for none'
    AFTER usage_json;

ALTER TABLE board_facts
    ADD COLUMN IF NOT EXISTS references_json String DEFAULT ''
    COMMENT 'JSON array of the references of a goal, the background or a correction'
    AFTER request_id;

ALTER TABLE board_events
    ADD COLUMN IF NOT EXISTS references_json String DEFAULT ''
    COMMENT 'JSON array of the references of the text of a person in this event'
    AFTER created_at
