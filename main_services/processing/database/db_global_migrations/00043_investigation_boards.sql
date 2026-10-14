-- Investigation boards. One board is a long-running investigation: a goal, board facts,
-- intents that agents explore, and the events of every action on it.
--
-- Each table has one writer, so no two components race on one ReplacingMergeTree row.
--   boards                the website, at creation and for the tombstone of a drop
--   board_events          every component. Each writer gives its event a deterministic id,
--                         so a retry replaces its own row and never adds a second one
--   board_state           the board_plan activity only. It folds the events into this row
--   board_intents         the board_plan activity only
--   board_facts           the website for origin, goal and corrections, conclude_explore
--                         for the fact of an intent. A writer checks that the fact is absent
--   board_fact_citations  the writer of the fact, in the same call
--
-- An explore runs as an ordinary chat turn in a chat session whose id starts with
-- board-. That prefix, not a column, marks the session (chat_sessions is rewritten whole
-- by its writers, so a new column there would be erased).
--
-- Every read uses FINAL. Without it a reader sees superseded state rows and the replaced
-- copy of a retried event.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS boards
(
    board_id String COMMENT 'Board id, a UUID in text form',
    owner LowCardinality(String) COMMENT 'The administrator who created the board. Only the owner can read it',
    title String COMMENT 'Display title',
    goal String COMMENT 'What the board must establish',
    context String COMMENT 'What is known and what is out of scope, written by the owner',
    collections Array(String) COMMENT 'Collections the explores may search, frozen at creation',
    llm_model String COMMENT 'Model of reason and explore turns, empty for the default chat model',
    max_explores UInt16 COMMENT 'Explore budget of the board',
    max_parallel UInt8 COMMENT 'Explores of this board that may run at once',
    explore_step_budget UInt16 COMMENT 'Model steps of one explore turn',
    created_at DateTime64(3) COMMENT 'Creation time',
    updated_at DateTime64(3) COMMENT 'Write time, the version',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Tombstone of a dropped board'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY board_id
COMMENT 'Board definitions. Writer: the website, see website/backend/src/api/admin/boards.rs';

CREATE TABLE IF NOT EXISTS board_events
(
    board_id String COMMENT 'Board id',
    event_id String COMMENT 'Deterministic id, type:subject:attempt or type:uuid',
    event_type LowCardinality(String) COMMENT 'See tasks/P_board/model.py for the list',
    actor LowCardinality(String) COMMENT 'Username, or dispatcher, reason, explore',
    subject String COMMENT 'The intent id, fact id or reason number the event is about',
    payload_json String COMMENT 'Event data as JSON',
    created_at DateTime64(3) COMMENT 'Write time. Orders the events of a board'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (board_id, event_id)
COMMENT 'The record of every action on a board. Writers: website and the board activities';

CREATE TABLE IF NOT EXISTS board_state
(
    board_id String COMMENT 'Board id',
    status LowCardinality(String) COMMENT 'active, paused, review, completed or dropped',
    explores_used UInt32 COMMENT 'Explore attempts that counted against the budget',
    reasons_done UInt32 COMMENT 'Reason results recorded',
    stall_count UInt8 COMMENT 'Explores in a row without a new sourced fact',
    invalid_reasons UInt8 COMMENT 'Invalid or empty reasons in a row with no open intent',
    checkpoint_json String COMMENT 'Counts at the last successful reason',
    summary_json String COMMENT 'Counts shown in the board list',
    version UInt64 COMMENT 'The dispatcher counter of this write',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(version)
ORDER BY board_id
COMMENT 'State derived from board_events. Writer: board_plan only';

CREATE TABLE IF NOT EXISTS board_intents
(
    board_id String COMMENT 'Board id',
    intent_id String COMMENT 'i<reason>.<index>',
    from_facts Array(String) COMMENT 'Board facts the intent starts from',
    objective String COMMENT 'What the explore must establish',
    brief String COMMENT 'What to search and what to return',
    state LowCardinality(String) COMMENT 'open, running, concluded, failed, question or cancelled',
    attempts UInt8 COMMENT 'Attempts that counted',
    session_id String COMMENT 'Chat session of the explore, board-<board>-<intent>',
    fact_id String COMMENT 'The fact the intent concluded in, empty until then',
    question String COMMENT 'The question an explore asked, empty otherwise',
    last_error String COMMENT 'Cause of the last failed attempt',
    created_at DateTime64(3) COMMENT 'Time of the reason result that declared it',
    version UInt64 COMMENT 'The dispatcher counter of this write',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (board_id, intent_id)
COMMENT 'Intents derived from board_events. Writer: board_plan only';

CREATE TABLE IF NOT EXISTS board_facts
(
    board_id String COMMENT 'Board id',
    fact_id String COMMENT 'origin, goal, f<reason>.<index> or c<uuid>',
    kind LowCardinality(String) COMMENT 'origin, goal, sourced, inferred, not_found or correction',
    text String COMMENT 'The finding, with session citation labels such as [D1]',
    intent_id String COMMENT 'The intent that produced it, empty for origin, goal and corrections',
    session_id String COMMENT 'Chat session of the explore, empty otherwise',
    answer_seq UInt32 COMMENT 'Transcript seq of the answer the fact came from, 0 otherwise',
    open_questions Array(String) COMMENT 'Directions the explore suggested, at most 3',
    problems Array(String) COMMENT 'Checks of conclude_explore that changed or marked the fact',
    created_by LowCardinality(String) COMMENT 'Username, or explore',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (board_id, fact_id)
COMMENT 'Board facts. Immutable after the first write. Writers: website, conclude_explore';

CREATE TABLE IF NOT EXISTS board_fact_citations
(
    board_id String COMMENT 'Board id',
    fact_id String COMMENT 'The cited fact',
    label String COMMENT 'Session handle without brackets, for example D1',
    collection_dataset String COMMENT 'Dataset of the cited document',
    collectionname String COMMENT 'Collection of the cited document',
    file_hash String COMMENT 'Full file hash of the cited document',
    path String COMMENT 'Path of the cited document',
    page_id UInt32 COMMENT 'Cited page, 0 when the citation names none',
    quote String COMMENT 'Quote the citation verified',
    quote_verified UInt8 COMMENT '1 when the collection server found the quote in the document',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (board_id, fact_id, label)
COMMENT 'Citations of board facts, resolved from the explore session. Writer: the fact writer';
