-- In-flight assistant output. Partial writes live here so that chat_messages keeps its
-- write-once-per-completed-row discipline.
--
-- Chat streams by adaptive long-poll rather than SSE: the reader holds a request up to
-- 15s when nothing changes and returns immediately with a 500ms floor while tokens flow.
-- Every poll writes and reads this table, so the row is rewritten many times per turn --
-- which is exactly what chat_messages must not do.
--
-- Two rules the read path must follow. Both are commonly got wrong:
--
--   1. Read with argMax(content, updated_at), never a bare SELECT. A ReplacingMergeTree
--      read without FINAL or argMax can return an older part, and the visible text would
--      shrink mid-stream -- the precise jitter the requirement forbids.
--   2. chat_messages wins. If a completed row exists for a seq, ignore any stream row for
--      it: finalisation and the last partial write race by construction.
--
-- Do not trust the TTL either. Merges apply it lazily, so filter on updated_at as well --
-- the same lesson usage_events already documents.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS chat_message_stream
(
    session_id String COMMENT 'FK chat_sessions.session_id',
    username   LowCardinality(String) COMMENT 'Owner, denormalised for permission filtering',
    seq        UInt32   COMMENT 'Same seq space as chat_messages',
    role       LowCardinality(String) COMMENT 'assistant | tool',
    content    String   COMMENT 'Partial content so far, monotonically growing',
    reasoning  String DEFAULT '' COMMENT 'Partial reasoning content, rendered behind a disclosure and never in the answer body',
    tool_name  String DEFAULT '',
    is_final   UInt8  DEFAULT 0 COMMENT 'Last write before the row moves to chat_messages',
    updated_at DateTime64(3) DEFAULT now64(3) COMMENT 'Version column, and the staleness clock for detecting an interrupted turn'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (username, session_id, seq)
TTL toDateTime(updated_at) + INTERVAL 1 HOUR DELETE
COMMENT 'In-flight assistant output, TTL 1h. chat_messages holds completed turns.';
