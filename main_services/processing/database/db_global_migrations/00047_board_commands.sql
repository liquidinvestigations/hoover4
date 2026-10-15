-- The command storage of investigation boards.
--
-- Every state change of a board is a command. A writer stores the command input, and the
-- per-board workflow BoardCommands (tasks/P_board/command_workflows.py) handles the inputs of
-- one board in order. It prepares each command against the committed state, freezes the
-- prepared rows in a receipt, writes those rows, and marks the receipt committed. A retry
-- writes the same prepared rows again, so one request never allocates a second node id.
--
-- Writers:
--   board_command_inputs    the website for person actions, the board activities for the
--                           dispatcher and the explores. Rows are immutable
--   board_command_receipts  BoardCommands only
--
-- The receipts keep request identity and node allocation after the closed workflow history
-- is gone, so neither table expires. Dropping a board deletes its rows of both tables.
--
-- A fact that a command writes carries the request id of the command. Readers show such a
-- fact only when a board event carries the same request id. A fact with an empty request id
-- has no command, and readers always show it.
--
-- Every read uses FINAL.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS board_command_inputs
(
    board_id String COMMENT 'Board id',
    request_id String COMMENT 'Identity of one deliberate action. A retry of the action keeps it',
    payload_digest String COMMENT 'sha256 of the canonical JSON body. Two bodies under one request id conflict',
    actor LowCardinality(String) COMMENT 'Username, or dispatcher, reason, explore, labels',
    kind LowCardinality(String) COMMENT 'Command kind, see tasks/P_board/commands.py',
    body_json String COMMENT 'The validated command body as JSON',
    submitted_at DateTime64(3) COMMENT 'Write time. Orders the pending inputs of a board'
)
ENGINE = ReplacingMergeTree(submitted_at)
ORDER BY (board_id, request_id, payload_digest)
COMMENT 'Board command inputs. Writers: website and board activities';

-- version is the phase of the receipt: 1 prepared, 2 committed or rejected. A late retry of
-- the prepared write cannot replace a committed receipt.
CREATE TABLE IF NOT EXISTS board_command_receipts
(
    board_id String COMMENT 'Board id',
    request_id String COMMENT 'The request this receipt decides',
    payload_digest String COMMENT 'The digest of the accepted input. Another digest of the request is a conflict',
    kind LowCardinality(String) COMMENT 'Command kind of the accepted input',
    state LowCardinality(String) COMMENT 'prepared, committed or rejected',
    seq_start UInt64 COMMENT 'First canonical event sequence number of the command, 0 for none',
    seq_end UInt64 COMMENT 'Last canonical event sequence number of the command, 0 for none',
    prepared_json String COMMENT 'The frozen rows: events, facts, citations, labels and node assignments',
    result_json String COMMENT 'The result that a status read returns',
    error String COMMENT 'Why a rejected command was refused',
    version UInt64 COMMENT 'Phase of the receipt, 1 prepared, 2 committed or rejected',
    created_at DateTime64(3) COMMENT 'Time of the prepared write',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (board_id, request_id)
COMMENT 'Board command receipts. Writer: BoardCommands only';

ALTER TABLE board_facts
    ADD COLUMN IF NOT EXISTS request_id String DEFAULT ''
    COMMENT 'The command that wrote the fact, empty for a fact without a command. Readers show the fact once an event carries this id'
    AFTER created_by;
