-- The prompt and the reply of each assessment of an investigation board.
--
-- One writer: the activity board_reason in tasks/P_board/activities.py, after its model call
-- and before its reason_result event. The website reads one row for the assessment details
-- popup of the board page, and deletes the rows of a board when the board is dropped.
--
-- A row is keyed by board and assessment number (the subject of the reason_result event). The
-- newest created_at wins, so a retried activity replaces its row and a read uses FINAL. An
-- assessment that ran before this table existed has no row. The page then shows the raw
-- reply that its event holds.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS board_assessments
(
    board_id String COMMENT 'Board id',
    reason_no UInt32 COMMENT 'Assessment number, the subject of its reason_result event',
    prompt String COMMENT 'The whole prompt of the model call',
    reply String COMMENT 'The whole reply text, empty when the call failed',
    error String COMMENT 'The call error, empty when the call returned',
    model String COMMENT 'Model of the call',
    created_at DateTime64(3) COMMENT 'Write time, the version'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (board_id, reason_no)
COMMENT 'Prompt and reply of each board assessment. Writer: tasks/P_board/activities.py board_reason';
