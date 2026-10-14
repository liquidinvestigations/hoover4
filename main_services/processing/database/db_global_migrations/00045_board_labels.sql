-- Generated labels of board nodes, and the summary of each board.
--
-- One writer: the activity label_board in tasks/P_board/labels.py. The website reads the rows
-- and deletes them when a board is dropped. A label is a display name. The storage ids of
-- facts and intents do not change.
--
-- A row is keyed by board and node. node_id is empty for the summary of the board. The newest
-- updated_at wins, so a read uses FINAL. A slug, once written, stays. A changed source text
-- gives a new title and summary under the same slug.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS board_labels
(
    board_id String COMMENT 'Board id',
    node_id String COMMENT 'Fact id or intent id, empty for the summary of the board',
    node_kind LowCardinality(String) COMMENT 'intent, fact, correction or board',
    slug String COMMENT 'Display name and address key, unique in one board, empty for the board and for a node without a label yet',
    title String COMMENT 'Three or four words',
    summary String COMMENT 'Fifteen to twenty words for a node, ten to fifteen for the board',
    source_hash String COMMENT 'sha256 of the text the label was made from',
    model String COMMENT 'Model that wrote the label, or fallback',
    attempts UInt8 DEFAULT 0 COMMENT 'Failed model attempts for a node that has no label yet',
    created_at DateTime64(3) COMMENT 'First write',
    updated_at DateTime64(3) COMMENT 'Write time, the version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (board_id, node_id)
COMMENT 'Generated labels of board nodes. Writer: tasks/P_board/labels.py';
