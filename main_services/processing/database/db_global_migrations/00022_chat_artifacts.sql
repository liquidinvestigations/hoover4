-- The index of everything a chat tool produced that is too big to put
-- in the model's context but that the user should still be able to see -- the full
-- before/after ordering of a web search, the captured HTML and screenshot of a page the
-- agent visited.
--
-- The bytes live in the blob store under derived/chat-artifacts/<session>/<id>/. This table is the
-- SOLE index of their existence: P0_scan_disk never walks that prefix (an artifact the
-- ingest walker can see would be ingested, captured again, and produce another artifact,
-- forever), so nothing else in the system knows those objects are there. verify-stack.sh
-- asserts that no blobs row references derived/.
--
-- artifact_id is what the model receives, and it is a lookup key rather than a
-- capability: the website resolves it to session_id/username and enforces owner-or-admin
-- before serving a byte. username is denormalised so that check never has to join.
--
-- ReplacingMergeTree with is_deleted gives the retention sweeper a soft delete: a
-- ClickHouse TTL cannot remove blob-store objects, so rows are tombstoned first, the objects
-- deleted, and only then are the rows dropped.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS chat_artifacts
(
    artifact_id   String                 COMMENT 'UUID, the only handle the model and the browser ever see',
    session_id    String                 COMMENT 'FK chat_sessions.session_id -- the ACL is resolved through this',
    username      LowCardinality(String) COMMENT 'Owner, denormalised so a read never joins to prove ownership',
    kind          LowCardinality(String) COMMENT 'page_capture | search_detail',
    tool_name     LowCardinality(String) COMMENT 'Tool that produced it',
    url           String   DEFAULT ''    COMMENT 'Page URL for page_capture, empty otherwise',
    title         String   DEFAULT '',
    thumb_key     String   DEFAULT ''    COMMENT 'Blob-store object key of the 1280x720 WebP, empty when none',
    body_key      String   DEFAULT ''    COMMENT 'Blob-store object key of the self-contained HTML or JSON detail',
    body_bytes    UInt64   DEFAULT 0,
    thumb_bytes   UInt64   DEFAULT 0,
    status        LowCardinality(String) DEFAULT 'ok' COMMENT 'ok | too_large | failed',
    detail        String   DEFAULT ''    COMMENT 'Why, when status is not ok -- shown on the card',
    created_at    DateTime DEFAULT now(),
    updated_at    DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted    UInt8    DEFAULT 0     COMMENT 'Soft-delete tombstone. The sweeper removes the objects, then the rows'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (username, session_id, artifact_id)
COMMENT 'Chat tool artifacts: captured pages and search detail. Bytes live in the blob store under the derived prefix and this table is the sole index of their existence.';
