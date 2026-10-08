-- Bug reports and feedback that people send from the website.
--
-- The website backend writes one row when a person sends a report, and a new row
-- version when an administrator marks it read or archived. The client creates
-- report_id before the first attempt, so a retried send writes the same key again.
-- The page image and the DOM copy are objects in the system bucket. The row keeps
-- their s3 paths, and only an administrator request reads them.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS feedback_reports
(
    report_id String COMMENT 'Identity that the client creates before the first send attempt',
    kind LowCardinality(String) COMMENT 'bug or feedback',
    title String COMMENT 'One-line title from the person',
    description String COMMENT 'Multiline description from the person',
    username String COMMENT 'Account of the authenticated request that sent the report',
    page_url String COMMENT 'Address of the page when the person opened the report',
    context_json String COMMENT 'Browser information, route state and collected log entries',
    screenshot_s3_path String COMMENT 'PNG image drawn from the DOM, empty when the capture failed',
    screenshot_bytes UInt64 COMMENT 'Size of the image object',
    dom_s3_path String COMMENT 'HTML copy of the DOM, empty when the capture failed',
    dom_bytes UInt64 COMMENT 'Size of the DOM object',
    created_at DateTime64(3) COMMENT 'When the backend received the report, UTC',
    is_read UInt8 COMMENT '1 after an administrator marks the report read',
    is_archived UInt8 COMMENT '1 after an administrator archives the report',
    row_version UInt64 COMMENT 'Version column, milliseconds since the epoch of the write'
)
ENGINE = ReplacingMergeTree(row_version)
ORDER BY report_id
COMMENT 'Bug reports and feedback from the website. Read with FINAL.';
