-- Rolling 24h usage counters for the admin metrics page.
--
-- PRIVACY RULE, do not "improve" away: record only who, which broad route class,
-- and when. Never a URL, never a query string, never a document hash, never a
-- result count. A metrics table that accumulates search queries is a
-- surveillance log.
--
-- The TTL is applied by background merges, so rows can outlive 24h briefly.
-- Every read query must therefore filter on event_ts itself rather than trusting
-- the TTL.
CREATE TABLE IF NOT EXISTS usage_events
(
    username LowCardinality(String),
    event_type LowCardinality(String) COMMENT 'user_login | user_search | user_get_document | user_other_request | llm_chat_message | llm_mcp_tool_call',
    event_ts DateTime64(3) COMMENT 'Millisecond timestamp',
    metadata String DEFAULT '' COMMENT 'Small JSON blob. Broad route class only, never a URL or query text'
)
ENGINE = MergeTree
ORDER BY (username, event_type, event_ts)
TTL toDateTime(event_ts) + INTERVAL 24 HOUR DELETE
COMMENT 'Rolling 24h usage counters for the admin metrics page.';
